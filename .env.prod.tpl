# =============================================================================
# .env.prod — entorno de PRODUCCIÓN
# =============================================================================
#   .env.prod.tpl  → SE COMMITEA. Es el CONTRATO: la lista completa de variables,
#                    documentadas, sin ningún valor real.
#   .env.prod      → NO se commitea. En el deploy lo genera el CI resolviendo este
#                    contrato contra los secrets del GitHub Environment "prod"
#                    (.github/actions/run-compose), y lo borra al terminar.
#
# Las variables SIN default son REQUERIDAS: si falta una, el deploy corta antes de
# levantar nada. Es preferible a un contenedor arrancando con la contraseña vacía.
#
# Este archivo tiene TODAS las variables del entorno: no depende de ningún otro.
# =============================================================================

# --- Imagen a desplegar -------------------------------------------------------
# La calcula el workflow de deploy a partir del tag del release y la agrega a este
# archivo al final. Se declara acá para que el contrato esté completo y para poder
# fijarla a mano en un rollback:
#     ETL_IMAGE=ghcr.io/<owner>/<repo>:etl-arquitectura-v1.2.3 docker compose up -d
ETL_IMAGE=${ETL_IMAGE:-}

# --- App ---------------------------------------------------------------------
APP_NAME=${APP_NAME:-etl-arquitectura}
ENV=prod
DEBUG=${DEBUG:-false}
LOG_LEVEL=${LOG_LEVEL:-INFO}

# --- Zona horaria ------------------------------------------------------------
# Una sola variable manda en todo el stack: los contenedores (TZ), la base de datos
# (ALTER DATABASE ... SET timezone), los timestamps que escribe dlt y los horarios
# de los schedules de Prefect. No mezclar zonas: un ETL con la mitad en UTC y la
# mitad en local produce reportes que no cierran por unas horas y nadie entiende
# por qué.
TIMEZONE=${TIMEZONE:-America/Argentina/Buenos_Aires}

# --- Warehouse (Postgres managed) --------------------------------------------
DB_HOST=${DB_HOST}
DB_PORT=${DB_PORT:-5432}
DB_NAME=${DB_NAME}
DB_USER=${DB_USER}
DB_PASSWORD=${DB_PASSWORD}
DB_SSLMODE=${DB_SSLMODE:-require}

# Rol del orquestador (schema `prefect`, con search_path propio).
PREFECT_DB_USER=${PREFECT_DB_USER:-prefect_app}
PREFECT_DB_PASSWORD=${PREFECT_DB_PASSWORD}

# --- Prefect -----------------------------------------------------------------
PREFECT_WORK_POOL_NAME=${PREFECT_WORK_POOL_NAME:-etl-process-pool}

# --- Notificaciones (Telegram) ------------------------------------------------
# Vacío = notificaciones deshabilitadas (ver shared/utils/notifications.py).
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID:-}

# --- Fuente: Frankfurter (tipos de cambio del BCE) ----------------------------
# API pública, sin autenticación ni cuota declarada. https://frankfurter.dev
FRANKFURTER_BASE_URL=${FRANKFURTER_BASE_URL:-https://api.frankfurter.dev/v1}
# Moneda base de las cotizaciones. El BCE publica contra EUR.
FRANKFURTER_BASE_CURRENCY=${FRANKFURTER_BASE_CURRENCY:-EUR}
# Primer día con datos en el BCE. Es el piso de la carga histórica.
FRANKFURTER_HISTORY_START=${FRANKFURTER_HISTORY_START:-1999-01-04}

# --- Ingesta: ventana y overlap ----------------------------------------------
# Días que se re-piden hacia atrás en la corrida incremental DIARIA (`lag` de dlt).
# Cubre la corrección que el origen publica dentro de la misma semana.
INGEST_OVERLAP_DAYS=${INGEST_OVERLAP_DAYS:-7}
# Días que re-pide el ETL de RECONCILIACIÓN, que corre con otra cadencia y existe
# para atrapar correcciones viejas que el overlap corto no alcanza. Los dos ETLs
# comparten pipeline y cursor: lo único que cambia es cuánto se re-pide.
INGEST_RECONCILE_OVERLAP_DAYS=${INGEST_RECONCILE_OVERLAP_DAYS:-365}
# Ventana máxima (en días) que se le pide a la API de una sola vez. El troceado
# adaptativo arranca en este valor y lo baja solo si la API falla.
INGEST_WINDOW_MAX_DAYS=${INGEST_WINDOW_MAX_DAYS:-365}

# --- Cliente HTTP de dlt (retry, backoff, timeouts) --------------------------
# Los lee dlt directamente: no hay retry propio en el código.
RUNTIME__REQUEST_TIMEOUT=${RUNTIME__REQUEST_TIMEOUT:-60}
RUNTIME__REQUEST_MAX_ATTEMPTS=${RUNTIME__REQUEST_MAX_ATTEMPTS:-5}
RUNTIME__REQUEST_BACKOFF_FACTOR=${RUNTIME__REQUEST_BACKOFF_FACTOR:-1.5}
RUNTIME__REQUEST_MAX_RETRY_DELAY=${RUNTIME__REQUEST_MAX_RETRY_DELAY:-120}

# --- dbt ---------------------------------------------------------------------
# El compose los pisa con los absolutos de /app dentro del container.
DBT_PROJECT_DIR=${DBT_PROJECT_DIR:-src/dbt}
DBT_TARGET=${DBT_TARGET:-prod}
DBT_LOG_PATH=${DBT_LOG_PATH:-logs/dbt}
DBT_TARGET_PATH=${DBT_TARGET_PATH:-src/dbt/target}
