"""Metadata de trazabilidad que se agrega a toda tabla raw.

Dos columnas, en todas las filas, sin importar la fuente:

    _ingested_at   cuándo se cargó, en hora de Argentina. Habilita
                   `dbt source freshness`: sin esto, un raw que dejó de
                   actualizarse se ve idéntico a uno al día y los marts mienten
                   sin dar ningún error.
    _source        de qué fuente y recurso vino la fila. Es lo que permite
                   responder "¿de dónde salió este número?" desde un mart.

Son las ÚNICAS columnas que la ingesta agrega. El resto de la tabla raw tiene los
nombres exactos del origen: el renombre (y el pasaje al español) es trabajo de la
capa de staging.

Sobre claves y deduplicación: la unicidad NO se resuelve acá. Se declara en el
`@dlt.resource` con `primary_key=(...)` usando la clave natural del origen, y dlt
hace el UPSERT. Cuando el origen no tiene clave natural, el patrón es agregar una
columna `_row_id = sha256(campos_de_negocio)` — ver docs/agregar_una_fuente.md.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from shared.settings import settings

if TYPE_CHECKING:
    from collections.abc import Callable

# Hints de dlt para que las columnas de metadata se creen con el tipo correcto y
# NOT NULL, en lugar de inferirse del primer lote.
METADATA_COLUMN_HINTS: dict[str, dict[str, Any]] = {
    "_ingested_at": {"data_type": "timestamp", "nullable": False},
    "_source": {"data_type": "text", "nullable": False},
}


def now_local() -> datetime:
    """Momento actual en la zona horaria del proyecto (hora Argentina).

    Se usa una fecha *aware*, no naive: el valor se guarda como `timestamptz` (un
    instante absoluto) y la base —configurada en la misma zona— lo muestra en hora
    local. Con una fecha naive, el mismo instante se leería distinto según dónde
    corra el proceso.
    """
    return datetime.now(ZoneInfo(settings.TIMEZONE))


def add_metadata(source: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Devuelve una función `map` para `@dlt.resource(...).add_map(...)`.

    Args:
        source: identificador de la fuente y el recurso (p. ej. "frankfurter.rates").
    """

    def _add(record: dict[str, Any]) -> dict[str, Any]:
        record["_ingested_at"] = now_local()
        record["_source"] = source
        return record

    return _add
