# Arquitectura

Este documento explica **cómo está armado el ETL y por qué**. Si vas a tocar código,
leelo antes: casi todas las decisiones tienen una razón concreta (algo que se rompió
al construirlo) y revertirlas sin saberla sale caro.

## 1. Las cuatro capas

```
src/
├── ingestion/       origen → raw             dlt + cliente propio
├── orchestration/   cuándo y en qué orden    Prefect 3
├── dbt/             raw → marts              dbt (modelo dimensional Kimball)
└── shared/          settings, logging, notificaciones, conexión, resiliencia
```

Regla de dependencias (si se rompe, el proyecto se vuelve una bola de barro):

```
orchestration ──▶ ingestion ──▶ shared
      │                            ▲
      └──────────▶ dbt/ ───────────┘     (dbt se invoca por CLI, no se importa)
```

- `shared/` no importa nada del proyecto. Es la base.
- `ingestion/` no sabe que existe Prefect. Un pipeline se puede correr con
  `python -c "from ingestion.pipelines...runner import run_rates_pipeline; ..."`.
- `orchestration/` no tiene lógica de ingesta ni SQL: solo coordina y decide qué
  falla grave y qué falla leve.
- Nadie importa `dbt/`: es un proyecto dbt que se invoca por CLI.

## 2. Qué delegamos y qué escribimos

La regla es delegar todo lo que exista como librería probada, y escribir solo lo que
no existe. Vale la pena tenerlo explícito, porque lo delegado no se mantiene:

| Responsabilidad | Quién |
|---|---|
| Retry con backoff exponencial y jitter | dlt (`sources.helpers.requests`) |
| Respetar `Retry-After`, timeouts, límites de conexión | dlt, configurable por `RUNTIME__*` |
| Paginación (offset, page, cursor, link) | dlt (`rest_client` paginators) |
| Autenticación (OAuth2 client credentials, API key, JWT) | dlt (`rest_client.auth`) |
| Estado incremental + ventana de overlap (`lag`) | dlt (`sources.incremental`) |
| UPSERT por clave, evolución de schema | dlt (`write_disposition="merge"`) |
| **Troceado adaptativo de la ventana** | **nuestro** ([ADR 0004](adr/0004-troceado-adaptativo-propio.md)) |
| **Circuit breaker** | **nuestro**, sobre `pybreaker` |
| **Traducción de las respuestas raras del origen** | **nuestro** (el cliente) |
| **Carga histórica si raw está vacío** | **nuestro** (el runner) |

Consecuencia práctica: el cliente de una fuente nueva son ~100 líneas, no 400.

## 3. Ingesta: `sources/` vs `pipelines/`

La división más importante del repo, y la que hace mecánico sumar una fuente:

| | `sources/<fuente>/` | `pipelines/<fuente>/` |
|---|---|---|
| Responde | ¿cómo hablo con el origen? | ¿cómo lo guardo en raw? |
| Contiene | transporte, auth, paginación, traducción de errores | `@dlt.resource`, replace/merge, cursor, troceado |
| Conoce dlt | solo sus helpers HTTP | sí, entero |
| Devuelve | datos crudos | nada: escribe en la base |

Los datos crudos se guardan **sin transformar**: sin renombrar campos, sin castear
tipos, sin filtrar filas. Raw es la única copia de lo que dijo el origen; si
transformamos al ingerir y la regla estaba mal, hay que volver a pedirle todo al
cliente (lento, y a veces imposible).

Eso incluye los **nombres de las columnas**: dlt corre con la convención `direct`, que
desactiva su normalización a `snake_case`. Si la API devuelve `FechaEmisión`, en raw
hay una columna `FechaEmisión`. Contrapartida asumida: los identificadores del origen
suelen necesitar comillas en el SQL de staging. Ver
[ADR 0005](adr/0005-raw-conserva-los-nombres-del-origen.md).

La única excepción admitida es **aplanar** una respuesta anidada cuyo shape dependa
de los datos — como `{"rates": {fecha: {moneda: valor}}}`, donde una columna por
moneda haría mutar el schema cada vez que el origen agrega una.

### Metadata de raw

Toda fila lleva `_ingested_at` y `_source` (ver `ingestion/metadata.py`). La primera
habilita `dbt source freshness`; la segunda permite responder "¿de dónde salió este
número?" desde un mart.

La unicidad NO se resuelve con metadata: se declara en el resource con
`primary_key=(...)` usando la clave natural del origen. Cuando el origen no tiene
clave natural, el patrón es agregar `_row_id = sha256(campos_de_negocio)` — ver
[agregar_una_fuente.md](agregar_una_fuente.md).

## 4. Estrategias de carga

| Estrategia | Cuándo | Ejemplo |
|---|---|---|
| `replace` | el recurso es una foto del presente | catálogos, maestros, saldos |
| `merge` | serie temporal o transaccional | cotizaciones, facturas, asientos |
| `append` | el origen garantiza que nunca reenvía una fila | logs de eventos (raro) |

`append` casi nunca es la respuesta: si el origen reenvía algo, raw duplica sin
aviso. Ante la duda, `merge`.

### Incremental: ventana, overlap y carga histórica

Una carga incremental ingenua arranca en `max(fecha) + 1`. El problema real es que
los orígenes **corrigen** datos ya publicados; ese registro corregido quedaría
afuera para siempre.

Por eso el cursor se configura con `lag`:

```python
dlt.sources.incremental("rate_date", initial_value=HISTORY_START,
                        lag=OVERLAP_DAYS, range_start="closed")
```

- `lag` corre el inicio de la ventana N días hacia atrás desde el último valor visto;
- `range_start="closed"` deja pasar las filas repetidas y las deduplica por clave;
- el merge por clave natural hace que re-pedir sea idempotente.

Las tres piezas van juntas: sacar una rompe las otras dos. Está fijado con tests en
`tests/integration/test_incremental_lag.py` y explicado en
[ADR 0002](adr/0002-incremental-con-lag-de-dlt.md).

**Carga histórica.** Hay tres formas de pedirla, y las tres existen por un motivo:

1. *Automática*: si raw está vacío, el runner fuerza el histórico. Hace falta
   porque dlt guarda su estado también en un directorio local, que puede sobrevivir
   a un borrado de la base; sin este chequeo el pipeline pediría solo la ventana
   incremental y raw quedaría con una semana de datos y años de agujero, **sin
   ningún error**.
2. *Forzada*: `full_refresh=True` (custom run de `frankfurter-rates` desde la UI)
   descarta las tablas y el estado y recarga todo.
3. *Acotada*: `date_from`/`date_to` reprocesan un tramo sin mover el cursor de la
   carga diaria (`end_value` hace el filtrado stateless).

**Dos cadencias de overlap.** El `lag` de la corrida diaria es un compromiso: si se
lo estira a un año, todos los días se re-piden 365 días que casi nunca cambian; si
se lo deja en una semana, una corrección que el origen publica dos meses tarde no
entra nunca — el agujero del ADR 0002, corrido de escala. Por eso hay dos ETLs sobre
el mismo pipeline y el mismo cursor, que se diferencian solo en cuánto re-piden:

| ETL | Overlap | Cadencia |
|---|---|---|
| `frankfurter-rates` | `INGEST_OVERLAP_DAYS` (7) | días hábiles, tras la publicación |
| `frankfurter-rates-reconcile` | `INGEST_RECONCILE_OVERLAP_DAYS` (365) | todos los días, de madrugada |

Los dos son idempotentes (merge por clave natural), así que correrlos el mismo día
no duplica nada. Los valores viven en `.env`, no en el código: son política
operativa y se cambian sin deploy.

### Un ETL por recurso, no uno por fuente

Cada recurso del origen tiene su propio pipeline de dlt (`frankfurter_rates`,
`frankfurter_currencies`), y por lo tanto su propio estado, su propio cursor y su
propio flow. Eso es lo que permite programarlos distinto, que fallen por separado
—si la API rompe el catálogo, las cotizaciones siguen entrando— y reprocesar uno
sin tocar el estado del otro. El costo es un pipeline más que mirar en `.dlt/`.

Lo que NO se hace es clonar el mismo juego de parámetros para todo recurso porque
sí. `/currencies` no tiene eje temporal: devuelve una foto del presente e ignora
cualquier fecha que se le pase (verificado el 2026-08-18, el payload de
`/currencies?date=1999-01-04` es idéntico al de `/currencies`). Así que su ETL no
expone `date_from`, `date_to` ni `overlap`, y no tiene reconciliación: sería el
mismo request otra vez. Las monedas que el BCE ya no publica se recuperan de las
cotizaciones, no del catálogo.

### Troceado adaptativo

Pedir 27 años de una vez termina en timeout; pedir de a un día son 10.000 requests.
El troceado arranca con la ventana máxima, la **divide** cuando el origen falla con
un error de tamaño y la vuelve a **agrandar** tras varios tramos exitosos (AIMD, el
esquema de congestión de TCP). Si un tramo del tamaño mínimo sigue fallando, se
registra como perdido y se sigue: el ETL no se cuelga por un día que el origen no
puede servir. Detalle y alternativas evaluadas en
[ADR 0004](adr/0004-troceado-adaptativo-propio.md).

### Resiliencia: tres capas distintas

Se confunden seguido, y cada una resuelve otra cosa:

| Capa | Qué cubre | Dónde |
|---|---|---|
| Retry | falla puntual de un request (timeout, 5xx, 429) | dlt, por config |
| Troceado adaptativo | "pediste demasiado de una vez" | `chunking.py` |
| Circuit breaker | el origen está caído: dejar de insistir | `shared/utils/resilience.py` |

Los 4xx no abren el breaker: son problemas nuestros de configuración o permisos, no
del origen.

## 5. Orquestación

```
task    unidad que tiene sentido reintentar y observar por separado
flow    coordina tasks, decide qué es grave y qué es leve
deploy  el flow + cuándo corre (schedule) + con qué parámetros
```

Los flows **no cortan en el primer error**: cada paso corre en su propio
`try/except`, se acumula qué falló y al final `finalize_flow` aplica la política:

- falló un paso **grave** → `RuntimeError` ⇒ Prefect rojo + Telegram urgente;
- solo fallaron **leves** → `status: "degraded"` ⇒ Prefect verde + warning;
- nada falló → `status: "ok"` ⇒ notificación informativa.

Ejemplos de esa clasificación: una ingesta fallida o un `dbt run` fallido son
graves; un `dbt test` en rojo o una regeneración de documentación fallida son leves
(los marts existentes siguen sirviendo, pero alguien tiene que mirarlo).

Las notificaciones no se mandan desde el flow: las despachan los hooks
`on_completion` / `on_failure`. Un flow no debería saber cómo se avisa.

**Schedules solo en producción** (`settings.is_prod`). Nadie quiere que su máquina
golpee la API del origen cada mañana, ni que un entorno de pruebas dispare cargas
que nadie pidió. El disparo manual desde la UI funciona en todos los entornos.

## 6. Transformación: modelo dimensional (Kimball)

| Capa | Materialización | Schema | Qué hace | Qué NO hace |
|---|---|---|---|---|
| `staging` | view | `staging` | renombrar al español, castear, limpiar. 1:1 con raw | joins, agregaciones |
| `intermediate` | ephemeral | — | lógica de negocio reutilizable | presentación |
| `marts` | table | `marts` | el modelo dimensional que consume BI | reglas nuevas de negocio |
| snapshots | table | `scd2` | historia de lo que el origen pisa | ser consumidos directo por BI |

El proyecto de dbt modela **solo datos de negocio**. La metadata del orquestador
(corridas, deployments) vive en su propio schema, aislada, y no se modela: acoplaría
la capa de transformación al schema interno de una herramienta que cambia en cada
upgrade. Ver [ADR 0003](adr/0003-modelos-sobre-prefect-como-tabla.md).

`intermediate` **no tiene schema propio**: sus modelos son `ephemeral`, o sea que dbt
los inlinea como CTE en quien los consume y no crean ningún objeto en la base. Tener
un schema vacío solo confunde. Si algún día uno se vuelve caro y lo usan varios
marts, se lo materializa como tabla y ahí sí se le da schema.

**Idioma:** de staging en adelante, todo en español —nombres de modelos y de
columnas—, porque es el vocabulario del negocio que lee los reportes. Raw se queda
con los nombres del origen. La frontera del renombre es exactamente la capa de
staging, y es visible en un diff.

Nomenclatura: `stg_<fuente>__<recurso>`, `int_<fuente>__<concepto>`, y en marts
`dim_` (dimensiones), `fct_` (hechos) y `rpt_` (agregados listos para una vista).

### El esquema estrella del ejemplo

```
                    ┌──────────────┐
                    │   dim_fecha   │   dimensión conformada
                    └──────┬───────┘   (todos los días, incluso sin hechos)
                           │ date_key
                    ┌──────▼─────────────────┐
   base_currency_key│                        │quote_currency_key
   ┌────────────────┤   fct_cotizacion    ├────────────────┐
   │                │  (snapshot periódico)  │                │
   │                └────────────────────────┘                │
   │                                                          │
┌──▼─────────────┐                                    ┌───────▼────────┐
│  dim_moneda  │◄─── la MISMA dimensión, dos roles ─┤  dim_moneda  │
└────────────────┘                                    └────────────────┘
```

Decisiones de modelado que vale la pena entender:

- **Tipo de hecho:** snapshot periódico, no transaccional. No hay un evento de
  negocio por fila: es el valor de un par de monedas al cierre de cada día
  publicado. Grano: una fila por fecha y par de monedas.
- **Aditividad:** la cotización es SEMI-ADITIVA (no se suma entre fechas: se promedia
  o se toma la última) y la variación porcentual es NO ADITIVA. Está documentado en
  el modelo, porque es lo primero que se hace mal en un tablero.
- **Dimensión con dos roles:** `dim_moneda` se referencia dos veces desde el hecho
  (moneda base y cotizada). Es el patrón de Kimball para role-playing dimensions.
- **Claves subrogadas** (`currency_key`, `date_key`): aíslan los hechos del código
  natural del origen. `date_key` es la clásica clave "inteligente" YYYYMMDD.
- **La dimensión incluye lo que ya no existe:** monedas discontinuadas marcadas con
  `is_active = false`. Sacarlas rompería la integridad referencial de todo el
  histórico.
- **Un `rpt_` agrega, no define:** las reglas de negocio viven en `intermediate` y se
  usan desde varios marts. Si la copiás en cada mart, en tres meses dan distinto.

### Historia: SCD2 separado de la foto actual

El catálogo se carga con `replace`, así que raw solo tiene la foto de hoy. Cuando el
origen retira una moneda, la fila desaparece — y con ella la posibilidad de explicar
por qué un reporte de hace dos años la incluía. El snapshot (SCD Type 2), en la
carpeta `scd2/` y el schema homónimo, registra esas altas y bajas con
`invalidate_hard_deletes`.

**Y sí: la historia va separada de la dimensión.** Son dos tablas con dos propósitos:

| | `dim_moneda` | `dim_moneda_historia` |
|---|---|---|
| Grano | una moneda | una moneda por período de vigencia |
| Responde | ¿cómo es hoy? | ¿qué decía en tal fecha? |
| La usan | los hechos y el 95% de los tableros | auditoría y análisis histórico |

El motivo de fondo: un hecho tiene que poder unirse a la dimensión con UN join y sin
filtrar por rango de vigencia. Si la dimensión tuviera varias versiones por moneda,
cada query del tablero necesitaría `where valido_hasta is null`, y el que se olvide
multiplica sus filas sin darse cuenta. Kimball admite las dos formas; separarlas es
lo que conviene cuando la mayoría de las consultas quiere el estado actual.

`dim_moneda_historia` es una publicación del snapshot en marts, con nombres de
negocio y un flag `es_version_vigente`, para que BI no tenga que conocer las columnas
internas de dbt (`dbt_valid_from` / `dbt_valid_to`).

Estrategia `check` y no `timestamp`: el origen no expone fecha de modificación, y el
único timestamp disponible (`_ingested_at`) cambia en cada corrida.

### Documentación y linaje

El servicio `dbt-docs` del compose sirve el catálogo en http://localhost:8085: el
grafo completo de dependencias, las descripciones de cada modelo y columna, y los
tests asociados. Se regenera con `make dbt-docs` (y el ETL lo hace al final de cada
corrida). Es la forma más rápida de responder "¿qué alimenta este mart?" y "¿qué
rompo si toco esta columna?".

## 7. Entornos

| | dev | prod |
|---|---|---|
| Dónde corre | máquina del desarrollador, todo en Docker | servidor (runner self-hosted) |
| Warehouse | Postgres del compose | Postgres managed |
| Metadata de Prefect | schema `prefect` de la misma base | ídem |
| Schedules | no | **sí** |
| Secretos | `.env.local` | GitHub Environment `prod` |
| Se levanta | `make up` | deploy por tag |

En producción se despliega una **imagen publicada**, no el código: el CI la construye
una vez con el tag del release y el servidor solo la baja. Eso da rollback por tag y
deja al servidor sin copia del fuente. Ver [deploy.md](deploy.md) para el detalle de
secretos y del pipeline de deploy.

### Zona horaria

Todo el stack corre en `America/Argentina/Buenos_Aires`, con `TIMEZONE` como única
fuente de verdad: la base (a nivel de base y de rol), los contenedores (`TZ`), los
timestamps que escribe dlt y los `Cron` de los deployments. Los datos se guardan como
`timestamptz` —un instante absoluto—, así que la zona define cómo se interpretan, no
lo que se almacena. Un test de dbt falla si la sesión no está en la zona esperada.
Ver [ADR 0006](adr/0006-zona-horaria-unica.md).

### Roles de base de datos

`scripts/init_db_permissions.sql` crea cuatro roles con permisos distintos:

| Rol | Puede |
|---|---|
| `etl_app` | dueño de los schemas de datos: lo usan dlt y dbt. Tiene CREATE sobre la base |
| `prefect_app` | dueño del schema `prefect`, con `search_path` propio. Nadie más lo lee |
| `bi_reader` | leer `marts` y `seeds`, nada más |
| `analyst` | leer todas las capas de datos (incluido raw), sin escribir |

Que `bi_reader` no vea raw es deliberado: si la herramienta de BI puede leer datos sin
transformar, alguien va a construir un tablero sobre ellos y ese tablero se va a
romper en la próxima corrida. Tampoco ve `scd2`, donde conviven versiones vigentes y
vencidas: lo que consume es la dimensión o la vista de historia publicada en marts.

Prefect necesita su propio rol porque su migrador crea tablas sin calificar el
schema: la única forma de que no las cree en `public` es que el `search_path` del
rol apunte al schema correcto. Y ese `search_path` incluye `public` al final,
porque sus migraciones usan operadores de `pg_trgm`, que vive ahí.

## 8. Qué mirar cuando algo da un número raro

1. UI de Prefect — ¿corrió? ¿cuándo terminó bien por última vez? (y las
   notificaciones de Telegram, que avisan sin que haya que ir a mirar)
2. `make diagnose` — ¿hay duplicados por clave natural? ¿hasta qué fecha llegó raw?
3. `dbt source freshness` — ¿raw está fresco o el mart muestra data vieja?
4. `dbt test` — ¿algún test de calidad en rojo? (las filas que fallaron quedan en
   `dbt_test_audit`)
5. dbt docs (http://localhost:8085) — ¿de dónde sale esa columna?

El [runbook](runbook.md) tiene el detalle por síntoma.
