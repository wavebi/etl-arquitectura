#!/bin/bash
# Arranque del contenedor etl-worker: espera al server de Prefect, registra los
# deployments y queda corriendo como worker del work pool.
set -e

echo "=== ETL Worker Startup ==="

# Timeout configurable: si Prefect no responde en N segundos el worker muere y
# Docker lo reinicia limpio (restart: unless-stopped).
PREFECT_WAIT_TIMEOUT="${PREFECT_WAIT_TIMEOUT:-300}"

# 1. Esperar a que el server de Prefect esté listo (con timeout)
echo "Waiting for Prefect server (timeout: ${PREFECT_WAIT_TIMEOUT}s)..."
elapsed=0
until curl -s "${PREFECT_API_URL}/health" > /dev/null 2>&1; do
    elapsed=$((elapsed + 5))
    if [ "$elapsed" -ge "$PREFECT_WAIT_TIMEOUT" ]; then
        echo "ERROR: Prefect server not ready after ${PREFECT_WAIT_TIMEOUT}s. Exiting for Docker restart."
        if [ -n "${TELEGRAM_BOT_TOKEN}" ] && [ -n "${TELEGRAM_CHAT_ID}" ] && [ "${TELEGRAM_BOT_TOKEN}" != "mock_bot" ]; then
            curl -sf "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
                -d chat_id="${TELEGRAM_CHAT_ID}" \
                -d text="⚠️ ETL Worker (${ENV:-dev}): Prefect no responde después de ${PREFECT_WAIT_TIMEOUT}s. Container reiniciándose." \
                > /dev/null 2>&1 || true
        fi
        exit 1
    fi
    echo "Prefect server not ready, retrying in 5s... (${elapsed}/${PREFECT_WAIT_TIMEOUT}s)"
    sleep 5
done
echo "Prefect server is ready!"

# 2. Crear el work pool si no existe
echo "Ensuring work pool '${PREFECT_WORK_POOL_NAME}' exists..."
prefect work-pool create "${PREFECT_WORK_POOL_NAME}" --type process 2>/dev/null || echo "Work pool already exists."

# 3. Registrar deployments
echo "Registering deployments..."
python /app/src/orchestration/deploy.py

# 4. Cancelar runs colgados (RUNNING/PENDING) de la sesión anterior del worker.
# Si falla, seguimos: un error transitorio del cliente no debe bloquear el arranque.
echo "Cancelling stale flow runs from previous worker session..."
python /app/src/orchestration/cancel_stale_runs.py || echo "WARN: stale-run cleanup failed, continuing."

# 5. Instalar paquetes dbt (dbt_packages/ no se commitea).
# Idempotente. Sin esto, dbt run/seed falla con "0 packages installed" en los
# entornos donde el deploy no trae dbt_packages. Paths absolutos a propósito:
# DBT_PROJECT_DIR es relativo y dbt lo concatena al cwd.
echo "Installing dbt packages..."
dbt deps --project-dir /app/src/dbt --profiles-dir /app/src/dbt \
    || echo "WARN: dbt deps failed, dbt commands will fail later."

# 6. Arrancar el worker (bloquea y mantiene vivo el contenedor)
echo "Starting Prefect worker for pool '${PREFECT_WORK_POOL_NAME}'..."
exec prefect worker start --pool "${PREFECT_WORK_POOL_NAME}"
