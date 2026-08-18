"""
Decorator de flow enterprise — estandariza logging, timing y manejo de errores
en todos los flows de la empresa para que los desarrolladores de ETL escriban solo
lógica de negocio.

Uso:
    from shared.utils.orchestration import enterprise_flow, finalize_flow
    from shared.utils.logging import get_logger
    from prefect import task

    @task(name="my-task")
    def extract():
        logger = get_logger(__name__)
        logger.info("Extracting...")
        return [1, 2, 3]

    @enterprise_flow(name="my-etl", description="Does the thing.")
    def my_flow():
        data = extract()
        ...
"""

from __future__ import annotations

import time
from functools import wraps
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

import prefect
from prefect import flow

from shared.settings import settings
from shared.utils.logging import configure_prefect_logging, get_logger


def enterprise_flow(
    name: str | None = None,
    description: str | None = None,
    **flow_kwargs: Any,
) -> Callable:
    """
    Decorator que convierte una función plana en un flow de Prefect estandarizado.

    Maneja automáticamente:
    - Setup del bridge de logging (configure_prefect_logging)
    - Log de inicio rico con contexto de env / app / log_level / versión de prefect
    - Medición del tiempo transcurrido y log de finalización
    - Logging uniforme de excepciones antes de re-lanzar

    Args:
        name:        Nombre del flow de Prefect. Por defecto el nombre de la función.
        description: Descripción del flow mostrada en la UI de Prefect.
        **flow_kwargs: Cualquier kwarg adicional reenviado a @flow()
                       (ej. retries, timeout_seconds, version).
    """

    def decorator(fn: Callable) -> Callable:
        @flow(name=name or fn.__name__, description=description, **flow_kwargs)
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # ── 1. Arrancar el bridge de logging ──────────────────────────
            configure_prefect_logging(
                level=settings.LOG_LEVEL,
                debug=settings.DEBUG,
            )
            logger = get_logger(fn.__name__)

            # ── 2. Log de inicio rico ──────────────────────────────────────
            logger.info(
                "🚀 %s started — env=%s app=%s log_level=%s prefect=%s",
                fn.__name__,
                settings.ENV,
                settings.APP_NAME,
                settings.LOG_LEVEL,
                prefect.__version__,
            )

            start = time.perf_counter()

            # ── 3. Ejecutar la lógica real del flow ───────────────────────
            # Las notificaciones (success/failure) las despachan los hooks de
            # Prefect `on_completion`/`on_failure` aplicados al @enterprise_flow
            # (ver shared/services/telegram.py). El decorator solo loguea +
            # re-raise para mantener la responsabilidad única.
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                elapsed = time.perf_counter() - start
                logger.error(
                    "❌ %s failed after %.3fs — %s: %s",
                    fn.__name__,
                    elapsed,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )
                raise

            # ── 4. Log de finalización ────────────────────────────────────
            elapsed = time.perf_counter() - start
            logger.info("✅ %s completed in %.3fs", fn.__name__, elapsed)
            return result

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# finalize_flow — política compartida de severidad grave/leve + Telegram
# ---------------------------------------------------------------------------


def finalize_flow(
    flow_name: str,
    results: dict,
    failed: list[str],
    grave_steps: Iterable[str],
) -> dict:
    """
    Construye el resultado final de un flow aplicando política grave/leve.

    Reglas:
        - Si algún step en `failed` está en `grave_steps` → levanta RuntimeError
          (Prefect marca el flow Failed; el hook `on_failure` envía la notif).
        - Si hay steps fallidos pero ninguno grave → retorna status="degraded"
          (Prefect marca el flow Completed; el hook `on_completion` ve el dict
          y manda notif warning).
        - Si no hay fallas → retorna status="ok" (notif info por hook).

    Las notificaciones NO se disparan acá: las despachan los hooks de Prefect
    (`shared/services/telegram.py`) aplicados al `@enterprise_flow`.

    Args:
        flow_name:   Nombre legible del flow (para el RuntimeError).
        results:     Dict con los resultados de cada paso (lo que retornó cada task).
        failed:      Lista de steps que fallaron.
        grave_steps: Steps cuya falla es crítica (rompen el flow).

    Returns:
        Dict con status/failed_steps/results cuando NO hay falla grave.

    Raises:
        RuntimeError: cuando hay al menos un step grave en `failed`.
    """
    grave = [s for s in failed if s in set(grave_steps)]
    leve = [s for s in failed if s not in set(grave_steps)]

    if grave:
        raise RuntimeError(f"{flow_name} falló en pasos críticos: {grave} (también fallaron: {leve or 'ninguno'})")

    return {
        "status": "ok" if not failed else "degraded",
        "failed_steps": failed,
        "results": results,
    }
