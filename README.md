# etl-arquitectura

Arquitectura base de los ETLs: ingesta con [dlt](https://dlthub.com), transformación
con [dbt](https://docs.getdbt.com), orquestación con [Prefect 3](https://docs.prefect.io)
y warehouse en PostgreSQL, con un **ejemplo funcional completo** de punta a punta.

El ejemplo ingesta los tipos de cambio del Banco Central Europeo desde
[frankfurter.dev](https://frankfurter.dev) —27 años de histórico, API pública sin
credenciales— y los modela en un esquema estrella de Kimball. Sirve para levantar el
stack, ver el ciclo completo funcionando y usarlo de molde.

```
     origen                ingesta            warehouse (PostgreSQL)              BI
┌───────────────┐      ┌───────────┐   ┌───────────────────────────────────┐  ┌─────────┐
│  API REST     │      │           │   │ raw      → tal cual llegó         │  │         │
│  (Frankfurter │─────▶│    dlt    │──▶│ staging  → tipado y en español    │─▶│ Power BI│
│   / tu ERP)   │      │           │   │ interm.  → lógica de negocio      │  │ Metabase│
└───────────────┘      └───────────┘   │ marts    → dim_ / fct_ / rpt_     │  │         │
                             ▲         │ scd2     → historia (SCD Type 2)  │  └─────────┘
                             │         └───────────────────────────────────┘
                             │                          ▲
                        Prefect 3 ────────── dbt ───────┘
              (schedules, reintentos, alertas por Telegram)
```

## Arrancar

```bash
make setup        # venv + dependencias + hooks de git
make env-init     # genera .env.local y .env.prod (los defaults ya funcionan)
make up           # Postgres + Prefect + worker + dbt docs, todo en Docker
```

Eso deja andando:

| | URL |
|---|---|
| Prefect UI | http://localhost:4210 |
| dbt docs (modelos y linaje) | http://localhost:8085 |
| Postgres | `localhost:5442` (`etl_app` / `dev_password`) |

Y para ver el ciclo completo:

```bash
make ingest        # raw vacío ⇒ carga histórica: 27 años, ~265.000 filas, ~15 s
make dbt-build     # seeds + modelos + snapshots + tests
make diagnose      # estado de raw: cobertura, duplicados, última fecha
```

O disparándolo como lo hace producción, desde la UI de Prefect o por CLI:

```bash
make sh
prefect deployment run 'frankfurter-rates/frankfurter-rates'
```

## Comandos frecuentes

```bash
make help                    # todos los comandos

make up | down | logs | ps | sh | psql | reset-db

make ingest                  # corrida incremental (con ventana de overlap)
make ingest-historical       # recarga el histórico completo desde cero

make lint                    # ruff
make fmt                     # ruff format + fix
make sqlfmt                  # sqlfluff sobre los modelos dbt

make test                    # unitarios (rápidos, sin DB)
make test-int                # integración contra el Postgres del compose
make test-live               # smoke contra la API real

make dbt-build               # seed + run + snapshot + test
make dbt CMD="run --select +fct_cotizacion"
make dbt-docs                # regenera documentación y linaje
```

## Estructura

```
src/
├── ingestion/               # origen → raw
│   ├── sources/frankfurter/ #   CÓMO HABLAR con el origen (cliente sobre helpers de dlt)
│   ├── pipelines/frankfurter/ # CÓMO CARGAR (dlt: merge, incremental con lag, troceado)
│   └── metadata.py          #   metadata común de raw (_ingested_at, _source)
├── orchestration/           # Prefect: tasks → flows → deployments
├── dbt/                     # dbt: staging → intermediate → marts (Kimball) + scd2
└── shared/                  # settings, logging, notificaciones, warehouse, resiliencia

.deploy/                     # Dockerfile, entrypoint, compose por entorno
.github/                     # CI: tests, dbt CI, deploy, releases, dependabot
docs/                        # arquitectura, playbooks, runbook, ADRs, fuentes
scripts/                     # permisos de la base, diagnóstico, clonado, utilidades
tests/                       # unit/ (sin DB) · integration/ (Postgres real y API real)
```

## El ejemplo, en concreto

**Ingesta.** Carga histórica automática si raw está vacío, incremental con ventana de
overlap el resto de los días, y troceado adaptativo que arranca pidiendo un año y se
achica solo si el origen falla. Reintentos, backoff y respeto de `Retry-After` los
pone dlt por configuración; el circuit breaker corta si el origen se cae. En `raw` los
nombres de columna son **exactamente** los del origen: el renombre al español es
trabajo de staging.

**Modelo dimensional (en español).** Esquema estrella con `fct_cotizacion` (snapshot
periódico, 265.000 filas) y dos dimensiones conformadas: `dim_fecha` y `dim_moneda`
— esta última usada con **dos roles** (moneda base y moneda cotizada) y con las
monedas históricas que ya no se publican marcadas como no vigentes. La historia de la
dimensión vive aparte, en `dim_moneda_historia` (SCD Type 2), para que los hechos
puedan unirse con un solo join. Más un agregado mensual listo para el tablero.

**Monitoreo.** Estado de las corridas en la UI de Prefect, y avisos por Telegram
cuando un flow falla o termina degradado. La metadata del orquestador no se modela
con dbt, a propósito ([ADR 0003](docs/adr/0003-modelos-sobre-prefect-como-tabla.md)).

## Documentación

| Documento | Para qué |
|---|---|
| [docs/arquitectura.md](docs/arquitectura.md) | Cómo está armado y por qué cada decisión |
| [docs/agregar_una_fuente.md](docs/agregar_una_fuente.md) | Playbook: sumar una fuente nueva |
| [docs/runbook.md](docs/runbook.md) | Operación: qué hacer cuando algo falla |
| [docs/deploy.md](docs/deploy.md) | Entornos, secretos y pipeline de deploy |
| [docs/fuentes/frankfurter.md](docs/fuentes/frankfurter.md) | La fuente de ejemplo y sus rarezas |
| [docs/adr/](docs/adr/) | Decisiones de arquitectura registradas |
| [CLAUDE.md](CLAUDE.md) | Contexto y convenciones para agentes de IA |

## Convenciones

- **Idioma:** español para docs, comentarios y commits; inglés para nombres de
  modelos y columnas de staging en adelante. Raw conserva los nombres del origen.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org), validados
  por commitlint en pre-commit y en CI.
- **Ramas:** `feature/* → dev → main`; los tags disparan el deploy a producción.
- **Secretos:** nunca en el repo. Contrato en los `.env.*.tpl` (commiteados, sin
  valores), valores en los `.env.*` locales o en GitHub Secrets.
- **Zona horaria:** todo el stack en `America/Argentina/Buenos_Aires`, con `TIMEZONE`
  como única fuente de verdad.
- **Ramas:** a `dev` y a `main` solo se entra por PR (`scripts/setup_branch_protection.sh`).
- **Deploy:** el CI publica una imagen por release y el servidor solo la baja; el
  rollback es apuntar a un tag anterior.
- **Dependencias:** pineadas exactas y actualizadas por Dependabot.
