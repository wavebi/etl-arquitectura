"""El pipeline completo contra un Postgres real, con la API mockeada.

Cubre lo que no se puede verificar con mocks puros: que el merge por clave natural
sea idempotente, que los tipos declarados lleguen a la tabla y que la carga
histórica se dispare cuando raw está vacío.
"""

import pytest

pytestmark = pytest.mark.integration

# El fake devuelve el payload con la forma exacta del origen.
RATES_PAYLOAD = {
    "amount": 1.0,
    "base": "EUR",
    "rates": {
        "2026-01-02": {"USD": 1.17, "BRL": 6.37},
        "2026-01-05": {"USD": 1.16, "BRL": 6.34},
    },
}
CURRENCIES = {"USD": "United States Dollar", "BRL": "Brazilian Real"}


@pytest.fixture
def fake_api(monkeypatch):
    """Reemplaza al cliente HTTP: devuelve datos fijos sin salir a la red."""
    from ingestion.sources.frankfurter import client as client_module

    calls: list[tuple] = []

    class _FakeClient:
        base_currency = "EUR"

        def __init__(self, *args, **kwargs):
            pass

        def get_currencies(self):
            return CURRENCIES

        def get_rates(self, date_from, date_to, symbols=()):
            calls.append((date_from, date_to))
            return {**RATES_PAYLOAD, "rates": dict(RATES_PAYLOAD["rates"])}

    monkeypatch.setattr(client_module, "FrankfurterClient", _FakeClient)
    import ingestion.pipelines.frankfurter.resources as resources_module

    monkeypatch.setattr(resources_module, "FrankfurterClient", _FakeClient)
    return calls


def _run(**kwargs):
    """Corre el ETL de cotizaciones."""
    from ingestion.pipelines.frankfurter.runner import run_rates_pipeline

    return run_rates_pipeline(**kwargs)


def _run_currencies(**kwargs):
    """Corre el ETL del catálogo, que es un pipeline de dlt aparte."""
    from ingestion.pipelines.frankfurter.runner import run_currencies_pipeline

    return run_currencies_pipeline(**kwargs)


def test_carga_las_cotizaciones_con_metadata_y_tipos(local_raw, fake_api, query):
    _run(date_from="2026-01-01", date_to="2026-01-31")

    filas = query('select * from raw.raw_frankfurter_exchange_rates order by "date", "currency"')
    assert len(filas) == 4
    assert {f["currency"] for f in filas} == {"USD", "BRL"}
    assert all(f["base"] == "EUR" for f in filas)
    assert all(f["_source"].startswith("frankfurter.") for f in filas)
    assert all(f["_ingested_at"] is not None for f in filas)

    tipos = query(
        """
        select column_name, data_type from information_schema.columns
        where table_schema = 'raw' and table_name = 'raw_frankfurter_exchange_rates'
        """
    )
    por_columna = {t["column_name"]: t["data_type"] for t in tipos}
    assert por_columna["date"] == "date", "el cursor tiene que ser date, no texto"
    assert por_columna["rate"] == "numeric"


def test_correr_dos_veces_no_duplica(local_raw, fake_api, query):
    """El invariante que hace seguros el overlap y los reprocesos."""
    _run(date_from="2026-01-01", date_to="2026-01-31")
    _run(date_from="2026-01-01", date_to="2026-01-31")

    filas = query("select count(*) as n from raw.raw_frankfurter_exchange_rates")
    assert filas[0]["n"] == 4


def test_un_valor_corregido_en_el_origen_actualiza_la_fila(local_raw, fake_api, query):
    _run(date_from="2026-01-01", date_to="2026-01-31")

    RATES_PAYLOAD["rates"]["2026-01-02"]["USD"] = 9.99
    try:
        _run(date_from="2026-01-01", date_to="2026-01-31")
        filas = query(
            """
            select rate from raw.raw_frankfurter_exchange_rates
            where "date" = %s and "currency" = %s
            """,
            ("2026-01-02", "USD"),
        )
        assert len(filas) == 1
        assert float(filas[0]["rate"]) == 9.99
    finally:
        RATES_PAYLOAD["rates"]["2026-01-02"]["USD"] = 1.17


def test_el_catalogo_de_monedas_se_reemplaza_completo(local_raw, fake_api, query):
    """El catálogo es su propio ETL: corre solo, sin tocar las cotizaciones."""
    _run_currencies()
    _run_currencies()  # `replace`: la segunda corrida reemplaza, no acumula.

    filas = query("select count(*) as n from raw.raw_frankfurter_currencies")
    assert filas[0]["n"] == len(CURRENCIES)


def test_los_dos_etls_son_independientes(local_raw, fake_api, query):
    """Cada recurso tiene su pipeline de dlt: cargar uno no crea la tabla del otro.

    Es lo que permite programarlos y reprocesarlos por separado.
    """
    _run_currencies()

    existe_rates = query(
        """
        select 1 from information_schema.tables
        where table_schema = 'raw' and table_name = 'raw_frankfurter_exchange_rates'
        """
    )
    assert not existe_rates, "el ETL de monedas no debe tocar la tabla de cotizaciones"


def test_el_overlap_se_puede_pisar_por_parametro(local_raw, fake_api, query):
    """Lo que distingue al ETL de reconciliación del diario es este parámetro.

    Con datos ya cargados hasta el 2026-01-05, un overlap de 365 días tiene que
    hacer que la ventana arranque bastante antes que con el overlap por defecto.
    """
    _run(date_from="2026-01-01", date_to="2026-01-31")

    fake_api.clear()
    _run(overlap=365)

    assert fake_api, "la reconciliación tuvo que pedirle datos a la API"
    desde_reconcile = min(desde for desde, _ in fake_api)

    fake_api.clear()
    _run(overlap=0)
    desde_sin_overlap = min(desde for desde, _ in fake_api)

    assert desde_reconcile < desde_sin_overlap, (
        f"overlap=365 tiene que arrancar antes que overlap=0 ({desde_reconcile} vs {desde_sin_overlap})"
    )


def test_raw_vacio_dispara_la_carga_historica(local_raw, fake_api, query):
    """Aunque dlt tenga estado local diciendo que ya cargó, si la base está vacía
    hay que traer el histórico: la base es la fuente de verdad."""
    from datetime import date

    from ingestion.pipelines.frankfurter.constants import history_start

    _run()  # sin argumentos: incremental → debería detectar raw vacío

    pedidos = fake_api
    assert pedidos, "tuvo que pedirle datos a la API"
    primer_desde = min(desde for desde, _ in pedidos)
    assert primer_desde == history_start(), (
        f"con raw vacío la ventana tiene que arrancar en el inicio del histórico, arrancó en {primer_desde}"
    )
    assert primer_desde < date.today()
