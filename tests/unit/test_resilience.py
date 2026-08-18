"""Circuit breaker: cuándo corta y cuándo no.

El retry lo hace dlt; acá se prueba la capa que dlt no tiene: dejar de insistir
cuando el origen está caído, sin que un 4xx nuestro cuente como caída.
"""

import pytest
import requests

from shared.utils.resilience import CircuitBreaker, CircuitOpenError


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


def test_pasa_el_resultado_cuando_todo_anda():
    breaker = CircuitBreaker(name="test-ok")
    assert breaker.call(lambda: "dato") == "dato"
    assert breaker.current_state == "closed"


def test_se_abre_tras_el_umbral_y_deja_de_llamar_al_origen():
    avisos = []
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60, name="test-open")
    breaker.add_on_open_callback(lambda: avisos.append(1))

    llamadas_reales = 0

    def falla():
        nonlocal llamadas_reales
        llamadas_reales += 1
        raise requests.Timeout()

    for _ in range(10):
        with pytest.raises((requests.Timeout, CircuitOpenError)):
            breaker.call(falla)

    assert breaker.current_state == "open"
    assert llamadas_reales <= 3, "abierto el breaker, no se debe seguir llamando"
    assert avisos, "el callback on_open tiene que haberse disparado"


def test_los_4xx_no_abren_el_breaker():
    """Un 403 es un problema de permisos nuestro, no del origen: si abriera el
    breaker, un endpoint mal configurado frenaría la ingesta de todos los demás."""
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60, name="test-4xx")

    def sin_permisos():
        raise _http_error(403)

    for _ in range(5):
        with pytest.raises(requests.HTTPError):
            breaker.call(sin_permisos)

    assert breaker.current_state == "closed"


@pytest.mark.parametrize("status", [408, 429])
def test_los_status_de_saturacion_si_cuentan(status):
    """408 y 429 hablan del estado del origen, no de nuestra configuración.

    La llamada que alcanza el umbral ya sale como CircuitOpenError (pybreaker
    reporta la apertura en vez de la excepción original), así que se aceptan las
    dos y lo que se verifica es el estado final.
    """
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=60, name=f"test-{status}")

    def saturado():
        raise _http_error(status)

    for _ in range(3):
        with pytest.raises((requests.HTTPError, CircuitOpenError)):
            breaker.call(saturado)

    assert breaker.current_state == "open"


def test_un_callback_roto_no_tumba_el_etl():
    """Si la notificación de apertura falla, se loguea y el ETL sigue: el aviso no
    puede ser más importante que el proceso."""
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60, name="test-cb")
    breaker.add_on_open_callback(lambda: 1 / 0)

    with pytest.raises((requests.Timeout, CircuitOpenError)):
        breaker.call(lambda: (_ for _ in ()).throw(requests.Timeout()))

    # El ZeroDivisionError del callback quedó logueado, no propagado.
    assert breaker.current_state == "open"
