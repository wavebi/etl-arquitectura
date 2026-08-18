---
name: git-commit
description: Commitear en etl-arquitectura con Conventional Commits en español, pasando el pre-commit a la primera. Usar cuando el usuario diga "commiteá", "hacé un commit", "/commit", o pida guardar cambios en git. Incluye la trampa del entorno que hace fallar a sqlfluff y las reglas de commitlint que rechazan mensajes que parecen correctos.
allowed-tools: Bash
---

# Commits en etl-arquitectura

Conventional Commits, **mensajes en español** (ver CLAUDE.md § Convenciones). El repo
tiene pre-commit con cinco hooks y commitlint en CI: un commit mal armado se rechaza
localmente, y si se cuela, rompe el check del PR.

---

## ⚠️ Lo primero: exportá el entorno o el commit falla

**`git commit` a secas falla** en este repo si tocaste SQL o modelos de dbt:

```
sqlfluff-lint............................................................Failed
User Error: dbt failed during project compilation.
  Env var required but not provided: 'DB_HOST'
```

No es un error de tu SQL. `sqlfluff` usa el **templater de dbt** (ver `.sqlfluff`), así
que para lintear tiene que *compilar* el proyecto, y para eso necesita las variables de
conexión. Siempre commiteá así:

```bash
set -a; . ./.env.local; set +a
git commit -m "..."
```

Le pasa lo mismo a `make sqlfmt`. Si no existe `.env.local`, corré `make env-init`.

---

## Antes de commitear

```bash
git status --short
git diff --staged        # o `git diff` si no hay nada en stage
```

**Mirá lo que no reconozcas.** Si aparece un archivo que no creaste vos, abrilo antes.

**Nunca commitees secretos.** Los `.env` están gitignoreados (solo los `.env.*.tpl` se
commitean, y son el contrato sin valores). El hook de `gitleaks` es la última red, no la
primera: no dependas de él.

Verificación rápida de que no se cuela nada grande ni indebido:

```bash
git add -A --dry-run | grep -iE "\.env($|\.)|venv/|\.dlt/|logs/|dbt_packages/"
```
No debería devolver nada salvo los `.tpl`.

---

## El mensaje

```
<tipo>[scope]: <descripción en minúscula, imperativo, < 72 chars>

<cuerpo: por qué, no qué. Líneas de hasta 200 chars.>

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
```

| Tipo | Cuándo |
|---|---|
| `feat` | funcionalidad nueva |
| `fix` | corrección de un bug |
| `docs` | solo documentación |
| `refactor` | reestructura sin cambiar comportamiento |
| `perf` | performance |
| `test` | tests |
| `build` | dependencias, Dockerfile |
| `ci` | workflows, hooks, linters |
| `chore` | mantenimiento |

Scopes que se usan acá: `ingestion`, `orchestration`, `dbt`, `deploy`, `dev`, `ci`, `docs`.

### Dos reglas de commitlint que rechazan mensajes que parecen bien

1. **`subject-case`: el asunto NO puede empezar con mayúscula.**
   ```
   ✖  feat: Agrega el pipeline de cotizaciones     ← rechazado (sentence-case)
   ✔  feat: agrega el pipeline de cotizaciones
   ```
   Es exactamente lo que hacía fallar a los PR de Dependabot (`ci(deps): Bump python...`).
   Por eso `.commitlintrc.cjs` los excluye por su firma — pero a vos sí te aplica.

2. **`body-max-line-length: 200`** (relajado respecto del default de 100).

Podés validar un mensaje sin commitear:

```bash
echo "feat: agrega el pipeline" | npx --yes commitlint
```

### Qué va en el cuerpo

Este repo documenta **por qué**, no qué. El diff ya dice qué cambió. El cuerpo sirve
para lo que no se deduce leyendo el código: qué alternativa se descartó, qué se
verificó, qué invariante de CLAUDE.md está en juego. Si el cambio nació de un
comportamiento raro del origen o de una herramienta, decilo con la fecha en que se
verificó.

**Un commit por intención.** Si el working tree mezcla dos temas, van en dos commits:

```bash
git add archivo1 archivo2 && git commit -m "fix(ci): ..."
git add archivo3        && git commit -m "docs: ..."
```

---

## Cuando el hook rechaza

Los cinco hooks son `ruff`, `ruff format`, `sqlfluff-lint`, `sqlfluff-fix`, `gitleaks`,
más `commitlint` en `commit-msg`.

- `ruff format` y `sqlfluff-fix` **modifican archivos**. Si fallan por eso, revisá el
  cambio, `git add` de nuevo y volvé a commitear.
- Si falla por el entorno, es lo de arriba: exportá `.env.local`.
- **Nunca uses `--no-verify`** salvo que el usuario lo pida explícitamente. Los hooks son
  la razón de que el CI casi nunca falle por lint.
- Si el commit ya se hizo y falló algo, hacé un commit **nuevo**; no uses `--amend` sobre
  algo ya pusheado.

---

## Reglas de seguridad

- Nunca `git config`, ni `--force`, ni `reset --hard` sin pedido explícito.
- **Nunca pushear directo a `dev` ni a `main`**: las reglas de rama lo bloquean (y con
  razón — ver el skill `pr-flow`). Se entra siempre por PR desde `feat/*`.
- `push --force-with-lease` sí es válido sobre una rama `feat/*` propia, típicamente
  después de un rebase.
