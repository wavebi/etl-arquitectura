"""Constantes compartidas: capas del warehouse y naming de tablas.

Los nombres de schema tienen que coincidir con los `+schema` de `dbt_project.yml`
y con los `CREATE SCHEMA` de `scripts/init_db_permissions.sql`.
"""

# Capas del warehouse (schemas de PostgreSQL)
RAW = "raw"  # crudo, exactamente como llegó del origen (lo escribe dlt)
STAGING = "staging"  # views 1:1 con raw: tipado y renombre al español
INTERMEDIATE = "intermediate"  # ephemeral: NO crea objetos en la base
MARTS = "marts"  # tablas finales que consume BI (modelo dimensional)
SCD2 = "scd2"  # historia de los atributos que el origen pisa (SCD Type 2)
SEEDS = "seeds"  # CSVs versionados en el repo

# Schemas que existen físicamente en la base. `intermediate` NO está: sus modelos
# son ephemeral (dbt los inlinea en quien los consume) y el schema quedaría vacío.
# Si alguna vez un intermediate se materializa como tabla, dbt crea el schema solo
# (etl_app tiene CREATE sobre la base).
PHYSICAL_SCHEMAS = [RAW, STAGING, MARTS, SCD2, SEEDS]

# Metadata que agrega la capa de ingesta a TODA tabla raw. Ver ingestion/metadata.py.
INGESTED_AT = "_ingested_at"  # cuándo se cargó la fila (hora Argentina)
SOURCE = "_source"  # de qué fuente y recurso vino

METADATA_COLUMNS = (INGESTED_AT, SOURCE)


def raw_table_name(source: str, resource: str) -> str:
    """Nombre canónico de una tabla raw: `raw_{fuente}_{recurso}`.

    >>> raw_table_name("frankfurter", "exchange_rates")
    'raw_frankfurter_exchange_rates'
    """
    return f"raw_{source}_{resource}"
