from dbt.cli.main import dbtRunner
from prefect.concurrency.sync import concurrency

from shared.settings import settings
from shared.utils.logging import get_logger


def run_dbt_command(command: str, select: str | None = None) -> None:
    """
    Ejecuta un comando DBT de forma programática y maneja errores estandarizados.
    Usa la configuración definida en settings.py.

    Args:
        command: Comando de dbt ('run', 'snapshot', 'test', 'docs generate'...).
        select: Selector opcional para filtrar modelos (ej: 'tag:marts', 'fct_x').

    Raises:
        Exception: Si el comando DBT falla
    """
    # get_logger (no get_run_logger): devuelve el logger de Prefect dentro de un
    # flow y cae a stderr fuera de uno, así el mismo código sirve para correr dbt
    # desde un script o una consola.
    logger = get_logger(__name__)
    dbt = dbtRunner()

    args = [
        "--log-path",
        settings.DBT_LOG_PATH,
        # `command.split()` y no `command`: dbtRunner espera argumentos sueltos, y
        # los comandos de dos palabras ("docs generate", "source freshness") se
        # pasarían como uno solo e invalidarían la invocación.
        *command.split(),
        "--project-dir",
        settings.DBT_PROJECT_DIR,
        "--profiles-dir",
        settings.DBT_PROJECT_DIR,
    ]

    if select:
        args.extend(["--select", select])

    logger.info(f"Ejecutando DBT: {' '.join(args)}")

    with concurrency("dbt-lock", occupy=1):
        res = dbt.invoke(args)

    if not res.success:
        if res.exception:
            logger.error(f"Excepcion Critica DBT: {res.exception}")

        if res.result:
            for r in res.result:
                if r.status in ["error", "fail"]:
                    logger.error(f"Error en Nodo ({r.node.name}): {r.message}")

        raise Exception(f"Fallo en ejecucion DBT: {command} {select or ''}")

    logger.info(f"DBT {command} completado exitosamente.")
