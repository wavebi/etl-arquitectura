from contextlib import contextmanager

import dlt
import psycopg2
from psycopg2.extras import RealDictCursor

from shared.settings import settings


def get_destination():
    """Retorna la configuración centralizada del destino Postgres (DLT)."""
    return dlt.destinations.postgres(
        credentials={
            "database": settings.DB_NAME,
            "password": settings.DB_PASSWORD.get_secret_value(),
            "username": settings.DB_USER,
            "host": settings.DB_HOST,
            "port": settings.DB_PORT,
            "sslmode": settings.DB_SSLMODE,
        }
    )


@contextmanager
def get_connection():
    """
    Retorna una conexión segura que SE CIERRA AUTOMÁTICAMENTE.
    Uso:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    conn = None
    try:
        conn = psycopg2.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            dbname=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD.get_secret_value(),
            sslmode=settings.DB_SSLMODE,
            cursor_factory=RealDictCursor,
        )
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()
