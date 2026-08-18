"""Metadata de raw: dos columnas, en todas las filas, siempre."""

from datetime import datetime

from ingestion.metadata import METADATA_COLUMN_HINTS, add_metadata


def test_agrega_ingested_at_y_source():
    enriquecer = add_metadata("frankfurter.tabla_x")
    fila = enriquecer({"rate": 1.5})

    assert fila["_source"] == "frankfurter.tabla_x"
    assert isinstance(fila["_ingested_at"], datetime)
    assert fila["_ingested_at"].tzinfo is not None, "_ingested_at tiene que ser UTC-aware"


def test_no_pisa_los_datos_de_negocio():
    fila = add_metadata("x")({"rate": 1.5, "quote_currency": "USD"})
    assert fila["rate"] == 1.5
    assert fila["quote_currency"] == "USD"


def test_los_hints_declaran_las_dos_columnas_como_not_null():
    """Si se crean nullable, una fila sin metadata pasa desapercibida."""
    assert set(METADATA_COLUMN_HINTS) == {"_ingested_at", "_source"}
    assert all(not h["nullable"] for h in METADATA_COLUMN_HINTS.values())
