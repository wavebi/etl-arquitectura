#!/bin/bash
# Genera y sirve la documentación de dbt (modelos, linaje, tests, descripciones).
#
# `dbt docs generate` necesita conexión a la base: lee el catálogo real (columnas y
# tipos materializados), que es lo que hace útil al linaje. Si la base todavía no
# tiene los modelos, genera igual con lo que haya.
set -u

DBT_DIR="${DBT_PROJECT_DIR:-/app/src/dbt}"
PORT=8080

cd "$DBT_DIR"

echo "=== dbt docs: instalando paquetes ==="
dbt deps --profiles-dir . || echo "WARN: dbt deps falló, sigo."

echo "=== dbt docs: generando catálogo ==="
dbt docs generate --profiles-dir . || echo "WARN: generate falló; sirvo el catálogo anterior si existe."

echo "=== dbt docs: sirviendo en 0.0.0.0:${PORT} ==="
exec dbt docs serve --profiles-dir . --host 0.0.0.0 --port "${PORT}" --no-browser
