# ADR 0002 — El incremental y la ventana de overlap los resuelve dlt

- **Fecha:** 2026-08-18
- **Estado:** aceptado
- **Contexto:** capa de ingesta (`ingestion/pipelines/*/resources.py`)

## Contexto

Los recursos que son series temporales se cargan con `write_disposition="merge"` y
clave natural, sobre una ventana de fechas que incluye un **overlap** hacia atrás.
El overlap existe por una razón concreta: el origen puede CORREGIR un dato ya
publicado (el BCE revisa cotizaciones), y una ventana que arranque en
`max(fecha) + 1` no volvería a mirar nunca ese día.

La primera versión de esta arquitectura implementaba el incremental a mano: una
función consultaba `max(fecha)` en raw, le restaba el overlap y armaba el rango.
Se descartó `dlt.sources.incremental` tras comprobar que descartaba las filas con
fecha anterior al último valor visto — es decir, justo las que el overlap busca.

**Esa conclusión estaba incompleta.** El comportamiento observado era el de
`dlt.sources.incremental` SIN configurar la ventana de atribución. dlt tiene dos
parámetros para exactamente este caso:

- `lag=N` — corre el inicio de la ventana N unidades hacia atrás desde el último
  valor guardado (para un cursor con fechas ISO, N son días);
- `range_start="closed"` — incluye las filas con el mismo valor de cursor que el
  último visto y activa la deduplicación por `primary_key`.

## Decisión

Usar `dlt.sources.incremental(cursor, initial_value=..., lag=OVERLAP, range_start="closed")`
y eliminar el cálculo propio del rango.

El recurso lee `incremental.start_value` (que ya viene con el `lag` aplicado) para
construir la llamada al origen: dlt decide QUÉ ventana, nosotros sabemos CÓMO
pedirla.

Se conserva una sola cosa propia: el chequeo de "raw vacío ⇒ carga histórica"
(ver `runner.raw_is_empty`), porque el estado de dlt vive también en su
directorio local y puede quedar desincronizado con la base.

## Consecuencias

**A favor**

- Menos código propio: se eliminó el módulo que consultaba `max(fecha)` y calculaba
  rangos, con sus casos borde.
- El estado lo persiste dlt en el destino, así que sobrevive al reinicio del
  contenedor y es consultable con SQL.
- La deduplicación por clave dentro de la ventana de overlap la hace dlt.
- `end_value` da backfills *stateless*: reprocesar un tramo viejo no mueve el
  cursor de la carga diaria.

**En contra**

- Hay que conocer la semántica de `lag` / `range_start`, que no es obvia y que la
  documentación de dlt explica de pasada. Un `lag` ausente pasa desapercibido y se
  manifiesta como datos faltantes, no como error.
- El estado de dlt es una segunda fuente de verdad además de los datos.

**Mitigaciones**

- `tests/integration/test_incremental_lag.py` fija el comportamiento con tests
  contra un Postgres real: sin `lag` la fila vieja se descarta, con `lag` entra, y
  el `lag` se cuenta en días para cursores de fecha. Si alguien "simplifica" la
  configuración, esos tests fallan.
- `raw_is_empty()` cubre la desincronización del estado local.

## Nota

Este ADR reemplaza a una versión anterior que concluía lo contrario ("no usar
`dlt.sources.incremental`"). Se deja registrado el cambio de decisión, no se borra:
la conclusión vieja era razonable con la evidencia que había, y saber por qué se
revirtió evita volver a la implementación manual.
