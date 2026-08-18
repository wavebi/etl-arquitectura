#!/usr/bin/env bash
# Renombra el scaffold para un cliente concreto: reemplaza el slug `wavebi-etl`
# (y su variante snake_case `wavebi_etl`) en todo el repo.
#
# Uso: bash scripts/rename_project.sh mi-cliente-etl
#      make rename NAME=mi-cliente-etl
#
# Después de correrlo, revisá y ajustá a mano:
#   - .env*.tpl                 → nombres de base y del work pool, si querés otros
#   - .github/workflows/deploy.yml → ruta de deploy (/opt/<slug>/app/prod)
#   - README.md y CLAUDE.md     → descripción del proyecto
set -euo pipefail

NEW_SLUG="${1:?uso: rename_project.sh <nuevo-slug>}"
OLD_SLUG="etl-arquitectura"
NEW_SNAKE="${NEW_SLUG//-/_}"
OLD_SNAKE="etl_arquitectura"

if [[ ! "$NEW_SLUG" =~ ^[a-z][a-z0-9-]*$ ]]; then
    echo "❌ El slug debe ser minúsculas, números y guiones (ej: acme-etl)."
    exit 1
fi

echo "Renombrando: $OLD_SLUG → $NEW_SLUG  (y $OLD_SNAKE → $NEW_SNAKE)"

# Se excluyen los directorios generados y el propio .git.
mapfile -t FILES < <(
    grep -rl -e "$OLD_SLUG" -e "$OLD_SNAKE" . \
        --exclude-dir=.git \
        --exclude-dir=venv \
        --exclude-dir=.venv \
        --exclude-dir=node_modules \
        --exclude-dir=__pycache__ \
        --exclude-dir=dbt_packages \
        --exclude-dir=target \
        --exclude-dir=.tmp \
        --exclude="*.dump" || true
)

if [ ${#FILES[@]} -eq 0 ]; then
    echo "No hay nada que renombrar (¿ya se corrió?)."
    exit 0
fi

for file in "${FILES[@]}"; do
    sed -i "s/${OLD_SLUG}/${NEW_SLUG}/g; s/${OLD_SNAKE}/${NEW_SNAKE}/g" "$file"
    echo "  ✏️  $file"
done

echo ""
echo "✅ Listo (${#FILES[@]} archivos). Revisá el diff antes de commitear: git diff"
echo "   Pendiente a mano: rutas de deploy en .github/workflows y los secrets del repo."
