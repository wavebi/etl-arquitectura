"""Semántica del incremental de dlt — el mecanismo del que depende la ingesta.

Estos tests existen porque el comportamiento NO es obvio y una equivocación no da
error: la tabla parece cargar bien todos los días mientras pierde correcciones del
origen. Fijan tres cosas verificadas contra dlt 1.30 y Postgres real:

    1. Sin `lag`, una fila con fecha anterior al último valor visto se DESCARTA.
    2. Con `lag=N` y `range_start="closed"`, las filas dentro de esa ventana
       vuelven a entrar y ACTUALIZAN (es la ventana de overlap del pipeline).
    3. Con `end_value`, el filtrado es stateless: un backfill acotado no mueve el
       cursor de la carga incremental.

Si alguien "simplifica" el incremental, estos tests son los que avisan.
"""

from typing import Any

import dlt
import pytest

pytestmark = pytest.mark.integration

TABLE = "test_incremental_rates"
PRIMARY_KEY = ("rate_date", "quote_currency")


def _resource(rows: list[dict[str, Any]], **incremental_kwargs: Any):
    @dlt.resource(name=TABLE, write_disposition="merge", primary_key=PRIMARY_KEY)
    def rates(
        cursor: Any = dlt.sources.incremental(
            "rate_date",
            primary_key=PRIMARY_KEY,
            **incremental_kwargs,
        ),
    ):
        _ = cursor
        yield from rows

    return rates()


def _run(pipeline_name: str, rows: list[dict[str, Any]], **incremental_kwargs: Any):
    from shared.utils.warehouse import get_destination

    pipeline = dlt.pipeline(
        pipeline_name=pipeline_name,
        destination=get_destination(),
        dataset_name="raw",
    )
    info = pipeline.run(_resource(rows, **incremental_kwargs))
    assert not info.has_failed_jobs, info
    return pipeline


PRIMERA_CARGA = [
    {"rate_date": "2026-01-10", "quote_currency": "USD", "rate": 1.0},
    {"rate_date": "2026-02-10", "quote_currency": "USD", "rate": 2.0},
]


def test_sin_lag_una_fila_vieja_se_descarta(query, tmp_path):
    """El comportamiento por defecto: el cursor no vuelve a mirar el pasado."""
    _run("test_inc_sin_lag", PRIMERA_CARGA, initial_value="2026-01-01")
    _run(
        "test_inc_sin_lag",
        [{"rate_date": "2026-01-10", "quote_currency": "USD", "rate": 99.0}],
        initial_value="2026-01-01",
    )

    filas = query(f'select rate from raw."{TABLE}" where rate_date = %s', ("2026-01-10",))
    assert [f["rate"] for f in filas] == [1.0], "sin lag, la corrección NO entra"


def test_con_lag_la_fila_dentro_de_la_ventana_actualiza(query, tmp_path):
    """Con overlap de 30 días, una corrección de hace 5 días sí entra.

    Es la razón por la que el pipeline usa `lag`: el BCE puede revisar una
    cotización ya publicada.
    """
    _run("test_inc_con_lag", PRIMERA_CARGA, initial_value="2026-01-01", lag=30, range_start="closed")
    _run(
        "test_inc_con_lag",
        [{"rate_date": "2026-02-05", "quote_currency": "USD", "rate": 55.0}],
        initial_value="2026-01-01",
        lag=30,
        range_start="closed",
    )

    filas = query(f'select rate from raw."{TABLE}" where rate_date = %s', ("2026-02-05",))
    assert [f["rate"] for f in filas] == [55.0], "con lag, la fila dentro de la ventana entra"


def test_el_lag_se_cuenta_en_dias_para_cursores_de_fecha(query, tmp_path):
    """Verifica el detalle que la documentación de dlt no explicita: para un cursor
    con fechas ISO en texto, `lag` se interpreta en DÍAS."""
    starts: list[str] = []

    @dlt.resource(name=TABLE, write_disposition="merge", primary_key=PRIMARY_KEY)
    def rates(
        cursor: Any = dlt.sources.incremental(
            "rate_date",
            initial_value="2026-01-01",
            lag=30,
            range_start="closed",
            primary_key=PRIMARY_KEY,
        ),
    ):
        starts.append(str(cursor.start_value))
        yield from PRIMERA_CARGA

    from shared.utils.warehouse import get_destination

    for _ in range(2):
        pipeline = dlt.pipeline(
            pipeline_name="test_inc_lag_dias",
            destination=get_destination(),
            dataset_name="raw",
        )
        pipeline.run(rates())

    # Primera corrida: arranca en initial_value. Segunda: max(fecha) - 30 días.
    assert starts[0] == "2026-01-01"
    assert starts[1] == "2026-01-11", f"esperaba 2026-02-10 menos 30 días, obtuve {starts[1]}"


def test_un_backfill_con_end_value_no_mueve_el_cursor(query, tmp_path):
    """Permite reprocesar un tramo viejo sin alterar la carga incremental."""
    starts: list[str] = []

    from shared.utils.warehouse import get_destination

    def build(initial: str, end: str | None):
        @dlt.resource(name=TABLE, write_disposition="merge", primary_key=PRIMARY_KEY)
        def rates(
            cursor: Any = dlt.sources.incremental(
                "rate_date",
                initial_value=initial,
                end_value=end,
                range_start="closed",
                primary_key=PRIMARY_KEY,
            ),
        ):
            starts.append(str(cursor.start_value))
            yield from PRIMERA_CARGA

        return rates()

    pipeline = dlt.pipeline(
        pipeline_name="test_inc_backfill",
        destination=get_destination(),
        dataset_name="raw",
    )
    pipeline.run(build("2026-01-01", None))  # carga normal: mueve el cursor
    pipeline.run(build("2020-01-01", "2020-12-31"))  # backfill acotado
    pipeline.run(build("2026-01-01", None))  # otra vez normal

    # La tercera corrida arranca del cursor que dejó la PRIMERA, no del backfill.
    assert starts[2] >= "2026-01-01", f"el backfill movió el cursor: {starts}"
