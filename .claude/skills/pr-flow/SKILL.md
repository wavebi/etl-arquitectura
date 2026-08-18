---
name: pr-flow
description: Llevar un cambio de etl-arquitectura desde una rama feat/* hasta producción — PR a dev, PR a main, release y deploy. Usar cuando el usuario diga "hacé el PR", "subilo a dev", "llevalo a prod", "mergealo" o pida promover cambios. Incluye los gotchas de las reglas de rama, de Prefect y de release-please que ya nos costaron tiempo.
allowed-tools: Bash
---

# Del cambio a producción — etl-arquitectura

Flujo obligatorio: **`feat/* → dev → main → tag → deploy`**. A `dev` y a `main` solo se
entra por PR; las reglas están en `scripts/setup_branch_protection.sh` y son reales
(rulesets activos, `bypass_actors = 0`: ni los admins las saltean).

> **Regla de oro**: el deploy lo dispara el **tag** que crea release-please, **no** el
> merge a `main`. Y ese tag dispara `deploy.yml` **solo si** el token es un PAT
> (`GH_PAT_RELEASE`): con el `GITHUB_TOKEN` los tags no disparan workflows.

---

## 1. Rama y commits

```bash
git fetch origin && git checkout -b feat/<descripcion-corta> origin/dev
```

Los commits, con el skill `git-commit` (acordate de exportar `.env.local`, o el
pre-commit falla al lintear SQL).

Antes de pushear:

```bash
set -a; . ./.env.local; set +a
./venv/bin/ruff check src/ tests/ scripts/
PYTHONPATH=src ./venv/bin/python -m pytest tests/ -q -m "not live"
```

Los de integración necesitan el Postgres del compose (`make up`) y **corren desde el
host**, no dentro del contenedor: el conftest apunta a `localhost:5442`, que es el mapeo
del host. Adentro se saltean sin avisar.

---

## 2. PR a `dev`

```bash
git push -u origin feat/<...>
gh pr create --base dev --head feat/<...> --title "<tipo>: <descripción>" --body "..."
```

El cuerpo explica **por qué** y **qué se verificó**. Si el cambio salió de un
comportamiento raro de una herramienta o del origen, ponelo con la fecha.

### Los cuatro checks

| Check | Cuándo corre |
|---|---|
| `test` | siempre — **es el único requerido** por las reglas de rama |
| `commitlint` | siempre |
| `validate-flow` | siempre (Branch Flow Police) |
| `build` | **solo** si el PR toca `.deploy/`, `requirements/` o `.dockerignore` |

`build` construye la imagen y corre los tests adentro. Si tu PR cambia el Dockerfile o
las dependencias y el check no aparece, revisá el filtro de paths en
`.github/workflows/docker-build.yml`.

### Gotchas de los PR

**`BEHIND` no es un error.** Los rulesets tienen
`strict_required_status_checks_policy: true`: el PR tiene que estar al día con la base.
Cuando `dev` avanza, el tuyo queda `BEHIND`. Resolvelo con **rebase**, no con
`gh pr update-branch`, que mete un merge commit:

```bash
git fetch origin && git rebase origin/dev && git push --force-with-lease
```

**`gh run rerun` no sirve para revalidar contra una base nueva**: repite el mismo SHA, o
sea el mismo merge ref viejo. Si mergeaste algo a `dev` que arregla el check de otro PR,
ese PR necesita un evento nuevo (rebase y push). Para los de Dependabot:

```bash
gh pr comment <n> --body "@dependabot rebase"
```

**Un PR verde de Dependabot no garantiza nada sobre la imagen** si no corrió `build`.
Un bump de la base de Python puede pasar `test` porque el CI instala su propio
intérprete. Ante la duda, construí y probá a mano antes de mergear.

Merge: **squash**, y borrá la rama.

```bash
gh pr merge <n> --squash --delete-branch
```

---

## 3. PR de `dev` a `main`

```bash
gh pr create --base main --head dev --title "..." --body "..."
```

`validate-flow` bloquea cualquier cosa que no venga de `dev` o de `release-please-*`, y
también el ciclo inverso (`main` → `dev`).

---

## 4. Release y deploy

Al mergear a `main`, **release-please** abre sola una PR `chore(main): release X.Y.Z`.
Mergear **esa** PR crea el tag y dispara `deploy.yml`.

**Antes de mergear la Release PR, verificá que producción exista de verdad:**

```bash
gh api repos/wavebi/etl-arquitectura/environments --jq '.environments[]?.name'
gh api repos/wavebi/etl-arquitectura/actions/organization-secrets --jq '.secrets[].name'
```

El Environment `prod` necesita, además de lo que ya usaba el compose:

| Secret | Para qué |
|---|---|
| `PG_ADMIN_USER` / `PG_ADMIN_PASSWORD` | el paso *Aplicar permisos de la base* |
| `BI_READER_PASSWORD` / `ANALYST_PASSWORD` | crear los roles de solo lectura |
| `GH_PAT_RELEASE` (nivel repo/org) | que el tag de release dispare el deploy |

Mergear la Release PR sin el Environment armado **lanza un deploy que falla**.

### Qué hace el deploy

1. Corre la suite (`test.yml`).
2. Construye y publica la imagen a GHCR, tageada con el release.
3. Copia **solo** los archivos de compose al servidor (el código viaja en la imagen).
4. **Aplica los permisos de la base** (`scripts/apply_db_permissions.sh`) — antes de
   levantar el stack, para que un schema o grant nuevo esté listo cuando arranque el
   worker.
5. `docker compose up -d`.

Rollback: apuntar a la imagen anterior y levantar.

```bash
ETL_IMAGE=ghcr.io/wavebi/etl-arquitectura:<tag-anterior> docker compose up -d
```

---

## 5. Después de tocar deployments de Prefect

**`prefect.deploy()` NO borra los deployments que dejaste de declarar.** Si renombraste
o sacaste alguno, quedan zombis en la UI hasta que los borres a mano:

```bash
docker compose -f .deploy/dev/docker-compose.yml exec -T etl-worker python -c "
import asyncio
from prefect.client.orchestration import get_client
VIGENTES = {'frankfurter-currencies','frankfurter-rates','frankfurter-rates-reconcile','dbt-docs','health-check'}
async def main():
    async with get_client() as c:
        for d in await c.read_deployments():
            if d.name not in VIGENTES:
                await c.delete_deployment(d.id); print('borrado:', d.name)
asyncio.run(main())
"
```

Borrá **deployments**, no flows: los flows conservan el historial de corridas.

Recordá que los schedules solo se activan con `ENV=prod` (`settings.is_prod`), así que en
dev los deployments se registran sin cron. Es lo esperado, no un bug.

---

## Checklist

- [ ] Rama `feat/*` desde `origin/dev`
- [ ] `.env.local` exportado antes de commitear
- [ ] `ruff` y tests en verde localmente
- [ ] PR a `dev` con el porqué y lo verificado
- [ ] Los cuatro checks (o los tres, si no toca la imagen)
- [ ] Squash + borrar rama
- [ ] PR `dev` → `main`
- [ ] Environment `prod` con sus secrets **antes** de la Release PR
- [ ] Deployments zombis borrados, si cambiaron
