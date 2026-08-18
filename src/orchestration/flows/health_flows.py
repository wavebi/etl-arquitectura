"""Flow de health check — valida la conectividad del stack de ETL."""

from prefect import task

from shared.utils.logging import LogTimer, get_logger
from shared.utils.orchestration import enterprise_flow


@task(
    name="check-database",
    description="Valida la conectividad con PostgreSQL mediante un SELECT 1 liviano.",
    retries=2,
    retry_delay_seconds=5,
    tags=["infra", "db"],
)
def check_database() -> dict:
    """Hace ping a la instancia de PostgreSQL configurada y devuelve sus metadatos de conexión."""
    logger = get_logger(__name__)

    with LogTimer(logger, "PostgreSQL connectivity check"):
        from shared.utils.warehouse import get_connection

        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT version(), current_database(), current_user, inet_server_addr()")
            row = dict(cur.fetchone())

    logger.info(
        "✅ PostgreSQL reachable — db=%s user=%s server=%s",
        row.get("current_database"),
        row.get("current_user"),
        row.get("inet_server_addr"),
    )
    return row


@enterprise_flow(
    name="health-check",
    description="Valida que el worker de Prefect pueda alcanzar toda la infraestructura crítica.",
)
def health_check() -> dict:
    """Health check enterprise: conectividad del worker de Prefect + PostgreSQL."""
    logger = get_logger(__name__)
    logger.info("✅ Prefect server: reachable (worker is executing this flow)")

    result: dict = {"status": "ok", "db": None}
    try:
        db_meta = check_database()
        # Parseo tolerante: "PostgreSQL 15.3 on ..." → "15.3". Un string sin
        # espacios (o vacío) cae a "unknown" en vez de tirar IndexError y marcar
        # falsamente la DB como inalcanzable.
        version_parts = (db_meta.get("version") or "").split(" ")
        pg_version = version_parts[1] if len(version_parts) > 1 else "unknown"
        result["db"] = {
            "reachable": True,
            "database": db_meta.get("current_database"),
            "server": str(db_meta.get("inet_server_addr")),
            "pg_version": pg_version,
        }
    except Exception:
        logger.exception("❌ PostgreSQL check failed — see traceback above")
        result["status"] = "degraded"
        result["db"] = {"reachable": False}

    return result
