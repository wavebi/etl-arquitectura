"""Recursos de dlt de la fuente Frankfurter.

Dos recursos con estrategias distintas, que son los dos casos que aparecen en
cualquier ETL:

    currencies       foto del presente ⇒ `replace`. La API expone las monedas que
                     publica HOY; el histórico de altas y bajas lo arma un snapshot
                     de dbt (SCD Type 2), no la ingesta.

    exchange_rates   serie temporal ⇒ `merge` por clave natural + cursor incremental
                     con overlap. Primera corrida = histórico completo; corridas
                     siguientes = solo lo nuevo más la ventana de overlap.

## raw significa raw: los nombres son los del origen

Los nombres de columna son EXACTAMENTE los del origen (`date`, `base`, `currency`,
`rate`, `amount`), y dlt tiene desactivada su normalización de nombres (ver
`runner.make_pipeline`). Si mañana la API devuelve `FechaEmisión`, en raw hay una
columna `FechaEmisión`. El renombre —y el pasaje al español— es trabajo de la capa
de staging, donde queda versionado y visible en un diff.

Lo único que se agrega son las dos columnas de metadata (`_ingested_at`, `_source`).

La respuesta anidada (`{"rates": {fecha: {moneda: valor}}}`) sí se aplana a formato
largo. No es un renombre: es evitar un schema que mute. El conjunto de monedas
cambia a lo largo de los 27 años (aparecen y desaparecen la dracma, el tolar, la
kuna), así que una columna por moneda haría que raw cambie de forma cada vez y se
llene de nulos.

## El incremental es de dlt, no nuestro

`dlt.sources.incremental` aporta tres cosas: persiste el cursor en el destino, `lag`
corre el inicio de la ventana hacia atrás para capturar correcciones del origen, y
`range_start="closed"` + `primary_key` deduplican las filas repetidas que trae ese
overlap. Verificado contra dlt 1.30 en tests/integration/test_incremental_lag.py.

Lo que dlt no puede saber es cómo pedirle ese rango a ESTA API: eso sale de
`incremental.start_value` / `end_value`, que el recurso lee para construir las
llamadas y trocearlas con el control adaptativo.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import dlt

from ingestion.metadata import METADATA_COLUMN_HINTS, add_metadata
from ingestion.pipelines.frankfurter.chunking import WindowPolicy, WindowReport, fetch_adaptive
from ingestion.pipelines.frankfurter.constants import (
    CURSOR_COLUMN,
    RATES_PRIMARY_KEY,
    TABLE_CURRENCIES,
    TABLE_RATES,
    history_start,
    overlap_days,
    window_max_days,
)
from ingestion.sources.frankfurter.client import FrankfurterClient

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Hints de las columnas de negocio. Raw es permisivo con lo que no está acá, pero el
# tipo de estas tres importa: `date` como date real (no texto) para que el cursor
# compare cronológicamente, y `rate` como decimal para no perder precisión en
# monedas con valores grandes (IDR ~20.000, la lira turca vieja ~1.900.000).
_RATES_COLUMNS: dict[str, dict[str, Any]] = {
    "date": {"data_type": "date", "nullable": False},
    "base": {"data_type": "text", "nullable": False},
    "currency": {"data_type": "text", "nullable": False},
    "rate": {"data_type": "decimal", "precision": 20, "scale": 8, "nullable": False},
    "amount": {"data_type": "decimal", "precision": 20, "scale": 8, "nullable": True},
    **METADATA_COLUMN_HINTS,
}

_CURRENCIES_COLUMNS: dict[str, dict[str, Any]] = {
    "code": {"data_type": "text", "nullable": False},
    "name": {"data_type": "text", "nullable": False},
    **METADATA_COLUMN_HINTS,
}


@dlt.resource(
    name=TABLE_CURRENCIES,
    write_disposition="replace",
    primary_key="code",
    columns=_CURRENCIES_COLUMNS,
)
def currencies(client: FrankfurterClient) -> Iterator[dict[str, Any]]:
    """Catálogo de monedas que la API publica hoy."""
    catalog = client.get_currencies()
    logger.info("Frankfurter: %s monedas en el catálogo actual.", len(catalog))
    for code, name in sorted(catalog.items()):
        yield {"code": code, "name": name}


@dlt.resource(
    name=TABLE_RATES,
    write_disposition="merge",
    primary_key=RATES_PRIMARY_KEY,
    columns=_RATES_COLUMNS,
)
def exchange_rates(
    client: FrankfurterClient,
    policy: WindowPolicy,
    report: WindowReport,
    end_date: date | None = None,
    cursor: dlt.sources.incremental[str] = dlt.sources.incremental(
        CURSOR_COLUMN,
        initial_value=None,  # lo setea el source: history_start() o el backfill pedido
        lag=None,  # ídem: overlap_days() salvo en un backfill acotado
        range_start="closed",
        primary_key=RATES_PRIMARY_KEY,
    ),
) -> Iterator[dict[str, Any]]:
    """Cotizaciones diarias, en formato largo: una fila por día y moneda."""
    # `start_value` ya tiene el `lag` aplicado: es el inicio real de la ventana.
    window_start = _as_date(cursor.start_value) or history_start()
    window_end = end_date or _as_date(cursor.end_value) or date.today()

    if window_start > window_end:
        logger.info("Frankfurter: nada que pedir (%s > %s).", window_start, window_end)
        return

    logger.info(
        "Frankfurter: ventana %s → %s (%s días) con troceado adaptativo de hasta %s días.",
        window_start,
        window_end,
        (window_end - window_start).days + 1,
        policy.max_days,
    )

    for chunk in fetch_adaptive(
        client.get_rates,
        window_start,
        window_end,
        policy,
        label=TABLE_RATES,
        report=report,
    ):
        yield from _flatten(chunk, client.base_currency)


def _flatten(payload: dict[str, Any], base_currency: str) -> Iterator[dict[str, Any]]:
    """`{fecha: {moneda: valor}}` → una fila por (fecha, base, moneda).

    Los nombres de las claves son los del origen: `date` y `base` son campos suyos,
    y `currency`/`rate` son las dos mitades del mapa que la API llama `rates`.
    """
    amount = payload.get("amount", 1.0)
    for rate_date, quotes in payload["rates"].items():
        for currency, rate in quotes.items():
            yield {
                "date": rate_date,
                "base": base_currency,
                "currency": currency,
                "rate": rate,
                "amount": amount,
            }


def _as_date(value: Any) -> date | None:
    """Normaliza a `date` lo que dlt guarde en el estado (str o date)."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


@dlt.source(name="frankfurter_currencies")
def currencies_source(base_currency: str | None = None) -> Any:
    """Fuente del catálogo de monedas. Un solo recurso, sin eje temporal.

    Es una source de un solo recurso a propósito, y no un recurso suelto colgado de
    la source de cotizaciones: cada recurso es un ETL independiente, con su propio
    pipeline de dlt, su propio estado y su propio schedule.

    Por qué acá NO hay `date_from`, `date_to` ni overlap (verificado contra la API
    el 2026-08-18): `/currencies` devuelve una foto del presente e IGNORA cualquier
    parámetro de fecha — el payload de `/currencies?date=1999-01-04` es idéntico
    byte a byte al de `/currencies`. No hay histórico que reprocesar ni corrección
    que atrapar hacia atrás, así que un ETL de reconciliación sobre este endpoint
    sería el mismo request otra vez.

    Las monedas que el BCE ya no publica (la dracma, el tolar, la lira turca vieja)
    no se recuperan de acá sino de las cotizaciones, y la dimensión las reconcilia
    con la unión de ambas. Ver la rareza 3 de `docs/fuentes/frankfurter.md`.
    """
    client = FrankfurterClient(base_currency=base_currency)
    return currencies(client=client).add_map(add_metadata(f"frankfurter.{TABLE_CURRENCIES}"))


@dlt.source(name="frankfurter_rates")
def rates_source(
    date_from: str | None = None,
    date_to: str | None = None,
    base_currency: str | None = None,
    window_max: int | None = None,
    overlap: int | None = None,
) -> Any:
    """Fuente de las cotizaciones: serie temporal con cursor incremental.

    Args:
        date_from: inicio explícito (YYYY-MM-DD). Fuerza un rango acotado y desactiva
                   el estado incremental (backfill reproducible).
        date_to:   fin explícito. Con `date_from`, delimita el backfill.
        base_currency: moneda base de las cotizaciones. Default: la del entorno.
        window_max: ventana máxima inicial del troceado, en días.
        overlap:   días de `lag` hacia atrás. `None` = el default del entorno
                   (`INGEST_OVERLAP_DAYS`). Es lo que distingue a la corrida diaria
                   de la de reconciliación: mismo código, mismo cursor, distinto
                   cuánto se re-pide.

    Sin argumentos: primera corrida = histórico completo desde
    `FRANKFURTER_HISTORY_START`; corridas siguientes = incremental con overlap.
    """
    client = FrankfurterClient(base_currency=base_currency)
    policy = WindowPolicy(max_days=window_max or window_max_days())
    report = WindowReport()

    is_backfill = date_from is not None
    cursor = dlt.sources.incremental(
        CURSOR_COLUMN,
        initial_value=date_from or history_start().isoformat(),
        # En un backfill acotado no se aplica overlap: se pide exactamente lo pedido.
        # `overlap` puede ser 0 (pedir solo lo nuevo), así que se compara contra None.
        lag=None if is_backfill else (overlap if overlap is not None else overlap_days()),
        # `end_value` hace que el filtrado sea stateless: el backfill no mueve el
        # cursor de la carga incremental normal.
        end_value=date_to if is_backfill else None,
        range_start="closed",
        primary_key=RATES_PRIMARY_KEY,
    )

    return exchange_rates(
        client=client,
        policy=policy,
        report=report,
        end_date=date.fromisoformat(date_to) if date_to else None,
        cursor=cursor,
    ).add_map(add_metadata(f"frankfurter.{TABLE_RATES}"))


def yesterday() -> date:
    """Último día con publicación posible. Útil para acotar backfills."""
    return date.today() - timedelta(days=1)
