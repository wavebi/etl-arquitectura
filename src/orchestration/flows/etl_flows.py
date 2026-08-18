"""Flows de ETL: un ETL independiente por recurso del origen.

## Por qué un flow por recurso y no uno solo que traiga todo

Cada recurso tiene su propio pipeline de dlt, su propio estado y su propia tabla.
Separarlos en flows distintos hace que se programen distinto, que fallen por
separado (si la API rompe el catálogo, las cotizaciones siguen entrando) y que uno
se reprocese sin tocar el estado del otro.

## Los tres ETLs

    frankfurter-currencies      catálogo de monedas. `replace`, sin eje temporal:
                                `/currencies` es una foto del presente e ignora
                                cualquier fecha (verificado 2026-08-18).

    frankfurter-rates           cotizaciones, incremental con overlap corto
                                (`INGEST_OVERLAP_DAYS`, 7 días). Es la corrida de
                                todos los días.

    frankfurter-rates-reconcile mismas cotizaciones, mismo cursor, overlap largo
                                (`INGEST_RECONCILE_OVERLAP_DAYS`, 365 días). Atrapa
                                las correcciones viejas que el overlap corto no
                                alcanza. Ver `constants.reconcile_overlap_days`.

No hay un cuarto ETL de "reconciliación del catálogo" porque no puede haberlo:
pedirle a `/currencies` un año hacia atrás devuelve exactamente el mismo payload
que pedirle hoy. Las monedas que ya no se publican se recuperan de las
cotizaciones, no del catálogo (rareza 3 de `docs/fuentes/frankfurter.md`).

## Lo que los tres comparten

    1. Cada paso se ejecuta en su propio `try/except` y se acumula en `failed`.
       Así una falla en la transformación no borra lo que sí se ingestó, y el
       reporte dice exactamente qué se rompió.

    2. `finalize_flow` aplica la política grave/leve al final:
         - falló un paso GRAVE  → RuntimeError ⇒ Prefect rojo + Telegram urgente.
         - solo fallaron leves  → status "degraded" ⇒ Prefect verde + warning.
         - nada falló           → status "ok" ⇒ notificación informativa.
       La notificación NO se manda desde acá: la despachan los hooks
       `on_completion` / `on_failure` (shared/services/telegram.py).

    3. Cada ETL refresca SU subgrafo de dbt, no todo el proyecto. `+modelo+` = todos
       los upstream y downstream de ese modelo. Los subgrafos se solapan (la
       dimensión de monedas se alimenta de los dos recursos) y está bien: `dbt build`
       es idempotente y el `concurrency("dbt-lock")` de `run_dbt_command` serializa
       las corridas que se pisen.

    4. Si raw está vacío ⇒ carga histórica automática, sin que nadie la pida. Lo
       decide el runner consultando la BASE, no el estado local de dlt.

    5. Todos aceptan `full_refresh` y los de cotizaciones aceptan además un rango
       explícito (`date_from` / `date_to`), que reprocesa sin mover el cursor.
"""

from __future__ import annotations

from ingestion.pipelines.frankfurter.constants import reconcile_overlap_days
from orchestration.tasks.ingestion_tasks import ingest_currencies, ingest_exchange_rates
from orchestration.tasks.transformation_tasks import dbt_build, dbt_docs_generate
from shared.services.telegram import notify_flow_failure, notify_flow_success
from shared.utils.logging import get_logger
from shared.utils.orchestration import enterprise_flow, finalize_flow

# ---------------------------------------------------------------------------
# Política de severidad
# ---------------------------------------------------------------------------
# Grave = sin esto los marts quedan mal o incompletos y hay que avisar ya.
# Leve  = los marts existentes siguen sirviendo; alcanza un warning.
#   - ingest y dbt_build graves: sin ellos los marts no existen o quedan viejos.
#     dbt_build incluye los tests con `severity: error`, que son los que no se
#     pueden dejar pasar.
#   - dbt_docs leve: la documentación desactualizada no invalida los datos.
GRAVE_STEPS = ("ingest", "dbt_build")

# Subgrafos de dbt de cada recurso: el modelo de staging más todo lo que cuelga
# de él (y todo lo que necesita para construirse).
DBT_SELECT_COTIZACIONES = "+stg_frankfurter__cotizaciones+"
DBT_SELECT_MONEDAS = "+stg_frankfurter__monedas+"

# 4h: alcanza de sobra para la corrida incremental, para la reconciliación de un
# año y para la carga histórica completa (27 años en ventanas de 1 año son ~30
# requests).
_TIMEOUT = 14_400


def _run_step(results: dict, failed: list[str], name: str, fn, *args, **kwargs) -> None:
    """Ejecuta un paso, registra el resultado y nunca corta el flow.

    El corte lo decide `finalize_flow` al final, según la política grave/leve.
    """
    logger = get_logger(__name__)
    try:
        results[name] = fn(*args, **kwargs)
    except Exception:
        logger.exception("Paso '%s' falló — sigo con el resto.", name)
        failed.append(name)


# ---------------------------------------------------------------------------
# ETL 1 — catálogo de monedas
# ---------------------------------------------------------------------------


@enterprise_flow(
    name="frankfurter-currencies",
    description="Catálogo de monedas de Frankfurter → raw → subgrafo dbt de monedas.",
    retries=0,
    timeout_seconds=_TIMEOUT,
    on_completion=[notify_flow_success],
    on_failure=[notify_flow_failure],
)
def frankfurter_currencies_flow(
    full_refresh: bool = False,
    dbt_select: str | None = DBT_SELECT_MONEDAS,
) -> dict:
    """Ingesta del catálogo de monedas y refresh de su subgrafo.

    Args:
        full_refresh: descarta la tabla y el estado antes de cargar. Casi nunca
                      hace falta: el recurso ya es `replace`, así que cada corrida
                      reemplaza la foto anterior. Sirve cuando cambió el schema.
        dbt_select:   subgrafo a refrescar. None = no corre dbt.

    No expone `date_from` / `date_to` / `overlap` a propósito: el endpoint no tiene
    eje temporal. Ver `resources.currencies_source`.
    """
    logger = get_logger(__name__)
    results: dict = {}
    failed: list[str] = []

    logger.info("═══ FASE 1: catálogo de monedas → raw ═══")
    _run_step(results, failed, "ingest", ingest_currencies, full_refresh)

    if dbt_select:
        logger.info("═══ FASE 2: transformación dbt (%s) ═══", dbt_select)
        _run_step(results, failed, "dbt_build", dbt_build, dbt_select)

    return finalize_flow("frankfurter-currencies", results, failed, GRAVE_STEPS)


# ---------------------------------------------------------------------------
# ETL 2 — cotizaciones, incremental con overlap corto
# ---------------------------------------------------------------------------


@enterprise_flow(
    name="frankfurter-rates",
    description="Cotizaciones de Frankfurter → raw (incremental con overlap) → subgrafo dbt.",
    retries=0,
    timeout_seconds=_TIMEOUT,
    on_completion=[notify_flow_success],
    on_failure=[notify_flow_failure],
)
def frankfurter_rates_flow(
    date_from: str | None = None,
    date_to: str | None = None,
    full_refresh: bool = False,
    overlap: int | None = None,
    window_max: int | None = None,
    dbt_select: str | None = DBT_SELECT_COTIZACIONES,
) -> dict:
    """Corrida incremental de cotizaciones. Es el ETL de todos los días.

    Los tres modos que pide la operación, en un solo flow:

        sin argumentos        incremental con el overlap del entorno
                              (`INGEST_OVERLAP_DAYS`). Si raw está vacío, el runner
                              fuerza la carga histórica solo.
        date_from/date_to     backfill acotado y reproducible: pide EXACTAMENTE ese
                              rango, sin overlap, y NO mueve el cursor incremental.
                              Sirve para rellenar un hueco o repetir un tramo que la
                              API no pudo servir en su momento.
        full_refresh=True     descarta las tablas y el estado, y recarga desde 1999.

    Args:
        date_from / date_to: rango explícito (YYYY-MM-DD). `date_to` None = hasta hoy.
        full_refresh:        recarga histórica completa. Destructivo sobre raw.
        overlap:             días de re-pedido hacia atrás. None = el default del
                             entorno. Poner un número acá convierte esta corrida en
                             una reconciliación puntual sin tocar el deployment.
        window_max:          ventana máxima inicial del troceado, en días. Bajarlo si
                             la API responde lento; el control adaptativo igual se
                             ajusta solo.
        dbt_select:          subgrafo a refrescar. None = no corre dbt (útil para
                             rellenar raw en varias corridas y transformar al final).
    """
    logger = get_logger(__name__)
    results: dict = {}
    failed: list[str] = []

    logger.info("═══ FASE 1: cotizaciones → raw ═══")
    _run_step(
        results,
        failed,
        "ingest",
        ingest_exchange_rates,
        date_from,
        date_to,
        full_refresh,
        window_max,
        overlap,
    )

    if dbt_select:
        logger.info("═══ FASE 2: transformación dbt (%s) ═══", dbt_select)
        _run_step(results, failed, "dbt_build", dbt_build, dbt_select)

    return finalize_flow("frankfurter-rates", results, failed, GRAVE_STEPS)


# ---------------------------------------------------------------------------
# ETL 3 — cotizaciones, reconciliación con overlap largo
# ---------------------------------------------------------------------------


@enterprise_flow(
    name="frankfurter-rates-reconcile",
    description="Re-pide N días de cotizaciones para atrapar correcciones viejas del origen.",
    retries=0,
    timeout_seconds=_TIMEOUT,
    on_completion=[notify_flow_success],
    on_failure=[notify_flow_failure],
)
def frankfurter_rates_reconcile_flow(
    overlap: int | None = None,
    window_max: int | None = None,
    dbt_select: str | None = DBT_SELECT_COTIZACIONES,
) -> dict:
    """Barrido hacia atrás sobre las cotizaciones ya cargadas.

    Es un flow aparte —y no un parámetro más del ETL diario— para que tenga su
    propio schedule, su propio historial de corridas y su propia identidad en la
    UI y en las notificaciones. Cuando el overlap largo encuentra diferencias, uno
    quiere poder ver de un vistazo cuándo corrió y qué trajo, sin filtrar entre las
    corridas incrementales.

    Comparte pipeline, cursor y tabla con `frankfurter_rates_flow`: lo único que
    cambia es cuánto se re-pide hacia atrás. El merge por clave natural hace que
    re-pedir sea idempotente, así que correr los dos el mismo día no duplica nada.

    Args:
        overlap:    días hacia atrás. None = `INGEST_RECONCILE_OVERLAP_DAYS` (365 por
                    defecto). Subirlo en una corrida manual barre más historia: p. ej.
                    `overlap=3650` re-pide diez años.
        window_max: ventana máxima inicial del troceado, en días.
        dbt_select: subgrafo a refrescar. None = no corre dbt.
    """
    logger = get_logger(__name__)
    results: dict = {}
    failed: list[str] = []

    # Se resuelve acá y no en el runner para que quede en el log de la corrida con
    # cuántos días se barrió realmente, sin tener que ir a mirar el .env.
    dias = overlap if overlap is not None else reconcile_overlap_days()

    logger.info("═══ FASE 1: reconciliación de cotizaciones — %s días hacia atrás ═══", dias)
    _run_step(
        results,
        failed,
        "ingest",
        ingest_exchange_rates,
        None,  # date_from
        None,  # date_to
        False,  # full_refresh
        window_max,
        dias,
    )

    if dbt_select:
        logger.info("═══ FASE 2: transformación dbt (%s) ═══", dbt_select)
        _run_step(results, failed, "dbt_build", dbt_build, dbt_select)

    return finalize_flow(f"frankfurter-rates-reconcile ({dias}d)", results, failed, GRAVE_STEPS)


# ---------------------------------------------------------------------------
# Documentación de dbt
# ---------------------------------------------------------------------------


@enterprise_flow(
    name="dbt-docs",
    description="Regenera la documentación y el linaje de dbt.",
    retries=0,
    timeout_seconds=1_800,
    on_failure=[notify_flow_failure],
)
def dbt_docs_flow() -> dict:
    """Regenera las docs una vez por día, en lugar de en cada ETL.

    Está afuera de los ETLs a propósito: el catálogo se arma leyendo el schema real
    de la base, tarda, y no cambia por una corrida incremental. Que cada ETL lo
    regenerara significaría hacer el mismo trabajo tres veces al día para obtener
    el mismo resultado.

    Sin `on_completion`: una regeneración de docs exitosa no amerita notificación.
    """
    results: dict = {}
    failed: list[str] = []

    _run_step(results, failed, "dbt_docs", dbt_docs_generate)

    # dbt_docs es leve: la doc vieja no invalida los datos.
    return finalize_flow("dbt-docs", results, failed, grave_steps=())
