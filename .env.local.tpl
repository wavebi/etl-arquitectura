# =============================================================================
# .env.local — entorno de DESARROLLO (todo en Docker, nada toca la nube)
# =============================================================================
# ¿Por qué existe este .tpl si el .env.local es lo que se usa?
#
#   .env.local.tpl  → SE COMMITEA. Es el CONTRATO: la lista completa de variables
#                     que el proyecto necesita, documentadas, sin ningún valor real.
#                     Sirve para saber qué hay que configurar y para que el CI pueda
#                     generar el archivo con los secretos que guarda GitHub.
#   .env.local      → NO se commitea (está en .gitignore). Tiene los valores.
#
# Sin el .tpl, la lista de variables solo viviría en la máquina de quien armó el
# proyecto y en la cabeza de quien lo mantiene.
#
# Se genera con:   make env-init
# Sintaxis:        ${VAR} = requerida (si falta, el render falla)
#                  ${VAR:-default} = opcional con default
#
# Este archivo tiene TODAS las variables del entorno: no depende de ningún otro.
# =============================================================================

# --- App ---------------------------------------------------------------------
APP_NAME=${APP_NAME:-etl-arquitectura}
ENV=dev
DEBUG=${DEBUG:-true}
LOG_LEVEL=${LOG_LEVEL:-DEBUG}

# --- Zona horaria ------------------------------------------------------------
# Una sola variable manda en todo el stack: los contenedores (TZ), la base de datos
# (ALTER DATABASE ... SET timezone), los timestamps que escribe dlt y los horarios
# de los schedules de Prefect. No mezclar zonas: un ETL con la mitad en UTC y la
# mitad en local produce reportes que no cierran por unas horas y nadie entiende
# por qué.
TIMEZONE=${TIMEZONE:-America/Argentina/Buenos_Aires}

# --- Warehouse (Postgres del compose) ----------------------------------------
# Coordenadas del HOST: sirven para correr scripts y tests desde la máquina.
# Dentro de los containers el compose las pisa con el nombre del servicio.
# Si cambiás POSTGRES_PORT, cambiá DB_PORT al mismo valor.
DB_HOST=${DB_HOST:-localhost}
DB_PORT=${DB_PORT:-5442}
DB_NAME=${DB_NAME:-warehouse}
DB_USER=${DB_USER:-etl_app}
DB_PASSWORD=${DB_PASSWORD:-dev_password}
DB_SSLMODE=${DB_SSLMODE:-disable}

# Superuser del Postgres local: lo usa el init para crear roles y permisos.
POSTGRES_SUPERUSER=${POSTGRES_SUPERUSER:-postgres}
POSTGRES_SUPERUSER_PASSWORD=${POSTGRES_SUPERUSER_PASSWORD:-postgres}

# Roles que crea scripts/init_db_permissions.sql.
# prefect_app es el rol del orquestador: tiene su propio schema y search_path.
PREFECT_DB_USER=${PREFECT_DB_USER:-prefect_app}
PREFECT_DB_PASSWORD=${PREFECT_DB_PASSWORD:-prefect_password}
BI_READER_PASSWORD=${BI_READER_PASSWORD:-bi_password}
ANALYST_PASSWORD=${ANALYST_PASSWORD:-analyst_password}

# --- Prefect -----------------------------------------------------------------
PREFECT_WORK_POOL_NAME=${PREFECT_WORK_POOL_NAME:-etl-process-pool}

# --- Puertos publicados en el host -------------------------------------------
# Cambialos si ya tenés otro ETL corriendo en esta máquina: los defaults son iguales
# en todos los proyectos que salen de este scaffold y chocan entre sí.
POSTGRES_PORT=${POSTGRES_PORT:-5442}
PREFECT_UI_PORT=${PREFECT_UI_PORT:-4210}
DBT_DOCS_PORT=${DBT_DOCS_PORT:-8085}

# UID/GID con los que corre el worker, para que los archivos que escribe en el repo
# montado (target/ de dbt, logs) queden con tu usuario y no como root.
# En Linux: poné los tuyos (`id -u` / `id -g`). `make up` ya los inyecta.
DOCKER_UID=${DOCKER_UID:-1000}
DOCKER_GID=${DOCKER_GID:-1000}

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
# Paths RELATIVOS al root del repo: los mismos valores sirven corriendo dbt desde la
# máquina o dentro del container (donde el compose los pisa con los absolutos de /app).
DBT_PROJECT_DIR=${DBT_PROJECT_DIR:-src/dbt}
DBT_TARGET=${DBT_TARGET:-dev}
DBT_LOG_PATH=${DBT_LOG_PATH:-logs/dbt}
DBT_TARGET_PATH=${DBT_TARGET_PATH:-src/dbt/target}
