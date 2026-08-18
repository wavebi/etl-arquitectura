"""Troceado adaptativo: es lo único de la resiliencia que no delega en dlt, así que
su comportamiento tiene que estar fijado por tests.

Todo se prueba sin red: `fetch` es una función que decide fallar o no según el
tamaño de la ventana que le pasan.
"""

from datetime import date, timedelta
from itertools import pairwise

import pytest
import requests

from ingestion.pipelines.frankfurter.chunking import (
    WindowPolicy,
    WindowReport,
    fetch_adaptive,
    is_window_error,
)


def _timeout() -> requests.Timeout:
    return requests.Timeout("demasiado grande")


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(response=response)


# ---------------------------------------------------------------------------
# Clasificación de errores
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [413, 414, 500, 502, 503, 504])
def test_los_errores_de_tamano_habilitan_reducir_la_ventana(status):
    assert is_window_error(_http_error(status))


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_los_errores_del_cliente_no_son_de_tamano(status):
    """Un 404 no se arregla pidiendo menos: hay que propagarlo."""
    assert not is_window_error(_http_error(status))


def test_timeout_y_corte_de_conexion_son_de_tamano():
    assert is_window_error(requests.Timeout())
    assert is_window_error(requests.ConnectionError())


# ---------------------------------------------------------------------------
# Recorrido
# ---------------------------------------------------------------------------


def test_cubre_todo_el_rango_sin_huecos_ni_solapes():
    visitados: list[tuple[date, date]] = []

    def fetch(desde, hasta):
        visitados.append((desde, hasta))
        return (desde, hasta)

    policy = WindowPolicy(max_days=10, successes_before_grow=99)  # sin crecimiento
    list(fetch_adaptive(fetch, date(2026, 1, 1), date(2026, 1, 25), policy))

    assert visitados[0][0] == date(2026, 1, 1)
    assert visitados[-1][1] == date(2026, 1, 25)
    # Cada tramo arranca justo el día siguiente al fin del anterior.
    for (_, fin), (inicio, _) in pairwise(visitados):
        assert inicio == fin + timedelta(days=1)


def test_arranca_con_la_ventana_maxima():
    """El punto del control adaptativo: pedir grande primero."""
    tamanos = []

    def fetch(desde, hasta):
        tamanos.append((hasta - desde).days + 1)
        return None

    list(fetch_adaptive(fetch, date(2026, 1, 1), date(2026, 12, 31), WindowPolicy(max_days=365)))
    assert tamanos[0] == 365


def test_reduce_la_ventana_cuando_el_origen_falla():
    intentos = []

    def fetch(desde, hasta):
        dias = (hasta - desde).days + 1
        intentos.append(dias)
        # Solo entran ventanas de 25 días o menos.
        if dias > 25:
            raise _timeout()
        return dias

    policy = WindowPolicy(max_days=100, shrink_divisor=2.0, successes_before_grow=99)
    # Rango más largo que la ventana máxima, para que el primer pedido sea de 100
    # días completos (si no, el tramo lo recorta el fin del rango).
    resultados = list(fetch_adaptive(fetch, date(2026, 1, 1), date(2026, 6, 30), policy))

    assert intentos[0] == 100, "probó con la ventana máxima"
    assert min(intentos) <= 25, "se fue achicando hasta que la API aceptó"
    assert resultados, "tuvo que traer datos con la ventana chica"


def test_vuelve_a_crecer_despues_de_varios_exitos():
    """Sin esto, una lentitud pasajera dejaría toda la carga histórica en la
    ventana mínima: el pipeline se defendería pero nunca se recuperaría."""
    tamanos = []
    fallas = {"restantes": 1}

    def fetch(desde, hasta):
        dias = (hasta - desde).days + 1
        tamanos.append(dias)
        if fallas["restantes"] > 0 and dias > 10:
            fallas["restantes"] -= 1
            raise _timeout()
        return dias

    policy = WindowPolicy(max_days=40, shrink_divisor=2.0, grow_factor=2.0, successes_before_grow=2)
    list(fetch_adaptive(fetch, date(2026, 1, 1), date(2026, 4, 30), policy))

    assert tamanos[0] == 40, "arrancó grande"
    assert tamanos[1] == 20, "redujo tras la falla"
    assert max(tamanos[2:]) > 20, "volvió a crecer al encadenar éxitos"


def test_nunca_baja_del_minimo_y_registra_el_tramo_perdido():
    """Si un día no entra, el problema no es el tamaño: se saltea y se avisa."""

    def fetch(desde, hasta):
        raise _timeout()

    report = WindowReport()
    policy = WindowPolicy(max_days=4, min_days=1)
    resultados = list(fetch_adaptive(fetch, date(2026, 1, 1), date(2026, 1, 3), policy, report=report))

    assert resultados == []
    assert report.has_gaps
    # Se avanzó día por día: hay un tramo perdido por cada día del rango.
    assert len(report.skipped_ranges) == 3
    assert all((fin - inicio).days == 0 for inicio, fin, _ in report.skipped_ranges)


def test_un_error_que_no_es_de_tamano_se_propaga():
    """Un 404 o un 401 no se resuelven troceando: que los vea el llamador."""

    def fetch(desde, hasta):
        raise _http_error(401)

    with pytest.raises(requests.HTTPError):
        list(fetch_adaptive(fetch, date(2026, 1, 1), date(2026, 1, 10), WindowPolicy(max_days=5)))


def test_rango_invertido_no_pide_nada():
    llamadas = []

    def fetch(desde, hasta):
        llamadas.append((desde, hasta))

    list(fetch_adaptive(fetch, date(2026, 2, 1), date(2026, 1, 1), WindowPolicy()))
    assert llamadas == []


def test_el_reporte_resume_lo_que_paso():
    def fetch(desde, hasta):
        return (hasta - desde).days + 1

    report = WindowReport()
    list(fetch_adaptive(fetch, date(2026, 1, 1), date(2026, 1, 20), WindowPolicy(max_days=10), report=report))

    resumen = report.summary()
    assert resumen["requests_ok"] == 2
    assert resumen["requests_failed"] == 0
    assert resumen["tramos_perdidos"] == []


def test_politica_invalida_falla_al_construirse():
    with pytest.raises(ValueError):
        WindowPolicy(max_days=5, min_days=10)
    with pytest.raises(ValueError):
        WindowPolicy(shrink_divisor=1.0)
