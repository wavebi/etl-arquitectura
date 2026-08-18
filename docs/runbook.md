# Runbook — operación del ETL

Qué hacer cuando algo falla, ordenado por síntoma. La primera pregunta siempre es la
misma: **¿el pipeline corrió?** Si no corrió, no hay nada que depurar en el SQL.

## Diagnóstico inicial

```bash
# 1. ¿Corrió y cómo terminó?  → UI de Prefect: http://localhost:4210 (dev)
#    Filtrando por el deployment, muestra estado, duración y logs de cada corrida.

# 2. ¿Raw está sano y hasta dónde llegó?
make diagnose

# 3. ¿Los datos llegan hasta hoy?
make dbt CMD="source freshness"

# 4. ¿Hay tests de calidad en rojo?  (las filas que fallaron quedan en dbt_test_audit)
make dbt CMD="test"
```

---

## El tablero no tiene datos de hoy

1. UI de Prefect: si la última corrida exitosa es vieja o el deployment viene
   fallando, seguí en *"El flow falló"*.
2. Si corrió OK, mirá `dbt source freshness`: puede haber cargado sin traer nada
   (el origen no publicó todavía).
3. Con datos de referencia del BCE: **no publica fines de semana ni feriados
   europeos**. Un lunes a la mañana, el último dato es del viernes. No es una falla.
4. Si raw está fresco y el mart no, revisá si el `dbt_run` quedó en
   `failed_steps` (el flow puede terminar "degraded" y verse verde).
5. La herramienta de BI tiene su propio refresh: que el mart esté actualizado no
   significa que el tablero lo esté.

## El flow falló (Prefect rojo)

```bash
make logs                       # o el run en la UI de Prefect
```

| En el log | Qué pasa | Qué hacer |
|---|---|---|
| `Circuit breaker ... ABIERTO` | el origen está caído o degradado | esperar y re-disparar; si sigue, revisar el estado del servicio |
| `recorrido terminado — tramos_perdidos: [...]` | el origen no pudo servir ese rango ni con la ventana mínima | custom run de `frankfurter-rates` con date_from/date_to sobre ese rango |
| `dlt jobs failed` | falló la escritura en Postgres | revisar espacio en disco y locks sobre la tabla |
| `Fallo en ejecucion DBT` | error de SQL o de compilación | `make dbt CMD="build --select <modelo>"` para reproducir |
| `permission denied for schema` | faltan permisos del rol | re-correr `scripts/init_db_permissions.sql` |

## El flow terminó "degraded"

Terminó, pero algo no crítico falló (`failed_steps` en la notificación). Los marts
existentes siguen sirviendo. Casos típicos:

- `dbt_test` — un test de calidad en rojo. Mirá `dbt_test_audit`.
- `dbt_docs` — la documentación quedó desactualizada.
- `dbt_seed` — un CSV de seeds mal formado.

No es urgente, pero **no es normal**: si se repite, o se arregla o se cambia la
clasificación del paso para que refleje la realidad.

## Raw quedó con un agujero histórico

Síntoma: `make diagnose` muestra que la tabla arranca mucho después de lo esperado,
o que le faltan meses en el medio.

Causa más común: el estado de dlt (que vive también en `.dlt/` local) quedó
desincronizado con la base, y una corrida incremental pidió solo la última semana.
El pipeline ya se defiende de esto (si raw está vacío fuerza el histórico), pero
no puede detectar un hueco *en el medio*.

```bash
# Rellenar un tramo puntual, sin mover el cursor de la carga diaria:
make sh
python -c "
from ingestion.pipelines.frankfurter.runner import run_rates_pipeline
print(run_rates_pipeline(date_from='2015-01-01', date_to='2015-12-31'))
"

# O desde la UI: custom run de `frankfurter-rates` con date_from y date_to.
```

Si el hueco es reciente pero no se sabe exactamente dónde, alcanza con barrer hacia
atrás sin fijar el rango — la reconciliación re-pide y el merge corrige:

```bash
make ingest-reconcile OVERLAP=3650      # diez años
# O desde la UI: custom run de `frankfurter-rates-reconcile` con overlap=3650.
```

Si el agujero es grande o arranca antes de eso, es más barato recargar todo:
custom run de `frankfurter-rates` con `full_refresh=true` (descarta raw y lo reconstruye).

## Un mart muestra valores duplicados o al doble

Casi siempre es la clave natural: el `primary_key` del resource no identifica de
verdad a la fila, así que el merge inserta en vez de pisar.

```bash
make diagnose                   # detecta duplicados por clave natural
```

Si hay duplicados:

1. Comparar dos filas duplicadas y encontrar qué campo difiere.
2. Corregir el `primary_key` del resource (o los campos que forman el `_row_id`,
   si la fuente no tiene clave natural).
3. Recargar la tabla afectada: los duplicados viejos no se van solos.
4. Correr el pipeline **dos veces** y verificar que la cantidad de filas no cambia.

## El server de Prefect no arranca

Dos causas conocidas, las dos con solución documentada:

| Error | Causa | Solución |
|---|---|---|
| `permission denied for schema public` | el rol de Prefect no tiene su `search_path` | `ALTER ROLE prefect_app SET search_path = prefect, public;` |
| `operator class "gin_trgm_ops" does not exist` | `pg_trgm` está en `public` y no es visible | mismo `search_path` (tiene que incluir `public`) |
| `cannot drop column ... because other objects depend on it` | hay una VISTA de dbt sobre las tablas de Prefect | ver [ADR 0003](adr/0003-modelos-sobre-prefect-como-tabla.md): esos modelos van como tabla |

Las tres las deja resueltas `scripts/init_db_permissions.sql`; aparecen si se corrió
una versión vieja del script.

## Recuperar el entorno local

```bash
make reset-db          # ⚠️ borra el volumen de Postgres y reaplica schemas/roles
make up
make ingest            # recarga (detecta raw vacío ⇒ histórico completo)
make dbt-build
```

## Runs zombie en Prefect

Si el worker se reinició en medio de un run, quedan runs en `RUNNING` que nadie está
ejecutando. El `entrypoint.sh` los cancela en cada arranque; para hacerlo a mano:

```bash
make sh
python /app/src/orchestration/cancel_stale_runs.py
```

## La documentación de dbt muestra un linaje viejo

`dbt docs` sirve archivos estáticos: hay que regenerarlos después de cambiar modelos.

```bash
make dbt-docs          # regenera el catálogo y reinicia el servidor
```
