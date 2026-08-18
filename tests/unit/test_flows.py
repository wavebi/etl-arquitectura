"""Política grave/leve y armado del resultado de los flows."""

import pytest

from shared.utils.orchestration import finalize_flow


def test_sin_fallas_devuelve_ok():
    result = finalize_flow("f", {"ingest": 1}, [], grave_steps=("ingest",))
    assert result["status"] == "ok"
    assert result["failed_steps"] == []


def test_falla_leve_devuelve_degraded():
    """Una documentación desactualizada avisa, pero no invalida lo que ya se cargó."""
    result = finalize_flow("f", {}, ["dbt_docs"], grave_steps=("ingest", "dbt_build"))
    assert result["status"] == "degraded"
    assert result["failed_steps"] == ["dbt_docs"]


def test_falla_grave_rompe_el_flow():
    with pytest.raises(RuntimeError, match="dbt_build"):
        finalize_flow("f", {}, ["dbt_build", "dbt_docs"], grave_steps=("dbt_build",))


def test_el_error_grave_menciona_tambien_los_leves():
    with pytest.raises(RuntimeError) as exc:
        finalize_flow("f", {}, ["ingest", "dbt_docs"], grave_steps=("ingest",))
    assert "dbt_docs" in str(exc.value)


def test_la_documentacion_del_flow_declara_los_pasos_graves():
    """Si alguien agrega un paso al flow, tiene que decidir si es grave o leve."""
    from orchestration.flows import etl_flows

    assert "ingest" in etl_flows.GRAVE_STEPS
    assert "dbt_build" in etl_flows.GRAVE_STEPS
    # Los pasos informativos NO son graves: no deben teñir de rojo la corrida.
    assert "dbt_docs" not in etl_flows.GRAVE_STEPS


# ---------------------------------------------------------------------------
# Forma de los ETLs — un ETL por recurso
# ---------------------------------------------------------------------------


def _params(flow):
    """Nombres de los parámetros de un flow de Prefect."""
    import inspect

    return set(inspect.signature(flow.fn).parameters)


def test_hay_un_etl_por_recurso_mas_la_reconciliacion():
    from orchestration.flows import etl_flows

    assert etl_flows.frankfurter_currencies_flow
    assert etl_flows.frankfurter_rates_flow
    assert etl_flows.frankfurter_rates_reconcile_flow


def test_el_etl_de_monedas_no_expone_parametros_de_fecha():
    """`/currencies` es una foto del presente e ignora cualquier fecha.

    Verificado contra la API el 2026-08-18: el payload de `/currencies?date=...`
    es idéntico al de `/currencies`. Exponer date_from/date_to/overlap acá sería
    prometer un reproceso histórico que el origen no puede dar.
    """
    from orchestration.flows import etl_flows

    params = _params(etl_flows.frankfurter_currencies_flow)
    assert not params & {"date_from", "date_to", "overlap"}


def test_los_etls_de_cotizaciones_permiten_rango_y_overlap():
    """Los tres modos que pide la operación: incremental, rango forzado, overlap."""
    from orchestration.flows import etl_flows

    rates = _params(etl_flows.frankfurter_rates_flow)
    assert {"date_from", "date_to", "full_refresh", "overlap"} <= rates

    # La reconciliación es la misma ingesta con otro overlap: no necesita rango.
    reconcile = _params(etl_flows.frankfurter_rates_reconcile_flow)
    assert "overlap" in reconcile


def test_los_overlaps_salen_del_entorno_y_el_largo_es_mayor():
    """No hardcodeados: son política operativa, se cambian sin deploy."""
    from shared.settings import settings

    assert settings.INGEST_OVERLAP_DAYS > 0
    assert settings.INGEST_RECONCILE_OVERLAP_DAYS > settings.INGEST_OVERLAP_DAYS
