"""Cancela flow runs huérfanos (RUNNING + PENDING) del work pool al arrancar el worker.

Cuando el worker container se reinicia (deploy, crash, docker restart), los runs que
estaba ejecutando quedan marcados como RUNNING en el server pero no hay nadie que los
ejecute — son zombies. Este script los cancela explícitamente para que la UI refleje el
estado real.

No toca runs SCHEDULED: esos son ejecuciones futuras del scheduler y deben seguir vivos.
"""

import asyncio

from prefect import get_client
from prefect.client.schemas.filters import (
    FlowRunFilter,
    FlowRunFilterState,
    FlowRunFilterStateType,
    WorkPoolFilter,
    WorkPoolFilterName,
)
from prefect.states import Cancelled

from shared.settings import settings
from shared.utils.logging import get_logger

logger = get_logger(__name__)

STALE_STATES = ["RUNNING", "PENDING"]


async def cancel_stale_runs(work_pool_name: str) -> int:
    """Cancela runs RUNNING/PENDING en el work pool dado. Retorna cantidad cancelada."""
    cancelled = 0
    async with get_client() as client:
        runs = await client.read_flow_runs(
            flow_run_filter=FlowRunFilter(
                state=FlowRunFilterState(type=FlowRunFilterStateType(any_=STALE_STATES)),
            ),
            work_pool_filter=WorkPoolFilter(name=WorkPoolFilterName(any_=[work_pool_name])),
        )

        if not runs:
            logger.info(f"No hay runs huérfanos en work pool '{work_pool_name}'.")
            return 0

        logger.warning(
            f"Encontrados {len(runs)} runs huérfanos en '{work_pool_name}' (estados: {STALE_STATES}). Cancelando..."
        )
        for run in runs:
            try:
                await client.set_flow_run_state(run.id, Cancelled(), force=True)
                logger.info(f"  Cancelado: {run.name} [{run.state_name}] ({run.id})")
                cancelled += 1
            except Exception as exc:
                logger.warning(f"  No se pudo cancelar {run.id}: {exc}")

    return cancelled


def main() -> None:
    pool = settings.PREFECT_WORK_POOL_NAME
    logger.info(f"Limpiando runs huérfanos del work pool '{pool}'...")
    try:
        total = asyncio.run(cancel_stale_runs(pool))
        logger.info(f"Limpieza completa. {total} runs cancelados.")
    except Exception as exc:
        logger.warning(f"Error durante limpieza de runs huérfanos: {exc}")


if __name__ == "__main__":
    main()
