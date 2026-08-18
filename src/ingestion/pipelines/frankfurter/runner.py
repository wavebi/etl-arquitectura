"""Ejecución de los pipelines de Frankfurter — el contrato que consume orquestación.

Un pipeline de dlt POR RECURSO, no uno por fuente. Cada uno tiene su estado, su
cursor y su tabla, así que son ETLs independientes: se programan distinto, fallan
por separado y uno se reprocesa sin tocar al otro.

    run_currencies_pipeline()
        Catálogo de monedas. `replace`: cada corrida reemplaza la foto anterior.
        No tiene eje temporal (ver `resources.currencies_source`).

    run_rates_pipeline()
        Cotizaciones, incremental. En la primera corrida (sin estado) trae el
        histórico completo desde `FRANKFURTER_HISTORY_START`; después, solo lo
        nuevo más la ventana de overlap.

    run_rates_pipeline(overlap=365)
        Igual, pero re-pidiendo un año hacia atrás. Es el ETL de reconciliación:
        mismo pipeline y mismo cursor, distinto cuánto se re-pide. Sirve para
        atrapar correcciones viejas que el overlap corto de la corrida diaria no
        alcanza.

    run_rates_pipeline(full_refresh=True)
        Fuerza la carga histórica: descarta las tablas del pipeline y su estado, y
        vuelve a empezar. Es lo que se usa cuando cambió la lógica de la ingesta o
        cuando raw quedó inconsistente.

    run_rates_pipeline(date_from="2010-01-01", date_to="2010-12-31")
        Backfill acotado y reproducible. No mueve el cursor de la carga
        incremental: se puede reprocesar un tramo viejo sin alterar el estado.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import dlt

from ingestion.pipelines.frankfurter.constants import (
    PIPELINE_CURRENCIES,
    PIPELINE_RATES,
    PIPELINE_WITNESS_TABLE,
    RAW_SCHEMA,
)
from ingestion.pipelines.frankfurter.resources import currencies_source, rates_source
from shared.utils.warehouse import get_connection, get_destination

if TYPE_CHECKING:
    from dlt.pipeline import Pipeline

logger = logging.getLogger(__name__)


def make_pipeline(pipeline_name: str) -> Pipeline:
    """Pipeline de dlt que escribe en raw.

    El estado (cursor incremental, schema) se guarda en el propio destino, así que
    sobrevive al reinicio del contenedor y es consultable con SQL.

    `schema.naming = "direct"` es lo que hace que raw sea RAW: por defecto dlt
    normaliza los nombres de columna (los pasa a snake_case y minúsculas), o sea que
    `FechaEmisión` llegaría a la base como `fecha_emision`. Con `direct` los nombres
    quedan exactamente como los devuelve el origen, y el renombre (y el pasaje al
    español) es responsabilidad —visible y versionada— de la capa de staging.

    Contrapartida asumida: los identificadores pueden necesitar comillas en SQL
    (`select "FechaEmisión" from raw...`), porque Postgres pliega a minúsculas todo
    lo que no esté citado. Es el precio de que raw sea auditable contra el origen.
    """
    # Se fija en código y no solo por entorno: si dependiera de una variable, un
    # `.env` sin ella haría que raw cambie de nombres sin que nadie lo note.
    dlt.config["schema.naming"] = "direct"

    return dlt.pipeline(
        pipeline_name=pipeline_name,
        destination=get_destination(),
        dataset_name=RAW_SCHEMA,
        # Progreso por log (no barra interactiva): en un worker no hay terminal.
        # `dump_system_stats=False` evita depender de psutil solo para eso.
        progress=dlt.progress.log(dump_system_stats=False),
    )


def destination_has_dlt_state() -> bool:
    """True si el destino ya tiene la metadata de dlt (`_dlt_version`).

    Sirve para distinguir dos situaciones que se parecen pero se resuelven distinto:

        - el pipeline ya corrió contra este destino y hay que RESETEARLO
          (`refresh="drop_resources"`, que borra tablas y estado);
        - el destino está virgen y solo hay que descartar el estado LOCAL, que puede
          haber sobrevivido en `DLT_DATA_DIR` a un borrado de la base.

    Pedir `refresh` sobre un destino virgen falla: dlt intenta limpiar `_dlt_version`
    y esa tabla todavía no existe.

    Ojo: `_dlt_version` es del SCHEMA, no de un pipeline. Si ya corrió cualquier
    pipeline contra `raw`, esto da True aunque el pipeline que pregunta sea nuevo.
    Es justo lo que se quiere: `drop_resources` borra solo los recursos del pipeline
    que lo pide, así que es seguro, y el caso "tabla vieja de otro pipeline" lo
    resuelve el propio `refresh`.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = '_dlt_version'
            """,
            (RAW_SCHEMA,),
        )
        return cur.fetchone() is not None


def raw_is_empty(table: str) -> bool:
    """True si la tabla de raw no existe o no tiene filas.

    Por qué hace falta preguntarlo: dlt guarda el estado del cursor incremental en
    DOS lugares —el destino y su directorio de trabajo local (`DLT_DATA_DIR`)— y el
    local puede sobrevivir a un borrado de la base (o viajar en la imagen). Si eso
    pasa, dlt cree que ya cargó el histórico, pide solo la ventana incremental y
    raw queda con una semana de datos y 27 años de agujero, sin ningún error.

    Verificado el 2026-08-18: tras recrear el volumen de Postgres, una corrida
    incremental arrancó en `max(fecha) - lag` en lugar del inicio del histórico.

    La base es la fuente de verdad: si no hay datos, hay que cargar el histórico.
    """
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
            """,
            (RAW_SCHEMA, table),
        )
        if cur.fetchone() is None:
            return True

        cur.execute(f'SELECT 1 FROM {RAW_SCHEMA}."{table}" LIMIT 1')  # noqa: S608
        return cur.fetchone() is None


def _resolve_refresh(pipeline: Pipeline, label: str) -> tuple[Pipeline, str | None]:
    """Traduce "hay que empezar de cero" al modo de reset que corresponde.

    Devuelve el pipeline (puede haber sido reemplazado por `drop()`) y el valor de
    `refresh` para `pipeline.run()`.
    """
    if destination_has_dlt_state():
        # El pipeline ya corrió contra este destino: se borran sus tablas y su
        # estado incremental, sin tocar otros pipelines del warehouse.
        logger.warning("%s: se descartan las tablas y el estado del pipeline.", label)
        return pipeline, "drop_resources"

    # Destino virgen: no hay nada que borrar allá, pero el estado LOCAL puede haber
    # sobrevivido (p. ej. se recreó la base y quedó el DLT_DATA_DIR). Pedir
    # `refresh` acá falla con: relation "raw._dlt_version" does not exist.
    logger.warning("%s: destino sin metadata de dlt — se limpia el estado local.", label)
    return pipeline.drop(), None


def _run(pipeline: Pipeline, source: Any, label: str, *, refresh: str | None) -> Any:
    """Corre el pipeline y verifica que la carga realmente haya andado.

    Raises:
        RuntimeError: si dlt reporta jobs de carga fallidos. dlt NO levanta
        excepción por sí solo cuando un resource falla: sin este chequeo, una
        carga parcial pasaría como exitosa y el flow quedaría verde con raw
        incompleto.
    """
    load_info = pipeline.run(
        source,
        refresh=refresh,
        # El schema puede evolucionar solo: si la API agrega un campo, entra a
        # raw y se decide en dbt si se usa.
        schema_contract={"data_type": "evolve", "columns": "evolve"},
    )

    if load_info is None:
        raise RuntimeError(f"{label}: dlt.run() devolvió None (la carga abortó antes de empezar).")
    if load_info.has_failed_jobs:
        raise RuntimeError(f"{label}: hay jobs de dlt fallidos — {load_info}")

    return load_info


def run_currencies_pipeline(
    *,
    full_refresh: bool = False,
    base_currency: str | None = None,
) -> dict[str, Any]:
    """Carga el catálogo de monedas en raw.

    Args:
        full_refresh:  descarta la tabla y el estado antes de cargar. Casi nunca
                       hace falta: el recurso ya es `replace`, así que cada corrida
                       reemplaza la foto anterior. Sirve cuando cambió el schema.
        base_currency: moneda base. Default: la del entorno.

    No tiene parámetros de fecha ni de overlap a propósito: `/currencies` es una
    foto del presente e ignora cualquier fecha que se le pase.
    """
    label = "Frankfurter/currencies"
    pipeline = make_pipeline(PIPELINE_CURRENCIES)

    refresh = None
    if full_refresh:
        pipeline, refresh = _resolve_refresh(pipeline, label)

    load_info = _run(pipeline, currencies_source(base_currency=base_currency), label, refresh=refresh)

    summary = _summarize(PIPELINE_CURRENCIES, pipeline, load_info)
    logger.info("%s: carga OK — %s", label, summary)
    return summary


def run_rates_pipeline(
    date_from: str | None = None,
    date_to: str | None = None,
    *,
    full_refresh: bool = False,
    base_currency: str | None = None,
    window_max: int | None = None,
    overlap: int | None = None,
) -> dict[str, Any]:
    """Carga las cotizaciones en raw.

    Args:
        date_from / date_to: backfill acotado (YYYY-MM-DD). Sin ellos, incremental.
        full_refresh:        descarta las tablas y el estado, y recarga el histórico.
        base_currency:       moneda base. Default: la del entorno.
        window_max:          ventana máxima inicial del troceado, en días.
        overlap:             días de re-pedido hacia atrás. `None` = el default del
                             entorno (`INGEST_OVERLAP_DAYS`). El ETL de
                             reconciliación pasa acá `INGEST_RECONCILE_OVERLAP_DAYS`.
                             Se ignora en un backfill acotado, que pide el rango exacto.

    Returns:
        Resumen de la carga: filas por tabla y load_ids.
    """
    label = "Frankfurter/rates"
    pipeline = make_pipeline(PIPELINE_RATES)
    source = rates_source(
        date_from=date_from,
        date_to=date_to,
        base_currency=base_currency,
        window_max=window_max,
        overlap=overlap,
    )

    # Carga histórica automática cuando raw está vacío: el estado de dlt no alcanza
    # como fuente de verdad (ver `raw_is_empty`). Un backfill acotado no se toca: si
    # alguien pidió un rango explícito, se respeta.
    if not full_refresh and date_from is None and raw_is_empty(PIPELINE_WITNESS_TABLE[PIPELINE_RATES]):
        logger.warning(
            "%s: raw está vacío ⇒ se fuerza la carga histórica "
            "(se descarta el estado de dlt, que podría estar desincronizado).",
            label,
        )
        full_refresh = True

    refresh = None
    if full_refresh:
        pipeline, refresh = _resolve_refresh(pipeline, label)

    load_info = _run(pipeline, source, label, refresh=refresh)

    summary = _summarize(PIPELINE_RATES, pipeline, load_info)
    logger.info("%s: carga OK — %s", label, summary)
    return summary


def _summarize(pipeline_name: str, pipeline: Pipeline, load_info: Any) -> dict[str, Any]:
    """Filas cargadas por tabla y load_ids, para el log y Telegram."""
    row_counts: dict[str, int] = {}
    try:
        # `row_counts` viene del último trace de extracción; si no está, no se
        # rompe el resumen por eso.
        row_counts = dict(pipeline.last_trace.last_normalize_info.row_counts)
    except Exception:  # pragma: no cover — el trace es informativo, no crítico
        logger.debug("No se pudo leer row_counts del trace de dlt.")

    return {
        "pipeline": pipeline_name,
        "filas_por_tabla": {k: v for k, v in row_counts.items() if not k.startswith("_dlt")},
        "load_ids": list(getattr(load_info, "loads_ids", []) or []),
    }
