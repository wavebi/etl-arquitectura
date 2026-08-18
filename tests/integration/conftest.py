"""Fixtures de integración: el Postgres real del stack local.

Los tests de integración corren dlt y SQL de verdad contra el Postgres del compose
(`make up`), en una base dedicada y descartable — nunca contra la del desarrollo.

Si no hay Postgres escuchando, los tests se SALTEAN en vez de fallar: así la suite
sigue verde en una máquina sin Docker y en el CI que no levanta servicios.
"""

import os

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor
from pydantic import SecretStr

# Coordenadas del Postgres del compose. Se pueden pisar por entorno para apuntar a
# otra instancia (otro puerto, un servicio de CI) sin tocar el código.
PG_SERVER = {
    "host": os.getenv("TEST_PG_HOST", "localhost"),
    "port": int(os.getenv("TEST_PG_PORT", "5442")),
    "user": os.getenv("TEST_PG_USER", "etl_app"),
    "password": os.getenv("TEST_PG_PASSWORD", "dev_password"),
    "sslmode": "disable",
}
MAINTENANCE_DB = os.getenv("TEST_PG_DB", "warehouse")  # solo para crear la de test
TEST_DB = "warehouse_test"  # base de integración, descartable

# Crear una base es una operación de administración: el rol del ETL no puede (ni
# debe poder) hacerlo. Solo para eso se usa el superuser del Postgres local.
PG_ADMIN = {
    **PG_SERVER,
    "user": os.getenv("TEST_PG_SUPERUSER", "postgres"),
    "password": os.getenv("TEST_PG_SUPERUSER_PASSWORD", "postgres"),
}


def _connect(dbname: str, **extra):
    return psycopg2.connect(dbname=dbname, **PG_SERVER, **extra)


def _can_connect() -> bool:
    try:
        psycopg2.connect(dbname=MAINTENANCE_DB, **PG_ADMIN).close()
        return True
    except Exception:
        return False


def _ensure_test_db() -> None:
    """Crea la base de test (como admin) y le da permisos al rol del ETL."""
    conn = psycopg2.connect(dbname=MAINTENANCE_DB, **PG_ADMIN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{TEST_DB}"')
            cur.execute(f'GRANT ALL ON DATABASE "{TEST_DB}" TO {PG_SERVER["user"]}')
    finally:
        conn.close()

    # El rol del ETL tiene que poder crear schemas en la base de test.
    conn = psycopg2.connect(dbname=TEST_DB, **PG_ADMIN)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'GRANT CREATE ON DATABASE "{TEST_DB}" TO {PG_SERVER["user"]}')
    finally:
        conn.close()


def _reset_raw() -> None:
    conn = _connect(TEST_DB)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS raw CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS raw_staging CASCADE")
            cur.execute("CREATE SCHEMA raw")
    finally:
        conn.close()


@pytest.fixture
def local_raw(monkeypatch, tmp_path):
    """Apunta settings y dlt a la base de test, y limpia raw antes y después."""
    if not _can_connect():
        pytest.skip(f"Postgres no disponible en {PG_SERVER['host']}:{PG_SERVER['port']} — corré `make up`")

    _ensure_test_db()

    from shared.settings import settings

    monkeypatch.setattr(settings, "DB_HOST", PG_SERVER["host"])
    monkeypatch.setattr(settings, "DB_PORT", PG_SERVER["port"])
    monkeypatch.setattr(settings, "DB_NAME", TEST_DB)
    monkeypatch.setattr(settings, "DB_USER", PG_SERVER["user"])
    monkeypatch.setattr(settings, "DB_PASSWORD", SecretStr(PG_SERVER["password"]))
    monkeypatch.setattr(settings, "DB_SSLMODE", "disable")
    # Aísla el estado local de dlt (cursores incrementales, schemas) por test.
    monkeypatch.setenv("DLT_DATA_DIR", str(tmp_path / "dlt"))

    _reset_raw()
    yield
    _reset_raw()


@pytest.fixture
def query(local_raw):
    """Consulta la base de test y devuelve lista de dicts."""

    def _q(sql: str, params=None):
        conn = _connect(TEST_DB, cursor_factory=RealDictCursor)
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall()
        finally:
            conn.close()

    return _q
