#!/usr/bin/env bash
# Configura las reglas de rama del repositorio con la API de GitHub.
#
# Deja el flujo obligatorio:  feature/* --PR--> dev --PR--> main
#
#   - No se puede pushear directo ni a `dev` ni a `main`: SIEMPRE por Pull Request.
#   - No se puede forzar el push ni borrar esas ramas.
#   - Un PR no se puede mergear si el check `test` no está en verde.
#   - Un PR tiene que estar actualizado con la rama destino antes de mergear. Esto
#     es lo que hace que el check del PR valga como verificación POST-merge: el
#     árbol que se testea es el mismo que va a quedar en la rama.
#   - A `main` solo se entra desde `dev` (o desde release-please). Eso lo verifica
#     además el workflow "Branch Flow Police", porque las reglas de GitHub no
#     pueden expresar "solo desde tal rama".
#
# Requiere el CLI `gh` autenticado con permisos de admin sobre el repo.
#
# Uso:
#   bash scripts/setup_branch_protection.sh                 # 1 aprobación en main, 0 en dev
#   APROBACIONES_MAIN=0 bash scripts/setup_branch_protection.sh   # equipo de una persona
set -euo pipefail

APROBACIONES_MAIN="${APROBACIONES_MAIN:-1}"
APROBACIONES_DEV="${APROBACIONES_DEV:-0}"
CHECK_REQUERIDO="${CHECK_REQUERIDO:-test}"

command -v gh >/dev/null 2>&1 || { echo "❌ Falta el CLI gh: https://cli.github.com"; exit 1; }

REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
echo "Configurando reglas en $REPO"

crear_ruleset() {
    local rama="$1" aprobaciones="$2"
    echo "  → ruleset para '$rama' (aprobaciones requeridas: $aprobaciones)"

    # Si ya existe un ruleset con el mismo nombre, se borra y se recrea: así el
    # script es idempotente y la configuración vive en el repo, no en la memoria de
    # quien la hizo a mano.
    local existente
    existente=$(gh api "repos/$REPO/rulesets" --jq \
        ".[] | select(.name == \"proteger-$rama\") | .id" 2>/dev/null || true)
    if [ -n "$existente" ]; then
        gh api -X DELETE "repos/$REPO/rulesets/$existente" >/dev/null
    fi

    gh api -X POST "repos/$REPO/rulesets" --input - >/dev/null <<JSON
{
  "name": "proteger-$rama",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": { "include": ["refs/heads/$rama"], "exclude": [] }
  },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": $aprobaciones,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true,
        "allowed_merge_methods": ["squash", "merge"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": true,
        "required_status_checks": [{ "context": "$CHECK_REQUERIDO" }]
      }
    }
  ]
}
JSON
}

crear_ruleset main "$APROBACIONES_MAIN"
crear_ruleset dev "$APROBACIONES_DEV"

echo ""
echo "✅ Listo. Reglas activas:"
gh api "repos/$REPO/rulesets" --jq '.[] | "  - \(.name): \(.enforcement)"'
echo ""
echo "Verificá que el nombre del check requerido ('$CHECK_REQUERIDO') coincida con el"
echo "job de .github/workflows/test.yml, o los PR van a quedar bloqueados esperando"
echo "un check que nunca llega."
