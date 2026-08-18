#!/usr/bin/env bash
# Aplica scripts/init_db_permissions.sql contra la base que indique el entorno.
#
# Es el MISMO archivo de SQL en dev y en producción: un solo lugar donde viven los
# schemas, los roles y los permisos. Lo único que cambia es contra qué base corre.
#
# Idempotente: se puede ejecutar tantas veces como haga falta. En el deploy corre
# SIEMPRE, antes de levantar el stack, para que un schema o un grant nuevo esté
# aplicado antes de que el worker intente usarlo.
#
# Corre psql dentro de un contenedor `postgres:<major>` en vez de exigir el cliente
# instalado: el runner self-hosted no tiene por qué tenerlo, y así la versión del
# cliente acompaña a la del servidor.
#
# Uso (producción, desde el workflow de deploy):
#     DB_HOST=... DB_NAME=... DB_SSLMODE=require \
#     PG_ADMIN_USER=... PG_ADMIN_PASSWORD=... \
#     ETL_PASSWORD=... PREFECT_DB_PASSWORD=... \
#     BI_READER_PASSWORD=... ANALYST_PASSWORD=... \
#     bash scripts/apply_db_permissions.sh
#
# Uso (desarrollo): `make db-permissions`, que completa todo desde el .env.local.
set -euo pipefail

for v in DB_HOST DB_NAME PG_ADMIN_USER PG_ADMIN_PASSWORD \
         ETL_PASSWORD PREFECT_DB_PASSWORD BI_READER_PASSWORD ANALYST_PASSWORD; do
    if [ -z "${!v:-}" ]; then
        echo "ERROR: falta la variable $v" >&2
        exit 1
    fi
done

DB_PORT="${DB_PORT:-5432}"
PG_IMAGE="${PG_IMAGE:-postgres:18}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Ninguna password aparece en la línea de comandos, ni del host ni del contenedor:
# `docker run -e VAR` (sin `=valor`) copia el valor desde el entorno de este proceso,
# y la expansión a los `-v` de psql ocurre DENTRO del contenedor, vía `sh -c` con
# comillas simples. Un `ps aux` en el servidor solo ve los nombres de las variables.
export PGPASSWORD="$PG_ADMIN_PASSWORD"
export PGSSLMODE="${DB_SSLMODE:-require}"
export V_ETL="$ETL_PASSWORD"
export V_PREFECT="$PREFECT_DB_PASSWORD"
export V_BI="$BI_READER_PASSWORD"
export V_ANALYST="$ANALYST_PASSWORD"
export V_HOST="$DB_HOST" V_PORT="$DB_PORT" V_USER="$PG_ADMIN_USER" V_DB="$DB_NAME"

# Red de Docker: en producción la base es externa y alcanza con la red por defecto;
# en desarrollo vive en la red del compose y hay que entrar ahí.
red=()
[ -n "${PG_DOCKER_NETWORK:-}" ] && red=(--network "$PG_DOCKER_NETWORK")

echo "=== Permisos de base: ${PG_ADMIN_USER}@${DB_HOST}:${DB_PORT}/${DB_NAME} (sslmode=${PGSSLMODE}) ==="

docker run --rm "${red[@]}" \
    -v "${REPO_DIR}/scripts:/scripts:ro" \
    -e PGPASSWORD -e PGSSLMODE \
    -e V_ETL -e V_PREFECT -e V_BI -e V_ANALYST \
    -e V_HOST -e V_PORT -e V_USER -e V_DB \
    "$PG_IMAGE" \
    sh -c 'psql -v ON_ERROR_STOP=1 \
        -h "$V_HOST" -p "$V_PORT" -U "$V_USER" -d "$V_DB" \
        -v etl_password="$V_ETL" \
        -v prefect_password="$V_PREFECT" \
        -v bi_password="$V_BI" \
        -v analyst_password="$V_ANALYST" \
        -f /scripts/init_db_permissions.sql'

echo "=== Permisos aplicados ==="
