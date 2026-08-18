# etl-arquitectura

Arquitectura base de los ETLs del equipo, con un ejemplo funcional completo:
ingesta de tipos de cambio del BCE (API pública [frankfurter.dev](https://frankfurter.dev))
modelada en un esquema estrella de Kimball.

> Al clonar este repo para un cliente: reemplazá la fuente de ejemplo por la real
> siguiendo `docs/agregar_una_fuente.md`, y actualizá **Stack**, **Estructura** y
> **Comandos** de este archivo con la realidad de ese proyecto.

## Stack

- Python 3.13
- Ingesta: **dlt** 1.30 · Transformación: **dbt-core** 1.12 + dbt-postgres 1.11
- Orquestación: **Prefect** 3.8 (worker `process` + deployments con schedule)
- Warehouse: **PostgreSQL 18** (arquitectura medallón + modelo dimensional)
- Config: **pydantic-settings** · Logs: **loguru** → UI de Prefect
- Resiliencia: retry/backoff de dlt + **pybreaker** (circuit breaker)
- Infra: Docker multi-stage (dev/prod) · GitHub Actions · runner self-hosted
- Secretos: GitHub Secrets por Environment (ver `docs/adr/0001-*`)
- Linting: `ruff`, `sqlfluff`, `commitlint`, `gitleaks`
- Dependencias pineadas exactas, actualizadas por Dependabot

## Estructura del proyecto

```
src/
├── ingestion/                       # origen → raw
│   ├── metadata.py                  #   _ingested_at / _source en toda fila de raw
│   ├── sources/frankfurter/         #   CÓMO HABLAR con el origen (sin dlt salvo helpers HTTP)
│   │   └── client.py                #     RESTClient + traducción de errores + breaker
│   └── pipelines/frankfurter/       #   CÓMO CARGAR a raw
│       ├── constants.py             #     tablas, clave natural, overlap, ventana
│       ├── chunking.py              #     troceado adaptativo (AIMD)
│       ├── resources.py             #     @dlt.resource + @dlt.source
│       └── runner.py                #     ejecución + carga histórica si raw vacío
├── orchestration/                   # Prefect: tasks → flows → deployments
├── dbt/                             # proyecto dbt (se invoca por CLI, no se importa)
│   ├── models/staging/              #   views 1:1 con raw, renombradas al español
│   ├── models/intermediate/         #   ephemeral, reglas de negocio reutilizables
│   ├── models/marts/{core,cotizaciones}      # dim_ / fct_ / rpt_
│   ├── scd2/                        #   snapshots SCD Type 2 (schema `scd2`)
│   ├── seeds/ macros/ tests/
└── shared/                          # settings, logging, notificaciones, warehouse, resiliencia

.deploy/{dev,prod}/                  # compose por entorno + Dockerfile + entrypoint
.env.local.tpl, .env.prod.tpl        # contrato de variables (los .env no se commitean)
scripts/                             # init_db_permissions.sql, diagnose_raw.py, ...
tests/                               # unit/ (sin DB) · integration/ (Postgres y API reales)
```

## Comandos frecuentes

```bash
make setup && make env-init && make up    # entorno completo en Docker

make ingest                               # los dos recursos (currencies + rates)
make ingest-currencies | ingest-rates     # un ETL a la vez
make ingest-reconcile OVERLAP=3650        # re-pide N días hacia atrás
make ingest-historical                    # recarga histórica de cotizaciones
make dbt-build                            # seed + run + snapshot + test
make dbt-docs                             # regenera documentación y linaje
make diagnose                             # estado de raw

make lint | fmt | sqlfmt
make test | test-int | test-live
make logs | sh | psql | reset-db
```

URLs del entorno local: Prefect http://localhost:4210 · dbt docs http://localhost:8085 ·
Postgres `localhost:5442`.

## Convenciones

### Idioma
- Español para docs, comentarios y mensajes de commit.
- Inglés para nombres de modelos y columnas de staging en adelante. Raw conserva
  los nombres crudos del origen.

### Python
- Line length 120 · comillas dobles · imports absolutos desde `src/`.
- Reglas ruff: E, W, F, I, N, UP, B, SIM, TCH, **S**, ARG, SLF, RUF.
- Todo secreto se declara `SecretStr` en `shared/settings.py`.
- Los imports de dlt y de los clientes van **dentro** de las tasks de Prefect, no al
  tope del módulo (encarecen el registro de deployments).

### Nombres de tablas
- **raw:** `raw_{fuente}_{recurso}` — crudo; las COLUMNAS son las del origen.
- **staging:** `stg_{fuente}__{recurso}` — views, 1:1 con raw, ya en español.
- **intermediate:** `int_{fuente}__{concepto}` — ephemeral (sin schema propio).
- **marts:** `dim_{entidad}` / `fct_{proceso}` / `rpt_{reporte}`.
- **scd2:** `scd2_{fuente}__{entidad}` — historia SCD Type 2.

### Nombres de columnas (staging en adelante, en español)
- Claves subrogadas `clave_{entidad}` · claves naturales `codigo_{entidad}` o `id_{entidad}`
- booleanos `es_` / `tiene_` · fechas `fecha_` · timestamps `_en` (`cargado_en`)
- importes `importe_` · cantidades `cantidad_` · porcentajes `_pct`

### SQL (dbt)
- Todo en minúsculas, snake_case, alias explícitos, dialecto PostgreSQL, 120 chars.
- Casteo con `cast(x as t)`, no `x::t` (lo verifica sqlfluff).
- Cada modelo con su entrada en `_models.yml`: descripción, **grano** y tests.

### Git
- Conventional Commits: `<tipo>[scope]: <descripción>`.
- Flujo: `feature/* → dev → main`. Los tags disparan el deploy a producción.

## Invariantes que NO se rompen

Cosas que parecen detalles y son la razón de que el ETL sea confiable. Si tenés que
cambiar una, entendé primero por qué está (`docs/arquitectura.md` y `docs/adr/`).

1. **Delegar en dlt lo que dlt ya hace.** Retry, backoff, `Retry-After`, timeouts,
   paginación, auth, estado incremental y UPSERT. Si estás escribiendo un decorador
   de retry, algo está mal.
2. **El incremental usa `lag` + `range_start="closed"`.** Sin `lag`, las correcciones
   del origen no vuelven a entrar nunca y nadie se entera (ADR 0002).
3. **Clave natural correcta en `primary_key`.** Es lo que hace idempotente al merge.
   Sin clave natural, un `_row_id` estable entre corridas.
4. **Raw se guarda crudo, incluidos los nombres.** dlt corre con `naming = direct`:
   las columnas de raw son las del origen, tal cual. El renombre (y el pasaje al
   español) es de staging. La única otra excepción es aplanar respuestas cuyo shape
   dependa de los datos (ADR 0005).
5. **Chequear `load_info.has_failed_jobs`.** dlt no levanta excepción cuando un
   resource falla: sin ese chequeo, una carga parcial pasa como exitosa.
6. **Raw vacío ⇒ carga histórica.** El estado local de dlt no alcanza como fuente
   de verdad.
7. **Los flows no cortan en el primer error.** Cada paso en su `try/except` y
   `finalize_flow` aplica la política grave/leve al final.
8. **Schedules activos solo en producción** (`settings.is_prod`).
9. **Una regla de negocio, un lugar.** Si dos marts la necesitan, va a `intermediate`.
10. **dbt modela solo datos de negocio.** La metadata del orquestador no se modela:
    acopla la transformación al schema interno de una herramienta de terceros
    (ADR 0003).
11. **Secretos nunca en el repo.** Contrato en los `.env.*.tpl`, valores en los
    `.env.*` locales o en GitHub Secrets.
12. **Una sola zona horaria** (`TIMEZONE`) para base, contenedores, dlt, dbt y
    Prefect. Un test de dbt lo verifica (ADR 0006).
13. **De staging en adelante, todo en español**: nombres de modelos y de columnas.
14. **A `dev` y `main` solo se entra por PR.** Las reglas están en
    `scripts/setup_branch_protection.sh` y el CI se apoya en eso para no repetir
    verificaciones.
15. **Un ETL por recurso, con los parámetros que el origen puede dar.** Cada
    recurso tiene su pipeline de dlt, su estado y su flow: se programan distinto y
    fallan por separado. Pero no se clona el juego de parámetros por simetría: si
    el endpoint no tiene eje temporal, su ETL no expone `date_from`/`overlap` ni
    tiene reconciliación (`/currencies` ignora las fechas — ver
    `docs/fuentes/frankfurter.md`). Un parámetro que el origen ignora es una
    promesa falsa.
16. **El overlap es política operativa, no código.** `INGEST_OVERLAP_DAYS` y
    `INGEST_RECONCILE_OVERLAP_DAYS` viven en `.env`; los flows y deployments pasan
    `None` y dejan que se resuelvan. Cambiar cuánto se re-pide no debe requerir un
    deploy.

## Fuente de datos

`sources/frankfurter/` es el **ejemplo** de la arquitectura, no una fuente de negocio.
Sus particularidades verificadas están en `docs/fuentes/frankfurter.md` (rangos sin
publicación que devuelven el día hábil anterior, 404 como "sin datos", catálogo que
solo refleja el presente). Al adaptar el repo a un cliente, reemplazala siguiendo
`docs/agregar_una_fuente.md`.

## Documentación

| Documento | Para qué |
|---|---|
| `docs/arquitectura.md` | Cómo está armado y por qué cada decisión |
| `docs/agregar_una_fuente.md` | Playbook para sumar un origen |
| `docs/runbook.md` | Operación: qué hacer cuando algo falla |
| `docs/deploy.md` | Entornos, secretos y pipeline de deploy |
| `docs/fuentes/` | Una ficha por fuente, con sus rarezas y la fecha en que se verificaron |
| `docs/adr/` | Decisiones de arquitectura registradas (incluida una que se revirtió) |
