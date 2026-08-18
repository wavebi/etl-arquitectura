"""Smoke contra la API real de Frankfurter.

No corre en la suite normal: requiere `RUN_LIVE_TESTS=1` (y salida a internet).
Sirve para verificar de una que el contrato del origen sigue siendo el que asume el
pipeline, antes de debuggear una carga entera.

    make test-live
"""

import os
from datetime import date, timedelta

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("RUN_LIVE_TESTS") != "1",
        reason="test live: requiere RUN_LIVE_TESTS=1 y salida a internet",
    ),
]


@pytest.fixture
def client():
    from ingestion.sources.frankfurter import FrankfurterClient

    return FrankfurterClient()


def test_el_catalogo_de_monedas_responde(client):
    catalogo = client.get_currencies()
    assert len(catalogo) > 20
    assert "USD" in catalogo


def test_un_rango_corto_devuelve_cotizaciones(client):
    hasta = date.today()
    desde = hasta - timedelta(days=10)

    payload = client.get_rates(desde, hasta)
    assert payload["rates"], "un rango de 10 días tiene que traer al menos un día hábil"
    # El payload conserva los campos del origen: es lo que después va a raw tal cual.
    assert payload["base"]
    assert payload["amount"] == 1.0

    primera = next(iter(payload["rates"].values()))
    assert "USD" in primera
    assert primera["USD"] > 0


def test_un_rango_futuro_no_es_un_error(client):
    """El origen responde 404 y el cliente lo traduce a "sin datos"."""
    futuro = date.today() + timedelta(days=365)
    assert client.get_rates(futuro, futuro + timedelta(days=5)) == {}


def test_el_origen_sigue_usando_su_vocabulario(client):
    """raw guarda los nombres del origen: si la API los cambia, hay que enterarse."""
    payload = client.get_rates(date(2026, 1, 2), date(2026, 1, 6))
    assert {"amount", "base", "rates"} <= set(payload), f"la API cambió el shape de la respuesta: {sorted(payload)}"


def test_el_inicio_del_historico_sigue_disponible(client):
    """Si el origen recorta el histórico, la carga histórica del pipeline cambia."""
    from ingestion.pipelines.frankfurter.constants import history_start

    inicio = history_start()
    payload = client.get_rates(inicio, inicio + timedelta(days=5))
    assert payload.get("rates"), f"el origen ya no publica datos desde {inicio}"
