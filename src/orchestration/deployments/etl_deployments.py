"""Deployments de los flows de ETL.

## Un deployment por SCHEDULE, no uno por forma de correr algo

Lo único que un deployment aporta y que la UI no puede improvisar es un horario.
Todo lo demás —correr a mano, pisar parámetros, forzar un rango, pedir la carga
histórica— sale de "Custom run" sobre el deployment que ya existe: Prefect muestra
los parámetros del flow y se completan en el momento.

Por eso NO hay deployments `-manual`, ni un `-historical`, ni un `-backfill`.
Serían el mismo flow con los campos precargados, y el costo de tenerlos es real:
cada uno es una entrada más que mantener sincronizada cuando cambia la firma del
flow, y una más entre las que hay que elegir cuando algo se rompe a las 3 de la
mañana.

    ¿Necesito la carga histórica?   Custom run de `frankfurter-rates`
                                    con full_refresh = true.
    ¿Necesito un tramo puntual?     Custom run con date_from / date_to.
    ¿Necesito barrer 10 años?       Custom run de `frankfurter-rates-reconcile`
                                    con overlap = 3650.

## Convenciones

    - El deployment se llama como el flow. Sin sufijos: no hay dos variantes que
      distinguir.
    - Los schedules se activan SOLO en producción. En desarrollo los deployments
      se registran sin schedule: nadie quiere que su máquina golpee la API del
      origen cada mañana. El disparo manual desde la UI funciona igual.
    - Los horarios se declaran en la timezone de `settings.TIMEZONE`, no en UTC:
      el negocio piensa en hora local y el cambio de horario no debe correr los
      procesos.
    - `parameters` explícitos aunque sean None: así la UI muestra los campos y se
      pueden completar en un custom run sin editar el deployment.
    - Los defaults de overlap NO se escriben acá: van en `.env`
      (`INGEST_OVERLAP_DAYS`, `INGEST_RECONCILE_OVERLAP_DAYS`) y los deployments
      pasan `None` para que el flow los resuelva. Hardcodear un 7 o un 365 en este
      archivo obligaría a un deploy para cambiar una política operativa.
"""

from __future__ import annotations

from prefect.schedules import Cron

from orchestration.flows.etl_flows import (
    DBT_SELECT_COTIZACIONES,
    DBT_SELECT_MONEDAS,
    dbt_docs_flow,
    frankfurter_currencies_flow,
    frankfurter_rates_flow,
    frankfurter_rates_reconcile_flow,
)
from shared.settings import settings

_ENTRYPOINT = "src/orchestration/flows/etl_flows.py"

# Solo producción corre con schedule activo.
_SCHEDULES_ENABLED = settings.is_prod


def _schedule(cron: str) -> list[Cron]:
    """Schedule en hora local, activo solo en producción."""
    return [Cron(cron, timezone=settings.TIMEZONE)] if _SCHEDULES_ENABLED else []


# ---------------------------------------------------------------------------
# Horarios — la única razón por la que estos deployments existen por separado
# ---------------------------------------------------------------------------
# El BCE publica las cotizaciones del día alrededor de las 16:00 CET, es decir
# ~12:00 en Argentina. Los ETLs del día corren a partir de las 13:20 hora local:
# con margen para que la publicación esté disponible, y de lunes a viernes porque
# el BCE no publica los fines de semana (un sábado no traerían nada nuevo).
#
# El catálogo va primero para que la dimensión de monedas ya tenga la foto del día
# cuando entren las cotizaciones. No es una dependencia dura —los dos subgrafos se
# reconstruyen solos— pero evita que la dimensión quede un ciclo atrasada.
CURRENCIES_CRON = "20 13 * * 1-5"
RATES_CRON = "30 13 * * 1-5"

# La reconciliación corre de madrugada y TODOS los días, incluidos sábado y
# domingo: no depende de que el BCE publique hoy, sino de que pueda haber
# corregido algo publicado semanas atrás. A esa hora no compite por el `dbt-lock`.
RECONCILE_CRON = "30 3 * * *"

# Las docs, después de que corrieron los ETLs del día.
DBT_DOCS_CRON = "0 15 * * 1-5"


etl_deployments = [
    # --- ETL 1: catálogo de monedas ------------------------------------------
    frankfurter_currencies_flow.from_source(
        source=".",
        entrypoint=f"{_ENTRYPOINT}:frankfurter_currencies_flow",
    ).to_deployment(
        name="frankfurter-currencies",
        tags=["etl", "frankfurter", "currencies"],
        parameters={"full_refresh": False, "dbt_select": DBT_SELECT_MONEDAS},
        schedules=_schedule(CURRENCIES_CRON),
    ),
    # --- ETL 2: cotizaciones, incremental con overlap corto ------------------
    # La carga histórica y el backfill son custom runs de ESTE deployment:
    # full_refresh=true recarga desde 1999; date_from/date_to piden un tramo
    # exacto sin mover el cursor.
    frankfurter_rates_flow.from_source(
        source=".",
        entrypoint=f"{_ENTRYPOINT}:frankfurter_rates_flow",
    ).to_deployment(
        name="frankfurter-rates",
        tags=["etl", "frankfurter", "rates"],
        # overlap=None ⇒ el flow usa INGEST_OVERLAP_DAYS del entorno.
        parameters={
            "date_from": None,
            "date_to": None,
            "full_refresh": False,
            "overlap": None,
            "window_max": None,
            "dbt_select": DBT_SELECT_COTIZACIONES,
        },
        schedules=_schedule(RATES_CRON),
    ),
    # --- ETL 3: cotizaciones, reconciliación con overlap largo ---------------
    # Deployment aparte porque tiene OTRO horario y otros parámetros, no porque
    # sea otra forma de correrlo a mano.
    frankfurter_rates_reconcile_flow.from_source(
        source=".",
        entrypoint=f"{_ENTRYPOINT}:frankfurter_rates_reconcile_flow",
    ).to_deployment(
        name="frankfurter-rates-reconcile",
        tags=["etl", "frankfurter", "rates", "reconciliacion"],
        # overlap=None ⇒ el flow usa INGEST_RECONCILE_OVERLAP_DAYS del entorno.
        # Para barrer más atrás: custom run con overlap=3650 (diez años).
        parameters={"overlap": None, "window_max": None, "dbt_select": DBT_SELECT_COTIZACIONES},
        schedules=_schedule(RECONCILE_CRON),
    ),
    # --- Documentación de dbt, una vez por día y fuera de los ETLs -----------
    dbt_docs_flow.from_source(
        source=".",
        entrypoint=f"{_ENTRYPOINT}:dbt_docs_flow",
    ).to_deployment(
        name="dbt-docs",
        tags=["dbt", "docs"],
        schedules=_schedule(DBT_DOCS_CRON),
    ),
]
