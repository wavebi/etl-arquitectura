"""Conexión al warehouse: credenciales bien armadas y transacciones cerradas."""

import pytest

from shared.utils import warehouse


class _FakeCursor:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.kwargs = {}

    def cursor(self):
        return _FakeCursor()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture
def fake_connect(monkeypatch):
    created = []

    def _connect(**kwargs):
        conn = _FakeConnection()
        conn.kwargs = kwargs
        created.append(conn)
        return conn

    monkeypatch.setattr(warehouse.psycopg2, "connect", _connect)
    return created


def test_get_destination_usa_los_settings():
    destination = warehouse.get_destination()
    assert destination is not None


def test_la_conexion_commitea_y_cierra(fake_connect):
    with warehouse.get_connection() as conn, conn.cursor() as cur:
        cur.execute("select 1")

    assert conn.committed
    assert conn.closed


def test_la_conexion_hace_rollback_y_cierra_ante_error(fake_connect):
    """Sin esto, una excepción deja la transacción abierta y bloquea la tabla."""
    with pytest.raises(ValueError), warehouse.get_connection() as conn:
        raise ValueError("boom")

    assert conn.rolled_back
    assert conn.closed
    assert not conn.committed


def test_pasa_las_credenciales_de_settings(fake_connect, monkeypatch):
    monkeypatch.setattr(warehouse.settings, "DB_HOST", "db.test")
    monkeypatch.setattr(warehouse.settings, "DB_NAME", "warehouse_test")

    with warehouse.get_connection():
        pass

    kwargs = fake_connect[0].kwargs
    assert kwargs["host"] == "db.test"
    assert kwargs["dbname"] == "warehouse_test"
    # La contraseña se pasa como valor plano, no como SecretStr.
    assert isinstance(kwargs["password"], str)
