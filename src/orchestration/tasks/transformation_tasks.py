"""Tasks de transformación: ejecutan dbt.

Un comando de dbt por task, para que en la UI de Prefect se vea qué etapa falló
(seed, run, snapshot o test) sin abrir los logs.
"""

from prefect import task

from shared.utils.dbt_utils import run_dbt_command
from shared.utils.logging import LogTimer, get_logger


@task(
    name="dbt-build",
    description="Ejecuta dbt build: seeds, modelos, snapshots y tests en orden de dependencias.",
    retries=1,
    retry_delay_seconds=10,
    tags=["transformation", "dbt"],
)
def dbt_build(select: str | None = None) -> dict:
    """Ejecuta `dbt build`, que es la forma correcta de correr el proyecto completo.

    Por qué `build` y no `seed` + `run` + `snapshot` + `test` por separado: dbt resuelve
    el orden a partir del DAG, y ese orden NO es el intuitivo. En este proyecto, por
    ejemplo, un snapshot lee un modelo de staging (así que va DESPUÉS de `run`) y un
    mart lee ese snapshot (así que va DESPUÉS de `snapshot`). Con los pasos separados,
    la primera corrida sobre una base limpia falla con "relation does not exist" y la
    segunda funciona — el peor tipo de error, porque parece intermitente.

    Además `build` corta el subgrafo de un modelo cuyo test falló con `severity: error`,
    en lugar de seguir construyendo marts sobre datos que ya se sabe que están mal.

    Los tests con `severity: warn` (el default del proyecto) NO hacen fallar el build:
    avisan. Ver dbt_project.yml.
    """
    logger = get_logger(__name__)

    label = f"dbt build --select {select}" if select else "dbt build"
    with LogTimer(logger, label):
        run_dbt_command("build", select=select)

    return {"command": "build", "select": select, "status": "ok"}


@task(
    name="dbt-run",
    description="Ejecuta dbt run para materializar modelos (staging → intermediate → marts).",
    retries=1,
    retry_delay_seconds=10,
    tags=["transformation", "dbt"],
)
def dbt_run(select: str | None = None) -> dict:
    """Ejecuta dbt run con selector opcional."""
    logger = get_logger(__name__)

    label = f"dbt run --select {select}" if select else "dbt run"
    with LogTimer(logger, label):
        run_dbt_command("run", select=select)

    return {"command": "run", "select": select, "status": "ok"}


@task(
    name="dbt-test",
    description="Ejecuta dbt test para validar calidad de datos.",
    retries=1,
    retry_delay_seconds=10,
    tags=["transformation", "dbt"],
)
def dbt_test(select: str | None = None) -> dict:
    """Ejecuta dbt test con selector opcional."""
    logger = get_logger(__name__)

    label = f"dbt test --select {select}" if select else "dbt test"
    with LogTimer(logger, label):
        run_dbt_command("test", select=select)

    return {"command": "test", "select": select, "status": "ok"}


@task(
    name="dbt-seed",
    description="Carga seeds (CSVs) en el data warehouse.",
    retries=1,
    retry_delay_seconds=10,
    tags=["transformation", "dbt", "seed"],
)
def dbt_seed(select: str | None = None) -> dict:
    """Ejecuta dbt seed con selector opcional."""
    logger = get_logger(__name__)

    label = f"dbt seed --select {select}" if select else "dbt seed"
    with LogTimer(logger, label):
        run_dbt_command("seed", select=select)

    return {"command": "seed", "select": select, "status": "ok"}


@task(
    name="dbt-snapshot",
    description="Captura snapshots SCD Type 2 (histórico de cambios) sobre staging.",
    retries=1,
    retry_delay_seconds=10,
    tags=["transformation", "dbt", "snapshot"],
)
def dbt_snapshot(select: str | None = None) -> dict:
    """Ejecuta dbt snapshot con selector opcional.

    Registra el histórico de cambios (SCD Type 2) de los catálogos que el origen
    pisa con `replace` en cada carga. Corre DESPUÉS de `dbt_run`: los snapshots
    leen los modelos de staging ya materializados.
    """
    logger = get_logger(__name__)

    label = f"dbt snapshot --select {select}" if select else "dbt snapshot"
    with LogTimer(logger, label):
        run_dbt_command("snapshot", select=select)

    return {"command": "snapshot", "select": select, "status": "ok"}


@task(
    name="dbt-docs-generate",
    description="Regenera el catálogo de documentación y linaje de dbt.",
    retries=1,
    retry_delay_seconds=10,
    tags=["transformation", "dbt", "docs"],
)
def dbt_docs_generate() -> dict:
    """Regenera `target/catalog.json` y `target/manifest.json`.

    El servicio `dbt-docs` del compose sirve esos archivos: si no se regeneran
    después de un cambio de modelos, la documentación queda mostrando el linaje
    viejo — que es peor que no tener documentación.
    """
    logger = get_logger(__name__)

    with LogTimer(logger, "dbt docs generate"):
        run_dbt_command("docs generate")

    return {"command": "docs generate", "status": "ok"}
