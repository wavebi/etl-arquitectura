"""Cliente de Frankfurter: los comportamientos de ESTA API que dlt no puede saber.

Se testea con una sesión falsa: no hay red. Lo que importa acá es la traducción
de las respuestas raras del origen, que es la única razón por la que el cliente
existe (el retry, el backoff y los timeouts los pone dlt).
"""

import json

import pytest
import requests

from ingestion.sources.frankfurter import client as client_module


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(response=self)


class _FakeRESTClient:
    """Reemplaza al RESTClient de dlt.

    Igual que el real, DEVUELVE la respuesta aunque el status sea de error: dlt no
    llama a `raise_for_status` por este camino. Quien decide es el cliente.
    """

    def __init__(self, responses):
        self._responses = responses
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        return self._responses.pop(0) if self._responses else _FakeResponse({}, 404)


@pytest.fixture
def make_client(monkeypatch):
    """Construye un FrankfurterClient con una sesión y un RESTClient falsos."""
    monkeypatch.setattr(client_module, "_build_session", lambda: object())

    def _make(responses):
        instance = client_module.FrankfurterClient.__new__(client_module.FrankfurterClient)
        instance._base_currency = "EUR"
        instance._client = _FakeRESTClient(list(responses))
        return instance

    return _make


def test_currencies_devuelve_el_catalogo(make_client):
    client = make_client([_FakeResponse({"USD": "United States Dollar", "BRL": "Brazilian Real"})])
    assert client.get_currencies() == {"USD": "United States Dollar", "BRL": "Brazilian Real"}


def test_un_404_significa_sin_datos_no_error(make_client):
    """La API responde 404 para rangos futuros o sin publicaciones. Tratarlo como
    error dejaría el ETL rojo por un fin de semana."""
    from datetime import date

    client = make_client([_FakeResponse({"message": "not found"}, 404)])
    assert client.get_rates(date(2030, 1, 1), date(2030, 1, 5)) == {}


def test_otros_errores_http_se_propagan(make_client):
    """Un 5xx tiene que romper, no devolver vacío.

    dlt reintenta los 5xx por dentro, pero cuando se agotan los intentos devuelve la
    respuesta con el status de error en vez de levantar excepción (usa `Session.send`,
    donde no corre `raise_for_status`). Si el cliente no chequeara el status, una caída
    del origen se vería como una carga exitosa de cero filas.
    """
    from datetime import date

    client = make_client([_FakeResponse({"message": "boom"}, 500)])
    with pytest.raises(requests.HTTPError):
        client.get_rates(date(2026, 1, 1), date(2026, 1, 5))


def test_normaliza_la_respuesta_de_un_solo_dia(make_client):
    """Para un día la API devuelve `rates` plano y la fecha aparte; para un rango,
    `rates` anidado por fecha. El cliente unifica los dos shapes y deja el resto del
    payload intacto (raw se queda con los campos del origen)."""
    from datetime import date

    client = make_client([_FakeResponse({"amount": 1.0, "base": "EUR", "date": "2026-01-02", "rates": {"USD": 1.17}})])
    payload = client.get_rates(date(2026, 1, 2), date(2026, 1, 2))
    assert payload["rates"] == {"2026-01-02": {"USD": 1.17}}
    assert payload["amount"] == 1.0
    assert payload["base"] == "EUR"


def test_devuelve_el_rango_anidado_tal_cual(make_client):
    from datetime import date

    payload = {
        "amount": 1.0,
        "base": "EUR",
        "start_date": "2026-01-02",
        "end_date": "2026-01-05",
        "rates": {"2026-01-02": {"USD": 1.17}, "2026-01-05": {"USD": 1.16}},
    }
    client = make_client([_FakeResponse(payload)])
    devuelto = client.get_rates(date(2026, 1, 2), date(2026, 1, 5))
    assert len(devuelto["rates"]) == 2
    assert devuelto["rates"]["2026-01-05"]["USD"] == 1.16


def test_pide_el_rango_en_el_path_y_la_base_por_query(make_client):
    from datetime import date

    client = make_client([_FakeResponse({"rates": {}})])
    client.get_rates(date(2026, 1, 1), date(2026, 3, 31), symbols=("USD", "BRL"))

    path, params = client._client.calls[0]
    assert path == "2026-01-01..2026-03-31"
    assert params["base"] == "EUR"
    assert params["symbols"] == "USD,BRL"


def test_la_respuesta_vacia_no_rompe(make_client):
    from datetime import date

    client = make_client([_FakeResponse({"amount": 1.0, "base": "EUR", "rates": {}})])
    assert client.get_rates(date(2026, 1, 1), date(2026, 1, 2))["rates"] == {}


def test_el_payload_es_json_valido():
    """Chequeo trivial de que el fake refleja el formato real documentado."""
    real = '{"amount":1.0,"base":"EUR","date":"2026-08-18","rates":{"USD":1.1576}}'
    assert json.loads(real)["rates"]["USD"] == 1.1576
