# =============================================================================
# Makefile — entorno local y stacks Docker
# =============================================================================
# Dos entornos:
#   dev  (default) todo en Docker: Postgres + Prefect + worker + dbt docs.
#   prod           se deploya por CI tras un tag; acá solo para operar el server.
#
# Secretos: no hay gestor externo. Los .env.*.tpl son el contrato (commiteados, sin
# valores) y los .env.* con valores quedan fuera de git:
#   .env.local   desarrollo
#   .env.prod    producción (en CI lo renderiza el deploy desde GitHub Secrets)
# Cada archivo tiene TODAS las variables de su entorno: no hay cascada.
# =============================================================================

.PHONY: help setup setup-hooks hooks install-uv env-init env-render require-env \
        up down restart build logs ps sh psql reset-db wait-postgres \
        lint fmt sqlfmt \
        test test-cov test-int test-live test-all \
        dbt dbt-build dbt-deps dbt-compile dbt-docs \
        ingest ingest-currencies ingest-rates ingest-reconcile ingest-historical \
        db-dump db-restore-local db-clone db-permissions diagnose

ENV ?= dev

COMPOSE_FILE := .deploy/$(ENV)/docker-compose.yml
PROJECT_NAME := etl-arquitectura-$(ENV)

# Un archivo por entorno, con todas las variables (sin cascada).
ENV_FILE := .env.$(if $(filter dev,$(ENV)),local,$(ENV))

VENV   := venv
PYTHON := $(VENV)/bin/python3

DOCKER_COMPOSE := docker compose -p $(PROJECT_NAME) -f $(COMPOSE_FILE) --env-file $(ENV_FILE)

DBT_DIR := src/dbt

help:
	@echo "Uso: make <comando> [ENV=dev|prod]"
	@echo ""
	@echo "Setup:"
	@echo "  install-uv   : instala uv (gestor de paquetes Python)."
	@echo "  setup        : venv + dependencias dev + hooks de git."
	@echo "  env-init     : crea .env.local y .env.prod desde los .tpl (contratos).""
	@echo "  env-render   : renderiza los .env desde variables ya exportadas (lo que hace CI)."
	@echo ""
	@echo "Stack local:"
	@echo "  up           : levanta Postgres + Prefect + worker + dbt docs."
	@echo "  down         : baja los contenedores."
	@echo "  logs / ps / sh"
	@echo "  psql         : abre psql en el Postgres del compose."
	@echo "  db-permissions: reaplica schemas, roles y permisos (sin borrar datos)."
	@echo "  reset-db     : BORRA el volumen de Postgres y lo reinicializa."
	@echo ""
	@echo "URLs del entorno local (según .env.local):"
	@echo "  Prefect UI   : http://localhost:4210"
	@echo "  dbt docs     : http://localhost:8085"
	@echo "  Postgres     : localhost:5442"
	@echo ""
	@echo "Ingesta (dentro del container):"
	@echo "  ingest             : corrida incremental de los dos recursos."
	@echo "  ingest-currencies  : solo el catálogo de monedas."
	@echo "  ingest-rates       : solo las cotizaciones (incremental con overlap)."
	@echo "  ingest-reconcile   : re-pide N días atrás. Uso: make ingest-reconcile OVERLAP=3650"
	@echo "  ingest-historical  : recarga el histórico completo desde cero."
	@echo ""
	@echo "Calidad:"
	@echo "  lint / fmt / sqlfmt"
	@echo ""
	@echo "Tests:"
	@echo "  test         : unitarios (rápidos, sin DB)."
	@echo "  test-cov     : unitarios con coverage."
	@echo "  test-int     : integración contra el Postgres del compose."
	@echo "  test-live    : smoke contra la API real (RUN_LIVE_TESTS=1)."
	@echo "  test-all     : toda la suite."
	@echo ""
	@echo "dbt:"
	@echo "  dbt-build    : seed + run + snapshot + test."
	@echo "  dbt CMD=\"build --select +fct_cotizacion\""
	@echo "  dbt-docs     : regenera la documentación y el linaje."
	@echo ""
	@echo "Datos:"
	@echo "  diagnose     : diagnóstico read-only de raw."
	@echo "  db-clone     : clona raw de otro entorno al local. SRC=prod"

# --- Setup -------------------------------------------------------------------

install-uv:
	@command -v uv >/dev/null 2>&1 && echo "✅ uv: $$(uv --version)" || { \
		echo "Instalando uv..."; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	}

setup: setup-hooks
	@echo "✅ Setup completo. Siguiente paso: make env-init && make up"

setup-hooks: install-uv
	@echo "Creando venv e instalando dependencias..."
	@if [ ! -d $(VENV) ]; then uv venv $(VENV) --python 3.13; fi
	@uv pip install --python $(PYTHON) -r requirements/dev.txt
	@echo "Instalando hooks de git..."
	@$(VENV)/bin/pre-commit install --hook-type pre-commit --hook-type commit-msg

hooks:
	@if [ ! -f .git/hooks/commit-msg ] || [ ! -f .git/hooks/pre-commit ]; then $(MAKE) setup-hooks; fi

# Genera los .env resolviendo los defaults de los .tpl y dejando vacías las
# variables requeridas. Nunca sobreescribe un archivo existente.
env-init:
	@for env in local prod; do \
		target=".env.$$env"; tpl=".env.$$env.tpl"; \
		if [ -f "$$target" ]; then \
			echo "⚠️  $$target ya existe — no lo toco."; \
		else \
			python3 .deploy/render_env.py "$$tpl" "$$target" --skip-missing && \
			echo "✅ Creado $$target"; \
		fi; \
	done
	@echo ""
	@echo "El entorno local ya funciona con los defaults: make up"

env-render:
	@python3 .deploy/render_env.py $(ENV_FILE).tpl $(ENV_FILE)
	@echo "✅ Renderizado $(ENV_FILE) desde las variables del entorno."

require-env:
	@test -f $(ENV_FILE) || { echo "❌ Falta $(ENV_FILE). Corré: make env-init"; exit 1; }

# --- Stack Docker ------------------------------------------------------------

# El arranque va en dos fases, igual que el deploy a producción: primero la base
# con sus permisos convergidos, después el resto del stack.
#
# Por qué no alcanza con el init del contenedor: ese script corre UNA sola vez, con
# el volumen vacío. Si alguien cambia los schemas o los grants y ya tenía la base
# levantada, el cambio no se aplicaba hasta un `reset-db` (que borra los datos). Al
# ser idempotente, reaplicarlo en cada `up` es barato y garantiza que la base
# siempre refleje lo que dice el repo.
up: require-env hooks
	@echo "Levantando Postgres ($(ENV))..."
	@DOCKER_UID=$$(id -u) DOCKER_GID=$$(id -g) $(DOCKER_COMPOSE) up -d --build postgres
	@$(MAKE) --no-print-directory wait-postgres
	@$(MAKE) --no-print-directory db-permissions
	@echo "Levantando el resto del stack..."
	@DOCKER_UID=$$(id -u) DOCKER_GID=$$(id -g) $(DOCKER_COMPOSE) up -d --build
	@echo ""
	@echo "✅ Listo. Prefect UI: http://localhost:$$(grep -E '^PREFECT_UI_PORT=' $(ENV_FILE) | cut -d= -f2)"
	@echo "   dbt docs:         http://localhost:$$(grep -E '^DBT_DOCS_PORT=' $(ENV_FILE) | cut -d= -f2)"

# Espera a que Postgres acepte consultas de verdad.
#
# No alcanza con el healthcheck ni con `--wait` de compose. En el PRIMER arranque el
# entrypoint de la imagen levanta un servidor TEMPORAL para correr los scripts de
# /docker-entrypoint-initdb.d/, y ese servidor arranca con `listen_addresses=''`:
# atiende por socket unix pero NO por TCP. Una sonda que entre por el socket (o
# `pg_isready` a secas) daría OK mientras una conexión TCP todavía es rechazada.
#
# Por eso la sonda fuerza TCP con `-h 127.0.0.1`: es el mismo camino que usa
# apply_db_permissions.sh, que se conecta desde otro contenedor de la red.
wait-postgres:
	@printf "Esperando a Postgres"
	@for i in $$(seq 1 45); do \
		if $(DOCKER_COMPOSE) exec -T postgres sh -c 'psql -h 127.0.0.1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "select 1"' >/dev/null 2>&1; then \
			echo " listo."; exit 0; \
		fi; \
		printf "."; sleep 2; \
	done; \
	echo ""; echo "❌ Postgres no respondió después de 90s."; exit 1

down: require-env
	@$(DOCKER_COMPOSE) down

restart: require-env
	@$(DOCKER_COMPOSE) restart

build: require-env
	@$(DOCKER_COMPOSE) build

logs: require-env
	@$(DOCKER_COMPOSE) logs -f

ps: require-env
	@$(DOCKER_COMPOSE) ps

sh: require-env
	@$(DOCKER_COMPOSE) exec etl-worker bash

psql: require-env
	@$(DOCKER_COMPOSE) exec postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# Reaplica schemas, roles, grants y permisos sobre la base local, SIN borrar datos.
# Es el mismo script que corre el deploy en producción, contra la misma base de dev:
# así un cambio en los permisos se prueba acá antes de que llegue a un cliente.
#
# Existe porque el init de Postgres corre UNA sola vez, con el volumen vacío: antes,
# tocar el SQL de permisos obligaba a `reset-db` y perder todos los datos cargados.
db-permissions: require-env
	@set -a; . ./.env.local; set +a; \
	DB_HOST=postgres DB_PORT=5432 DB_SSLMODE=disable \
	PG_ADMIN_USER="$$PG_ADMIN_USER" PG_ADMIN_PASSWORD="$$PG_ADMIN_PASSWORD" \
	ETL_PASSWORD="$$DB_PASSWORD" \
	PG_DOCKER_NETWORK=$$($(DOCKER_COMPOSE) config --format json | \
		$(VENV)/bin/python -c "import json,sys; print(next(iter(json.load(sys.stdin)['networks'].values()))['name'])") \
	bash scripts/apply_db_permissions.sh

# Borra el volumen y vuelve a empezar. Usalo solo si querés perder los datos: para
# reaplicar permisos sobre una base con datos está `make db-permissions`.
reset-db: require-env
	@echo "⚠️  Esto BORRA todos los datos del Postgres local."
	@read -p "¿Seguro? [s/N] " ok && [ "$$ok" = "s" ] || exit 1
	@$(DOCKER_COMPOSE) down -v
	@DOCKER_UID=$$(id -u) DOCKER_GID=$$(id -g) $(DOCKER_COMPOSE) up -d postgres
	@$(MAKE) --no-print-directory wait-postgres
	@$(MAKE) --no-print-directory db-permissions
	@echo "✅ Postgres reinicializado (schemas, roles y permisos aplicados)."

# --- Ingesta -----------------------------------------------------------------

# Un target por ETL. `ingest` corre los dos recursos, que es lo que uno quiere
# al probar la ingesta completa desde la consola.
ingest: ingest-currencies ingest-rates

ingest-currencies: require-env
	@$(DOCKER_COMPOSE) exec etl-worker python -c \
		"from ingestion.pipelines.frankfurter.runner import run_currencies_pipeline as r; print(r())"

ingest-rates: require-env
	@$(DOCKER_COMPOSE) exec etl-worker python -c \
		"from ingestion.pipelines.frankfurter.runner import run_rates_pipeline as r; print(r())"

# Reconciliación: re-pide OVERLAP días hacia atrás. `make ingest-reconcile OVERLAP=3650`
# barre diez años. Sin OVERLAP usa INGEST_RECONCILE_OVERLAP_DAYS del entorno.
ingest-reconcile: require-env
	@$(DOCKER_COMPOSE) exec etl-worker python -c \
		"from ingestion.pipelines.frankfurter.runner import run_rates_pipeline as r; \
		 print(r(overlap=$(or $(OVERLAP),None)))"

ingest-historical: require-env
	@$(DOCKER_COMPOSE) exec etl-worker python -c \
		"from ingestion.pipelines.frankfurter.runner import run_rates_pipeline as r; print(r(full_refresh=True))"

# --- Calidad -----------------------------------------------------------------

lint:
	@$(VENV)/bin/ruff check src/ tests/ scripts/

fmt:
	@$(VENV)/bin/ruff format src/ tests/ scripts/
	@$(VENV)/bin/ruff check --fix src/ tests/ scripts/

sqlfmt:
	@$(VENV)/bin/sqlfluff lint $(DBT_DIR)/models/

# --- Tests -------------------------------------------------------------------

test:
	@$(VENV)/bin/pytest tests/unit

test-cov:
	@$(VENV)/bin/pytest tests/unit --cov --cov-report=term-missing

test-int: require-env
	@$(DOCKER_COMPOSE) up -d postgres
	@$(VENV)/bin/pytest tests/integration -m integration

test-live:
	@RUN_LIVE_TESTS=1 $(VENV)/bin/pytest tests/integration -m live

test-all: require-env
	@$(DOCKER_COMPOSE) up -d postgres
	@$(VENV)/bin/pytest tests/

# --- dbt (dentro del container) ----------------------------------------------

dbt: require-env
	@if [ -z "$(CMD)" ]; then echo "Uso: make dbt CMD=\"run\"  (run|test|build|compile|debug|ls|docs generate)"; exit 1; fi
	@$(DOCKER_COMPOSE) exec etl-worker bash -c "cd /app/$(DBT_DIR) && dbt $(CMD) --profiles-dir ."

dbt-build: require-env
	@$(DOCKER_COMPOSE) exec etl-worker bash -c "cd /app/$(DBT_DIR) && dbt build --profiles-dir ."

dbt-deps: require-env
	@$(DOCKER_COMPOSE) exec etl-worker bash -c "cd /app/$(DBT_DIR) && dbt deps --profiles-dir ."

dbt-compile: require-env
	@$(DOCKER_COMPOSE) exec etl-worker bash -c "cd /app/$(DBT_DIR) && dbt compile --profiles-dir ."

# Regenera el catálogo y reinicia el servidor de docs para que sirva lo nuevo.
dbt-docs: require-env
	@$(DOCKER_COMPOSE) exec etl-worker bash -c "cd /app/$(DBT_DIR) && dbt docs generate --profiles-dir ."
	@$(DOCKER_COMPOSE) restart dbt-docs
	@echo "✅ Documentación regenerada: http://localhost:$$(grep -E '^DBT_DOCS_PORT=' $(ENV_FILE) | cut -d= -f2)"

# --- Datos -------------------------------------------------------------------

diagnose: require-env
	@$(DOCKER_COMPOSE) exec etl-worker python /app/scripts/diagnose_raw.py

SRC ?= prod

db-dump:
	@ENV=$(SRC) bash scripts/clone_raw.sh dump

db-restore-local:
	@bash scripts/clone_raw.sh restore

db-clone:
	@ENV=$(SRC) bash scripts/clone_raw.sh clone
