"""Notificaciones: nunca deben tumbar un flow, y no deben mandarse sin configurar."""

import pytest

from shared.services.telegram import notify_flow_failure, notify_flow_success
from shared.utils import notifications


@pytest.fixture
def sent(monkeypatch):
    """Captura los POST a Telegram en vez de hacerlos."""
    calls = []

    class _Response:
        ok = True
        status_code = 200
        text = ""

    def _fake_post(url, data=None, timeout=None):
        calls.append({"url": url, "data": data})
        return _Response()

    monkeypatch.setattr(notifications.requests, "post", _fake_post)
    return calls


@pytest.fixture
def _configured(monkeypatch):
    """Credenciales de Telegram presentes."""
    from pydantic import SecretStr

    monkeypatch.setattr(notifications.settings, "TELEGRAM_BOT_TOKEN", SecretStr("token-test"))
    monkeypatch.setattr(notifications.settings, "TELEGRAM_CHAT_ID", SecretStr("chat-test"))


def test_sin_credenciales_no_manda_nada(sent):
    notifications.notify_telegram("info", "hola")
    assert sent == []


def test_con_credenciales_manda_el_mensaje(sent, _configured):
    notifications.notify_telegram("error", "el ETL falló", details={"paso": "dbt_run"})
    assert len(sent) == 1
    body = sent[0]["data"]["text"]
    assert "el ETL falló" in body
    assert "dbt_run" in body


def test_un_error_de_telegram_no_propaga(monkeypatch, _configured):
    """Si Telegram se cae, el ETL tiene que seguir. Nunca al revés."""

    def _explota(*args, **kwargs):
        raise ConnectionError("telegram caído")

    monkeypatch.setattr(notifications.requests, "post", _explota)
    notifications.notify_telegram("info", "test")  # no debe levantar


def test_los_detalles_muy_largos_se_truncan(sent, _configured):
    notifications.notify_telegram("info", "t", details={"payload": "x" * 5000})
    assert "truncated" in sent[0]["data"]["text"]


class _Flow:
    name = "etl-test"


class _FlowRun:
    id = "run-123"
    start_time = None
    total_run_time = None


class _State:
    message = "boom"
    timestamp = None

    def __init__(self, result=None):
        self._result = result

    def result(self, raise_on_failure=True):
        return self._result


def test_hook_de_exito_manda_info(sent, _configured):
    notify_flow_success(_Flow(), _FlowRun(), _State({"status": "ok"}))
    assert "completado OK" in sent[0]["data"]["text"]


def test_hook_de_exito_avisa_degradado_como_warning(sent, _configured):
    """Un flow degradado (falló algo leve) tiene que distinguirse de un OK."""
    notify_flow_success(_Flow(), _FlowRun(), _State({"status": "degraded", "failed_steps": ["dbt_test"]}))
    body = sent[0]["data"]["text"]
    assert "DEGRADADO" in body
    assert "dbt_test" in body


def test_hook_de_falla_incluye_el_error(sent, _configured):
    notify_flow_failure(_Flow(), _FlowRun(), _State())
    body = sent[0]["data"]["text"]
    assert "FALLÓ" in body
    assert "boom" in body
