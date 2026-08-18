"""
Bridge de logging enterprise — enruta TODOS los loggers de Python a la UI de Prefect.

Arquitectura:
    stdlib logging root  ──┐
    loguru                 ├──► PrefectInterceptHandler ──► UI de Prefect + run logs
    sqlalchemy / psycopg2  ┘
    dbt / dlt              ─── silenciados por debajo de WARNING (salvo DEBUG=True)

Uso dentro de un flow o task:
    from shared.utils.logging import get_logger
    logger = get_logger(__name__)
    logger.info("hello")

Uso a nivel de módulo o en scripts (fuera de un flow):
    Misma API — cae automáticamente a stdlib + el formatter de loguru.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import TYPE_CHECKING

from loguru import logger as loguru_logger

# Imports de Prefect cacheados a nivel de módulo — evita el overhead de importar en cada emit.
try:
    from prefect import get_run_logger as _prefect_get_run_logger
    from prefect.exceptions import MissingContextError as _MissingContextError

    _PREFECT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PREFECT_AVAILABLE = False
    _MissingContextError = Exception  # type: ignore[misc,assignment]

# Guarda de reentrancia thread-local — previene loops recursivos de logging.
# Cuando nuestro handler llama a prefect_logger.info(), el propio APILogHandler de
# Prefect usa httpx/asyncio por debajo; esos emiten records de stdlib que volverían
# a entrar a este handler → recursión infinita → tormenta de '--- Logging error ---'.
_tls = threading.local()

if TYPE_CHECKING:
    import loguru
    from prefect.logging.loggers import PrefectLogAdapter

# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

# Estos loggers son útiles de ver en niveles más bajos al debuggear código de la app.
_NOISY_LOGGERS: dict[str, int] = {
    "sqlalchemy.engine": logging.WARNING,
    "sqlalchemy.pool": logging.WARNING,
    "sqlalchemy.dialects": logging.WARNING,
    "psycopg2": logging.WARNING,
    "dbt": logging.WARNING,
    "dlt": logging.WARNING,
    "dlt.sources": logging.WARNING,
    "dlt.pipeline": logging.WARNING,  # INFO inunda la UI en ETLs reales; usar DEBUG=True cuando haga falta
    "dlt.load": logging.WARNING,
}

# Loggers de red/infraestructura — SIEMPRE silenciados en WARNING sin importar
# el flag DEBUG. Son llamadas internas a la API de Prefect y no aportan valor.
_INFRA_LOGGERS: dict[str, int] = {
    "httpcore": logging.WARNING,
    "httpx": logging.WARNING,
    "urllib3": logging.WARNING,
    "asyncio": logging.WARNING,
    "concurrent.futures": logging.WARNING,
}

_STDLIB_TO_LOGURU_LEVEL: dict[int, str] = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
}


# ---------------------------------------------------------------------------
# Supresiones de warnings documentadas
# ---------------------------------------------------------------------------


class _DltLowResolutionCursorFilter(logging.Filter):
    """
    Suprime el warning de dlt "Large number of records sharing the same value of
    cursor field".

    Por qué estamos explícitamente de acuerdo con ignorar esta señal (leer antes de quitar):

    - Cada tabla raw se declara con `@dlt.resource(primary_key="_row_id")`,
      donde `_row_id = sha256(business_key)` es único por registro. Por lo tanto, el
      UPSERT del merge deduplica correctamente sin importar la resolución del cursor.

    - También pasamos `primary_key=("_row_id",)` a `dlt.sources.incremental`, así
      el estado de dedup por valor de cursor guarda _row_ids (strings cortos) en
      lugar de hashes del payload completo. El warning es sobre la CANTIDAD de
      records con el mismo valor de cursor, no sobre el TAMAÑO del estado — pero el
      estado se mantiene manejable gracias a esta configuración.

    - Es habitual que el origen exponga solo una columna DATE como cursor (sin hora).
      Días con cientos o miles de registros son normales en un libro contable, y no
      hay una columna de mayor resolución a la que cambiar sin mapear endpoint por
      endpoint.

    IMPORTANTE: si alguna vez se quita el UPSERT por `_row_id` de raw, QUITAR este
    filtro — el warning pasaría a señalar un riesgo real de pérdida de registros
    entre runs.
    """

    _PATTERN = "Large number of records"
    _CURSOR_HINT = "sharing the same value of cursor field"

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        # Descarta el record (return False) solo si ambas frases están presentes.
        return not (self._PATTERN in message and self._CURSOR_HINT in message)


# ---------------------------------------------------------------------------
# Handler: stdlib → UI de Prefect
# ---------------------------------------------------------------------------


class PrefectInterceptHandler(logging.Handler):
    """
    Handler de logging que reenvía los records de stdlib al run logger activo de
    Prefect para que cada mensaje aparezca en la UI de Prefect.

    Cae a loguru (stderr) cuando se lo llama fuera de un contexto de flow/task, así
    los scripts y tests siguen produciendo salida legible.
    """

    # Los namespaces de loggers internos de Prefect ya tienen su propio APILogHandler.
    # Interceptarlos causa recursión; dejamos que Prefect los maneje de forma nativa.
    _SKIP_PREFIXES = ("prefect.", "prefect", "asyncio", "concurrent.futures")

    def emit(self, record: logging.LogRecord) -> None:
        # ── Guarda de reentrancia ─────────────────────────────────────────
        # Si ya estamos dentro de emit() en este thread, salimos de inmediato.
        # Esto corta cualquier loop recursivo antes de que se desborde el stack.
        if getattr(_tls, "in_emit", False):
            return

        # ── Saltar los loggers internos de Prefect ────────────────────────
        # Los maneja el APILogHandler de Prefect; no debemos tocarlos.
        if record.name.startswith(self._SKIP_PREFIXES):
            return

        level: str = _STDLIB_TO_LOGURU_LEVEL.get(record.levelno, "INFO")
        # Usa el mensaje crudo (args ya interpolados) — sin prefijo de formato a
        # nivel de handler. El propio formatter de la UI de Prefect maneja la
        # presentación. Evita el doble prefijo tipo: "etl — etl — My message"
        message = record.getMessage()

        _tls.in_emit = True
        try:
            if _PREFECT_AVAILABLE:
                try:
                    prefect_logger = _prefect_get_run_logger()
                    log_fn = getattr(prefect_logger, level.lower(), prefect_logger.info)
                    log_fn(message)
                except _MissingContextError:
                    # Fuera de un flow run — escribe directo al stderr original real
                    # (sys.__stderr__ evita cualquier redirección de logging).
                    sys.__stderr__.write(f"{record.levelname:<8} | {record.name} — {message}\n")

        except Exception as exc:  # pragma: no cover
            # Último recurso: escribir al stderr a nivel de SO para que el error
            # nunca se trague en silencio. Nunca llamar a self.handleError() — vuelve
            # a entrar a la maquinaria de logging y causa otro loop.
            sys.__stderr__.write(f"[PrefectInterceptHandler] Failed to forward log record: {exc}\n")
        finally:
            _tls.in_emit = False


# ---------------------------------------------------------------------------
# Loguru → Prefect sink
# ---------------------------------------------------------------------------


def _loguru_prefect_sink(message: loguru.Message) -> None:  # type: ignore[name-defined]
    """Sink de loguru que reenvía al run logger activo de Prefect."""
    # Misma guarda de reentrancia: loguru → prefect_logger.info() → logs de httpx →
    # logging de stdlib → nuestro PrefectInterceptHandler → loguru otra vez → loop.
    if getattr(_tls, "in_emit", False):
        return

    record = message.record
    level: str = record["level"].name  # ej. "INFO"

    _tls.in_emit = True
    try:
        if _PREFECT_AVAILABLE:
            try:
                prefect_logger = _prefect_get_run_logger()
                log_fn = getattr(prefect_logger, level.lower(), prefect_logger.info)
                log_fn(record["message"])
            except _MissingContextError:
                pass  # loguru ya imprimió a stderr vía el sink por defecto

    except Exception as exc:  # pragma: no cover
        sys.__stderr__.write(f"[loguru→prefect sink] Failed: {exc}\n")
    finally:
        _tls.in_emit = False


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def configure_prefect_logging(level: str = "INFO", debug: bool = False) -> None:
    """
    Conecta todos los loggers de Python para que reenvíen sus records a la UI de Prefect.

    Llamar a esto como PRIMERA instrucción dentro de cada función `@flow`:

        @flow(name="my-flow")
        def my_flow():
            configure_prefect_logging(settings.LOG_LEVEL, settings.DEBUG)
            ...

    Args:
        level:  String del nivel de log raíz (ej. "INFO", "DEBUG", "WARNING").
        debug:  Cuando es True, los loggers ruidosos de terceros también se ponen en DEBUG.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    # Nombre canónico derivado del nivel numérico ya validado. Si `level` era
    # inválido, numeric_level cayó a INFO → level_name == "INFO". Lo usamos para
    # loguru (que sí valida y tiraría ValueError ante un string desconocido),
    # manteniendo consistencia con el path de stdlib.
    level_name = logging.getLevelName(numeric_level)

    # ── 1. Logger raíz ────────────────────────────────────────────────────
    handler = PrefectInterceptHandler()
    handler.setFormatter(logging.Formatter("%(name)s — %(message)s"))
    handler.setLevel(numeric_level)

    root = logging.getLogger()
    # Quitar solo los PrefectInterceptHandler obsoletos de llamadas previas a configure().
    # Dejar intactos los handlers de terceros (Sentry, New Relic, etc.).
    root.handlers = [h for h in root.handlers if not isinstance(h, PrefectInterceptHandler)]
    root.addHandler(handler)
    root.setLevel(numeric_level)

    # ── 2. Loggers ruidosos de terceros (respetan el flag DEBUG) ─────────
    third_party_level = numeric_level if debug else logging.WARNING
    dlt_filter = _DltLowResolutionCursorFilter()
    for name, default_level in _NOISY_LOGGERS.items():
        lg = logging.getLogger(name)
        lg.setLevel(min(default_level, third_party_level) if debug else default_level)
        if not any(isinstance(h, PrefectInterceptHandler) for h in lg.handlers):
            lg.addHandler(handler)
        lg.propagate = False
        # Adjuntar el supresor de warnings documentado de dlt a todos los loggers
        # del namespace dlt exactamente una vez. Ver el docstring de
        # _DltLowResolutionCursorFilter para la justificación completa de por qué es seguro.
        if name.startswith("dlt") and not any(isinstance(f, _DltLowResolutionCursorFilter) for f in lg.filters):
            lg.addFilter(dlt_filter)

    # ── 3. Loggers de infraestructura/red (SIEMPRE WARNING — nunca debug) ─
    for name, fixed_level in _INFRA_LOGGERS.items():
        lg = logging.getLogger(name)
        lg.setLevel(fixed_level)
        if not any(isinstance(h, PrefectInterceptHandler) for h in lg.handlers):
            lg.addHandler(handler)
        lg.propagate = False

    # ── 3. Bridge Loguru → Prefect ────────────────────────────────────────
    # Quitar el sink stderr por defecto de loguru para que no duplique la salida
    loguru_logger.remove()
    # Agregar nuestro sink de Prefect
    loguru_logger.add(
        _loguru_prefect_sink,
        level=level_name,
        format="{name} — {message}",
        backtrace=True,
        diagnose=False,  # no exponer variables locales en prod
    )
    # Mantener un fallback a stderr en WARNING+ para que los scripts siempre vean errores críticos
    loguru_logger.add(
        sys.stderr,
        level="WARNING",
        format="<yellow>{time:HH:mm:ss}</yellow> | <level>{level:<8}</level> | <cyan>{name}</cyan> — {message}",
        colorize=True,
    )


def get_logger(name: str = "etl") -> logging.Logger | PrefectLogAdapter:
    """
    Retorna el logger apropiado para el contexto de ejecución actual.

    - Dentro de un flow/task de Prefect → retorna `get_run_logger()` (los logs van a la UI)
    - Fuera de un flow (scripts, tests, CLI) → retorna un logger de stdlib con nombre
      que escribe a stderr vía el formatter de loguru

    Args:
        name: Nombre del logger (usar `__name__` para loggers a nivel de módulo).

    Returns:
        Una instancia de logger sobre la que es seguro llamar .info/.warning/.error/.exception.
    """
    try:
        from prefect import get_run_logger
        from prefect.exceptions import MissingContextError

        try:
            return get_run_logger()
        except MissingContextError:
            pass

    except ImportError:  # pragma: no cover — prefect no instalado
        pass

    # Fallback: logger de stdlib (loguru lo formatea si se llamó a configure_logging)
    fallback = logging.getLogger(name)
    if not fallback.handlers:
        _configure_fallback_logger(fallback)
    return fallback


def _configure_fallback_logger(logger: logging.Logger) -> None:
    """Configura un logger stderr mínimo para uso fuera del contexto de flow."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s — %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False


# ---------------------------------------------------------------------------
# Context manager de timing (utilidad extra para logs de performance estructurados)
# ---------------------------------------------------------------------------


class LogTimer:
    """
    Context manager que loguea el tiempo transcurrido al salir.

    Uso:
        with LogTimer(logger, "DB query"):
            cur.execute(heavy_query)
        # → loguea: "DB query completed in 0.123 s"
    """

    def __init__(self, logger: logging.Logger, label: str) -> None:
        self._logger = logger
        self._label = label
        self._start: float = 0.0

    def __enter__(self) -> LogTimer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        elapsed = time.perf_counter() - self._start
        if exc_type is None:
            self._logger.info(f"{self._label} completed in {elapsed:.3f}s")
        else:
            self._logger.error(f"{self._label} failed after {elapsed:.3f}s — {exc_type.__name__}: {exc_val}")
        return False  # nunca suprimir excepciones
