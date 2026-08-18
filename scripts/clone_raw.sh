#!/usr/bin/env bash
# Clona el schema raw de un entorno remoto al Postgres local, para poder
# desarrollar los modelos dbt con datos reales sin volver a ingestar (que es lento
# y consume cuota del origen).
#
# Uso:
#   ENV=prod bash scripts/clone_raw.sh dump      # solo descarga el dump
#            bash scripts/clone_raw.sh restore   # restaura el último dump
#   ENV=prod bash scripts/clone_raw.sh clone     # dump + restore
#
# Las credenciales salen de los .env en cascada: .env (común) + .env.<entorno>.
# El destino siempre es el Postgres local del compose.
#
# El pg_dump del cliente tiene que ser de una versión >= al servidor de origen.
set -euo pipefail

ACTION="${1:-clone}"
ENV="${ENV:-prod}"
DUMP_DIR=".tmp"
DUMP_FILE="${DUMP_DIR}/raw_${ENV}.dump"

load_env() {
    # Carga .env y después el del entorno: el segundo pisa lo que define.
    local suffix="$1"
    for f in .env ".env.${suffix}"; do
        [ -f "$f" ] || { echo "❌ Falta $f (corré: make env-init)"; exit 1; }
        set -a
        # shellcheck disable=SC1090
        . "$f"
        set +a
    done
}

do_dump() {
    load_env "$ENV"
    mkdir -p "$DUMP_DIR"
    echo "📦 Dump de raw desde ${ENV} (${DB_HOST}/${DB_NAME})..."
    PGPASSWORD="$DB_PASSWORD" pg_dump \
        --host="$DB_HOST" --port="${DB_PORT:-5432}" \
        --username="$DB_USER" --dbname="$DB_NAME" \
        --schema=raw --format=custom --no-owner --no-privileges \
        --file="$DUMP_FILE"
    echo "✅ Dump en $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"
}

do_restore() {
    [ -f "$DUMP_FILE" ] || { echo "❌ No existe $DUMP_FILE. Corré primero: ENV=$ENV $0 dump"; exit 1; }
    load_env "local"
    echo "♻️  Restaurando en el Postgres local (${DB_HOST}:${DB_PORT}/${DB_NAME})..."
    PGPASSWORD="$DB_PASSWORD" pg_restore \
        --host="$DB_HOST" --port="$DB_PORT" \
        --username="$DB_USER" --dbname="$DB_NAME" \
        --clean --if-exists --no-owner --no-privileges \
        --schema=raw "$DUMP_FILE"
    echo "✅ raw restaurado. Para reconstruir los marts: make dbt-build"
}

case "$ACTION" in
    dump)    do_dump ;;
    restore) do_restore ;;
    clone)   do_dump && do_restore ;;
    *)       echo "Uso: $0 [dump|restore|clone]"; exit 1 ;;
esac
