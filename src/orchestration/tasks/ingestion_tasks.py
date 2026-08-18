"""Tasks de ingesta: origen → raw.

Una task por unidad que tiene sentido reintentar y observar por separado — que acá
es una por recurso, porque cada recurso es un ETL independiente con su propio
pipeline de dlt. Son envoltorios delgados: NO tienen lógica de ingesta, solo la
política de ejecución (retries, tags, timing) y la llamada al `run_*_pipeline`.

Por qué el import del pipeline va DENTRO de la función: importar dlt y los
clientes al tope del módulo hace que Prefect pague ese costo al registrar los
deployments, y que un error de import en una fuente rompa el registro de todas.
"""

from __future__ import annotations

from prefect import task

from shared.utils.logging import LogTimer, get_logger


@task(
    name="ingest-currencies",
    description="Carga el catálogo de monedas de Frankfurter en raw.",
    retries=2,
    retry_delay_seconds=60,
    tags=["ingestion", "frankfurter"],
)
def ingest_currencies(full_refresh: bool = False) -> dict:
    """Ingesta del catálogo de monedas.

    Args:
        full_refresh: descarta la tabla y el estado antes de cargar. Casi nunca
                      hace falta: el recurso ya es `replace`.

    Sin parámetros de fecha a propósito: `/currencies` es una foto del presente.
    """
    logger = get_logger(__name__)

    with LogTimer(logger, "Ingesta Frankfurter/currencies"):
        from ingestion.pipelines.frankfurter.runner import run_currencies_pipeline

        summary = run_currencies_pipeline(full_refresh=full_refresh)

    return {"pipeline": "frankfurter_currencies", "status": "ok", **summary}


@task(
    name="ingest-exchange-rates",
    description="Carga las cotizaciones de Frankfurter en raw.",
    retries=2,
    retry_delay_seconds=60,
    tags=["ingestion", "frankfurter"],
)
def ingest_exchange_rates(
    date_from: str | None = None,
    date_to: str | None = None,
    full_refresh: bool = False,
    window_max: int | None = None,
    overlap: int | None = None,
) -> dict:
    """Ingesta de tipos de cambio.

    Args:
        date_from / date_to: backfill acotado (YYYY-MM-DD). Sin ellos, incremental
                             (histórico completo en la primera corrida).
        full_refresh:        descarta las tablas y el estado, y recarga el histórico.
        window_max:          ventana máxima inicial del troceado, en días.
        overlap:             días de re-pedido hacia atrás. None = default del entorno.

    Retries: 2 con 60s de espera. La API es pública y sin cuota declarada, pero un
    corte de red o un 5xx transitorio no debería costar la corrida entera. Los
    reintentos de request individuales ya los hace dlt: estos son de la task.
    """
    logger = get_logger(__name__)

    with LogTimer(logger, "Ingesta Frankfurter/rates"):
        from ingestion.pipelines.frankfurter.runner import run_rates_pipeline

        summary = run_rates_pipeline(
            date_from=date_from,
            date_to=date_to,
            full_refresh=full_refresh,
            window_max=window_max,
            overlap=overlap,
        )

    return {"pipeline": "frankfurter_rates", "status": "ok", **summary}
