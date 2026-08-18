"""Parámetros de carga del pipeline de Frankfurter.

Todo lo que hay que revisar al ajustar el pipeline está acá, y sale del entorno
(`.env.<entorno>`) para poder cambiarlo sin tocar código.
"""

from __future__ import annotations

from datetime import date

from shared.constants import RAW
from shared.settings import settings

RAW_SCHEMA = RAW

# Un pipeline de dlt POR RECURSO, no uno por fuente.
#
# El nombre del pipeline es la clave bajo la que dlt guarda su estado (el cursor
# incremental, el schema inferido). Tenerlos separados es lo que permite que cada
# recurso sea un ETL independiente: se programan distinto, fallan por separado y
# uno puede reprocesarse sin tocar el estado del otro.
#
# Cambiar estos nombres equivale a arrancar de cero: dlt no encuentra el estado
# viejo y el cursor vuelve a `history_start()`. No se pierde nada (el merge por
# clave natural es idempotente), pero la corrida siguiente re-pide el histórico.
PIPELINE_RATES = "frankfurter_rates"
PIPELINE_CURRENCIES = "frankfurter_currencies"

# Tablas raw que escribe cada pipeline.
TABLE_RATES = "raw_frankfurter_exchange_rates"
TABLE_CURRENCIES = "raw_frankfurter_currencies"

# Clave natural de las cotizaciones, con los nombres CRUDOS del origen: una fila por
# día, moneda base y moneda cotizada. Es la primary_key del merge, así que re-pedir
# un rango es idempotente.
RATES_PRIMARY_KEY = ("date", "base", "currency")

# Cursor incremental: la fecha de la cotización, con el nombre del origen.
CURSOR_COLUMN = "date"

# Catálogo de lo que este pipeline escribe en raw, con su clave natural y su cursor.
# Lo consume scripts/diagnose_raw.py para saber qué chequear sin hardcodear nada: si
# sumás una tabla, agregala acá.
RAW_TABLES: dict[str, dict[str, object]] = {
    TABLE_RATES: {"primary_key": RATES_PRIMARY_KEY, "cursor": CURSOR_COLUMN},
    TABLE_CURRENCIES: {"primary_key": ("code",), "cursor": None},
}

# Qué tabla es la "testigo" de cada pipeline: la que se consulta para saber si el
# recurso ya tiene datos en raw. Es lo que dispara la carga histórica automática
# (ver `runner.raw_is_empty`), y por eso vive acá y no hardcodeada en el runner.
PIPELINE_WITNESS_TABLE: dict[str, str] = {
    PIPELINE_RATES: TABLE_RATES,
    PIPELINE_CURRENCIES: TABLE_CURRENCIES,
}


def history_start() -> date:
    """Primer día del histórico. Piso de la carga inicial y de los reprocesos."""
    return date.fromisoformat(settings.FRANKFURTER_HISTORY_START)


def overlap_days() -> int:
    """Días que se re-piden hacia atrás en la corrida incremental de todos los días.

    Es el `lag` de `dlt.sources.incremental`: sin overlap, una cotización que el
    origen corrige después de publicarla no vuelve a entrar nunca.

    Dimensionado para la corrección "normal" del origen: el BCE republica un día
    ya publicado dentro de la misma semana. Para correcciones más viejas está el
    ETL de reconciliación, que usa `reconcile_overlap_days()`.
    """
    return settings.INGEST_OVERLAP_DAYS


def reconcile_overlap_days() -> int:
    """Días que re-pide el ETL de reconciliación.

    Por qué existe además del overlap corto: el overlap de la corrida diaria es un
    compromiso entre costo y cobertura. Si se lo estira a un año, todos los días se
    re-piden 365 días de datos que casi nunca cambian; si se lo deja en una semana,
    una corrección que el origen publica dos meses tarde no entra NUNCA y nadie se
    entera — el mismo agujero silencioso que motivó el ADR 0002, corrido de escala.

    La solución son dos cadencias sobre el mismo pipeline y el mismo cursor: una
    corrida barata todos los días con overlap corto, y una corrida de barrido con
    overlap largo. Las dos son idempotentes (merge por clave natural), así que la
    única diferencia es cuántos días se re-piden.
    """
    return settings.INGEST_RECONCILE_OVERLAP_DAYS


def window_max_days() -> int:
    """Ventana máxima que se le pide a la API de una sola vez.

    El troceado adaptativo arranca en este valor y lo baja solo si la API falla.
    """
    return settings.INGEST_WINDOW_MAX_DAYS
