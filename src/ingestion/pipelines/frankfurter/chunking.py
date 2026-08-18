"""Troceado adaptativo de la ventana de fechas.

Es lo único de la capa de resiliencia que no delegamos: dlt reintenta un request
que falla, pero no sabe que el request se puede volver a hacer PIDIENDO MENOS. Y
no hay librería estándar para esto porque la decisión es de dominio: cuál es la
unidad divisible (días, ids, páginas) y qué error significa "pediste demasiado".

## Cómo funciona

Control de congestión, igual que TCP: **crecimiento aditivo, reducción
multiplicativa** (AIMD).

    - Arranca pidiendo la ventana más grande permitida (`max_days`). Para una
      carga histórica de 27 años, pedir de a un año es ~28 requests en vez de
      ~10.000 de a un día.
    - Si el origen falla con un error de tamaño (timeout, 5xx, payload demasiado
      grande), la ventana se DIVIDE y se reintenta el mismo tramo. Un año que no
      entra puede entrar en dos semestres.
    - Tras `successes_before_grow` tramos seguidos OK, la ventana CRECE de nuevo.
      Esto es lo que la hace adaptativa y no solo defensiva: si la API estaba
      lenta un rato, el pipeline vuelve solo al ritmo rápido en vez de terminar
      la carga entera de a un día.
    - Si un tramo del tamaño mínimo sigue fallando, el problema no es el tamaño:
      se registra el tramo como perdido y se sigue. El ETL no se cuelga por un
      día que la API no puede servir, y el tramo queda listado en los logs y en
      el resultado para reprocesarlo.

Progreso garantizado: cada iteración o avanza el cursor o reduce la ventana, y la
ventana tiene piso.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

# Errores que significan "la ventana era demasiado grande" y que por lo tanto
# vale la pena reintentar pidiendo menos. Llegan acá ya reintentados por dlt.
_WINDOW_ERROR_STATUS = frozenset({413, 414, 431, 500, 502, 503, 504, 507, 509})


def is_window_error(exc: BaseException) -> bool:
    """True si el error puede desaparecer pidiendo un rango más chico."""
    if isinstance(exc, requests.Timeout | requests.ConnectionError | requests.exceptions.ChunkedEncodingError):
        return True
    if isinstance(exc, requests.HTTPError):
        response = exc.response
        return response is not None and response.status_code in _WINDOW_ERROR_STATUS
    return False


@dataclass(frozen=True, slots=True)
class WindowPolicy:
    """Parámetros del control adaptativo.

    Attributes:
        max_days:              ventana inicial y techo, en días.
        min_days:              piso. Por debajo, el problema no es el tamaño.
        shrink_divisor:        por cuánto se divide la ventana al fallar.
        grow_factor:           por cuánto se multiplica al ir bien.
        successes_before_grow: tramos OK seguidos antes de volver a crecer.
    """

    max_days: int = 365
    min_days: int = 1
    shrink_divisor: float = 2.0
    grow_factor: float = 2.0
    successes_before_grow: int = 2

    def __post_init__(self) -> None:
        if self.min_days < 1 or self.max_days < self.min_days:
            raise ValueError(f"Ventana inválida: min={self.min_days} max={self.max_days}")
        if self.shrink_divisor <= 1 or self.grow_factor <= 1:
            raise ValueError("shrink_divisor y grow_factor tienen que ser > 1")


@dataclass
class WindowReport:
    """Qué pasó durante el recorrido. Se loguea y se devuelve al flow."""

    requests_ok: int = 0
    requests_failed: int = 0
    skipped_ranges: list[tuple[date, date, str]] = field(default_factory=list)
    min_window_used: int = 0
    max_window_used: int = 0

    @property
    def has_gaps(self) -> bool:
        return bool(self.skipped_ranges)

    def summary(self) -> dict[str, Any]:
        return {
            "requests_ok": self.requests_ok,
            "requests_failed": self.requests_failed,
            "ventana_min": self.min_window_used,
            "ventana_max": self.max_window_used,
            "tramos_perdidos": [f"{s.isoformat()}..{e.isoformat()} ({msg})" for s, e, msg in self.skipped_ranges],
        }


def fetch_adaptive[T](
    fetch: Callable[[date, date], T],
    date_from: date,
    date_to: date,
    policy: WindowPolicy,
    *,
    label: str = "",
    report: WindowReport | None = None,
) -> Iterator[T]:
    """Recorre `[date_from, date_to]` llamando a `fetch` con ventanas adaptativas.

    Args:
        fetch:    función que trae los datos de un rango cerrado de fechas.
        policy:   parámetros del control adaptativo.
        label:    nombre del recurso, para los logs.
        report:   acumulador de estadísticas; se crea uno si no se pasa.

    Yields:
        Lo que devuelva `fetch` por cada tramo exitoso.
    """
    if date_from > date_to:
        logger.info("%s: rango vacío (%s > %s), no hay nada que pedir.", label, date_from, date_to)
        return

    report = report if report is not None else WindowReport()
    size = policy.max_days
    cursor = date_from
    consecutive_ok = 0

    while cursor <= date_to:
        window_end = min(cursor + timedelta(days=size - 1), date_to)
        try:
            result = fetch(cursor, window_end)
        except Exception as exc:
            if not is_window_error(exc):
                raise  # no es un problema de tamaño: que lo vea el llamador

            report.requests_failed += 1
            if size > policy.min_days:
                size = max(policy.min_days, math.floor(size / policy.shrink_divisor))
                consecutive_ok = 0
                logger.warning(
                    "%s: falló %s..%s (%s) — reduzco la ventana a %s días y reintento.",
                    label,
                    cursor,
                    window_end,
                    type(exc).__name__,
                    size,
                )
                continue

            # Ya estamos en el mínimo: el tamaño no es el problema. Se registra y
            # se avanza para no bloquear el resto de la carga.
            report.skipped_ranges.append((cursor, window_end, f"{type(exc).__name__}: {exc}"))
            logger.error(
                "%s: %s..%s falla incluso con la ventana mínima (%s días) — se saltea. %s",
                label,
                cursor,
                window_end,
                policy.min_days,
                exc,
            )
            cursor = window_end + timedelta(days=1)
            continue

        report.requests_ok += 1
        report.max_window_used = max(report.max_window_used, size)
        report.min_window_used = size if report.min_window_used == 0 else min(report.min_window_used, size)
        yield result

        cursor = window_end + timedelta(days=1)
        consecutive_ok += 1
        if consecutive_ok >= policy.successes_before_grow and size < policy.max_days:
            size = min(policy.max_days, math.ceil(size * policy.grow_factor))
            consecutive_ok = 0
            logger.info(
                "%s: %s tramos OK seguidos — subo la ventana a %s días.", label, policy.successes_before_grow, size
            )

    level = logging.WARNING if report.has_gaps else logging.INFO
    logger.log(level, "%s: recorrido terminado — %s", label, report.summary())
