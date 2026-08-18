#!/bin/bash
# Init del Postgres local: crea schemas, roles y permisos.
#
# Postgres corre los archivos de /docker-entrypoint-initdb.d/ UNA sola vez, la
# primera vez que arranca con el volumen vacío. Para volver a ejecutarlo hay que
# borrar el volumen (`make reset-db`).
#
# Las passwords vienen del entorno del contenedor (definidas en .env.local); no
# quedan escritas en ningún archivo del repo.
set -euo pipefail

echo "=== init: schemas, roles y permisos ==="

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" \
     --dbname "$POSTGRES_DB" \
     -v etl_password="${ETL_PASSWORD:-dev_password}" \
     -v prefect_password="${PREFECT_DB_PASSWORD:-prefect_password}" \
     -v bi_password="${BI_READER_PASSWORD:-bi_password}" \
     -v analyst_password="${ANALYST_PASSWORD:-analyst_password}" \
     -f /scripts/init_db_permissions.sql

# El rol del ETL se llama etl_app en el script de permisos. Si el .env define
# otro nombre de usuario, se le da el mismo poder (útil cuando el cliente impone
# el nombre del usuario de la base).
if [ -n "${ETL_USER:-}" ] && [ "${ETL_USER}" != "etl_app" ]; then
    echo "=== init: alias de rol ${ETL_USER} → etl_app ==="
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
         -v etl_user="${ETL_USER}" -v etl_password="${ETL_PASSWORD:-dev_password}" <<'SQL'
SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'etl_user'))::int AS need_user \gset
\if :need_user
CREATE ROLE :"etl_user" LOGIN PASSWORD :'etl_password';
\endif
GRANT etl_app TO :"etl_user";
SQL
fi

echo "=== init: listo ==="
