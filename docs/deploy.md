# Deploy, entornos y secretos

## Entornos

| | dev | prod |
|---|---|---|
| Rama | `feature/*`, `dev` | tag de release desde `main` |
| Corre en | máquina del desarrollador (Docker) | servidor (runner self-hosted) |
| Compose | `.deploy/dev/docker-compose.yml` | `.deploy/prod/docker-compose.yml` |
| Warehouse | Postgres del compose | Postgres managed externa |
| Prefect UI | `localhost:4210` | `localhost:4200` vía túnel SSH |
| dbt docs | `localhost:8085` | no se publica |
| Schedules | no | **sí** |
| Secretos | `.env.local` (gitignoreado) | GitHub Environment `prod` |

No hay entorno de staging: se eliminó del proyecto.

## Secretos

No hay gestor externo. Los valores viven en **GitHub Secrets** por Environment, y el
repo solo guarda el **contrato** de variables.

```
.env.local.tpl    contrato de desarrollo   ┐ SE COMMITEAN. Solo referencias ${VAR},
.env.prod.tpl     contrato de producción   ┘ sin ningún valor real.
       │
       │   .deploy/render_env.py  (resuelve desde el entorno o desde los secrets)
       ▼
.env.local        → desarrollo   ┐ NO se commitean (están en .gitignore).
.env.prod         → producción   ┘ En CI se generan y se borran en el mismo job.
```

**¿Para qué sirven los `.tpl` si al final se usa el `.env`?** Porque el `.env` no se
puede commitear (tiene credenciales) y sin el `.tpl` la lista de variables que el
proyecto necesita no viviría en ningún lado versionado: estaría en la máquina de
quien armó el proyecto y en la memoria de quien lo mantiene. El `.tpl` es el
contrato —qué variables existen, cuáles son obligatorias, qué default tienen y para
qué sirven— y es lo que le permite al CI generar el archivo real a partir de los
secrets de GitHub.

**Un archivo por entorno, completo.** No hay cascada ni archivo base: `.env.local` y
`.env.prod` tienen cada uno TODAS sus variables. Es un poco de repetición a cambio
de que lo que ves en el archivo sea exactamente lo que recibe el proceso, sin tener
que resolver mentalmente qué pisa a qué. Un test
(`tests/unit/test_render_env.py`) verifica que los dos declaren el mismo conjunto de
variables, salvo las que son exclusivas del entorno local (puertos publicados, UID).

Sintaxis del contrato:

```bash
DB_HOST=${DB_HOST}                            # requerida: si falta, el render FALLA
DB_PORT=${DB_PORT:-5432}                      # opcional con default
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}    # opcional, puede quedar vacía
```

Que el render falle ante una variable requerida ausente es deliberado: es mejor que
el deploy corte con "falta DB_PASSWORD" a que el contenedor arranque con la
contraseña vacía y falle 40 segundos después con un error de autenticación.

### En local

```bash
make env-init     # genera .env.local y .env.prod resolviendo los defaults
```

Los defaults de desarrollo apuntan al Postgres del compose, así que `make up`
funciona sin configurar nada. El único bloque que conviene completar a mano es el de
Telegram, si querés notificaciones.

### En CI

El composite action `.github/actions/run-compose` recibe **todos** los secrets del
Environment de una sola vez:

```yaml
- uses: ./.github/actions/run-compose
  with:
    secrets_json: ${{ toJSON(secrets) }}
    environment: prod
    compose_file: .deploy/prod/docker-compose.yml
    compose_args: "up -d --build --remove-orphans"
    working_directory: /opt/etl-arquitectura/app/prod
```

`toJSON(secrets)` evita enumerar cada variable en el workflow: agregar un secreto
nuevo es cargarlo en el Environment y declararlo en el `.tpl`, sin tocar el YAML del
workflow. Los archivos renderizados se borran en un paso `always()`.

### Qué protege este esquema y qué no

Vale la pena tenerlo explícito, porque "los secretos están seguros" no significa nada
sin decir contra qué.

**Protege** (verificado, no asumido):

| Riesgo | Cómo se corta |
|---|---|
| Secreto commiteado por error | `.gitignore` cubre `.env*` salvo los `.tpl`; `gitleaks` corre en pre-commit; los `.tpl` no tienen valores |
| Secreto dentro de la imagen | El `.dockerignore` excluye todo `.env*`. Importa porque la imagen se publica en un registry: se verificó que no contiene ningún `.env` ni variables sensibles horneadas |
| Secreto en los logs del CI | GitHub enmascara los valores de sus secrets; el paso de render solo imprime la cantidad de variables, nunca su contenido |
| Lectura del archivo por otro usuario del servidor | `.env.prod` con permisos `600` |
| Deploy desde código no revisado | Los secrets viven en el GitHub Environment `prod`; con las reglas de rama, solo llega ahí código mergeado por PR |
| Credencial de BI filtrada | `bi_reader` solo ve `marts` y `seeds`: no puede leer `raw` ni escribir nada. Ningún rol del proyecto es superuser |

**NO protege** (es inherente al modelo, no un descuido):

- **Quien tenga acceso al servidor con permiso de docker tiene los secretos.** No por
  el archivo: `docker inspect <container>` muestra todas las variables de entorno en
  claro. Y pertenecer al grupo `docker` equivale a ser root en esa máquina. Borrar el
  `.env.prod` no cambiaría esto en nada — solo rompería el rollback.
- **El runner self-hosted corre en el servidor de producción.** Quien pueda mergear un
  cambio en un workflow puede ejecutar código ahí. Hoy lo acota que a `main` solo se
  entra por PR, pero es el punto más fuerte del modelo de amenaza.
- **No hay rotación ni auditoría**: nadie registra quién leyó qué secreto ni cuándo se
  cambió por última vez.

**Si hace falta subir el nivel**, en orden de impacto sobre costo:

1. **Sacar el runner del servidor de producción**: que el deploy corra en un runner
   hosted y llegue por SSH. Elimina "ejecutar código arbitrario en prod desde un PR",
   que es el riesgo más grande.
2. **Restringir el grupo `docker`** del servidor a quienes realmente lo necesiten.
3. **Rotar credenciales** periódicamente (los roles ya están segregados, así que
   rotar el de BI no toca al del ETL).
4. **Verificar que el package de GHCR sea privado.** Con repo privado lo es por
   defecto, pero conviene confirmarlo: la imagen contiene el código del proyecto
   (secretos no, eso está verificado).
5. **Gestor de secretos con auditoría** (tipo Vault o 1Password). No elimina la
   exposición vía `docker inspect` —el proceso necesita las credenciales igual—, pero
   agrega rotación y traza de accesos.

### Alta de un secreto nuevo

1. Declararlo en **los dos** `.tpl` (`.env.local.tpl` y `.env.prod.tpl`).
2. Cargarlo en el GitHub Environment `prod`
   (*Settings → Environments → prod → Secrets*).
3. Agregarlo a tu `.env.local`.
4. Si el código lo lee, declararlo en `shared/settings.py` como `SecretStr`.

### Secretos a nivel repositorio (no de Environment)

| Secreto | Para qué |
|---|---|
| `GH_PAT_RELEASE` | release-please: un PAT (no `GITHUB_TOKEN`) para que el tag que crea dispare el workflow de deploy |

## Base de datos: roles y permisos

`scripts/init_db_permissions.sql` es idempotente y crea schemas, roles y permisos.
En desarrollo lo corre solo el init del contenedor; en producción se corre una vez
contra la base managed, como superuser:

```bash
psql -h <host> -U <superuser> -d <base> \
  -v etl_password=... -v prefect_password=... \
  -v bi_password=... -v analyst_password=... \
  -f scripts/init_db_permissions.sql
```

Roles: `etl_app` (dlt y dbt), `prefect_app` (el orquestador, con su propio schema y
`search_path`), `bi_reader` (solo `marts` y `seeds`) y `analyst` (lectura de todas
las capas). Ver la sección de arquitectura para el porqué de cada uno.

## Flujo de ramas y deploy

```
feature/* ──PR──▶ dev ──PR──▶ main ──▶ tag ──▶ deploy a producción
                   │           │
                   │           └─ release-please abre la Release PR
                   └─ Test + dbt CI en cada PR
```

**A `dev` y a `main` no se puede pushear directo.** Lo garantizan las reglas del
repositorio, que se configuran una sola vez con:

```bash
bash scripts/setup_branch_protection.sh
```

Ese script crea un ruleset por rama que:

- exige Pull Request (bloquea el push directo);
- bloquea el force-push y el borrado de la rama;
- exige que el check `test` esté en verde;
- exige que el PR esté **actualizado con la rama destino** antes de mergear.

El workflow *Branch Flow Police* agrega la regla que GitHub no sabe expresar: a `main`
solo se entra desde `dev` (o desde una rama de release-please).

### Por qué el CI no repite verificaciones

Con esas reglas activas, correr la suite en cada `push` a `dev` sería pagar dos veces
por lo mismo: como el PR tiene que estar actualizado con la rama destino, **el árbol
que se testea en el PR es el mismo que queda en la rama al mergear**. Por eso:

| Momento | Qué corre | Por qué |
|---|---|---|
| PR → `dev` | ruff + tests unitarios + dbt build completo (si cambió `src/dbt/`) | es donde se verifica el código |
| PR → `dev`/`main` | commitlint + Branch Flow Police | historial semántico y flujo de ramas |
| PR `dev` → `main` | ruff + tests unitarios | `main` puede tener commits que `dev` no (los de release-please), así que el árbol resultante no es idéntico al ya probado |
| push a `dev`/`main` | **nada** | es imposible pushear directo; lo que llega es un merge ya verificado |
| tag | tests + deploy | última red antes de producción |

Lo que sí conviene NO recortar: los **tests de datos** (`dbt test`) que corren dentro
del ETL en cada ejecución. Esos no validan código sino datos, que cambian todos los
días — un PR verde no dice nada sobre lo que el origen publicó esta mañana.

Además, todos los workflows cancelan corridas superadas (`concurrency` con
`cancel-in-progress`), así que empujar tres commits seguidos a un PR consume una sola
corrida y no tres.

### Workflows

| Workflow | Dispara con | Qué hace |
|---|---|---|
| `test.yml` | PR a `dev` o `main` | ruff + pytest unitarios con coverage mínimo |
| `dbt-ci.yml` | PR que toca `src/dbt/**` | carga un fixture de `raw` y corre `dbt build` completo + sqlfluff contra un Postgres de servicio |
| `commit-lint.yml` | PR | Conventional Commits y título del PR |
| `check-branch-rules.yml` | PR | valida el flujo de ramas |
| `release.yml` | push a `main` | release-please: Release PR y tag |
| `deploy.yml` | tag `etl-arquitectura-v*` / manual | rsync al servidor + `compose up -d --build` |
| `changelog.yml` | release publicada | actualiza el CHANGELOG en `main` |

Además, `dependabot.yml` abre PRs semanales con las actualizaciones de
dependencias (y mensuales para actions e imágenes de Docker), apuntados a `dev` y
con los majors de dbt, Prefect y dlt excluidos para que se planifiquen a mano.

### Qué se despliega: una imagen, no el código

El CI **construye la imagen una sola vez** y la publica en GHCR con el tag del
release. Al servidor solo van los archivos de compose (dos archivos), y el
`docker compose up -d` baja esa imagen.

```
tag  ──▶  docker build --target prod  ──▶  ghcr.io/<owner>/<repo>:<tag>
                                                    │
                        rsync de .deploy/prod/  ─────┼──▶  servidor
                                                    ▼
                                        docker compose up -d
```

Por qué así y no sincronizando el repo al servidor: la imagen ya **contiene** el
código (`COPY . /app` en el Dockerfile), así que la copia del fuente en `/opt` no se
usaba en runtime — servía únicamente como contexto de build. Sacarla trae tres cosas:

- **Rollback real**: volver a la versión anterior es apuntar a otro tag, sin
  reconstruir código viejo ni hacer checkout de nada.
  ```bash
  cd /opt/etl-arquitectura/app/prod
  ETL_IMAGE=ghcr.io/<owner>/<repo>:etl-arquitectura-v1.2.3 docker compose up -d
  ```
- **Lo que se probó es lo que corre**: el artefacto es el mismo, no una recompilación
  en otra máquina y en otro momento.
- **Menos superficie en el servidor**: no queda una copia del fuente que alguien
  pueda editar creyendo que eso cambia algo.

Si el registry no está disponible y hay que levantar igual, existe la salida de
emergencia (requiere el fuente en el servidor):

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

La autenticación con GHCR usa el `GITHUB_TOKEN` del propio workflow (permiso
`packages: write`): no hay que crear ningún secreto adicional.

### Qué queda en el servidor

```
/opt/etl-arquitectura/app/prod/
├── .env.prod                       ← generado por el deploy, permisos 600
└── .deploy/prod/
    ├── docker-compose.yml
    └── docker-compose.build.yml
```

Tres archivos. Nada de código fuente.

**El `.env.prod` SÍ queda en el servidor**, y es a propósito. Lo efímero es el JSON
con todos los secrets que manda GitHub: se escribe en un temporal, se usa para
resolver el contrato y se borra en el mismo paso.

Dejar el `.env.prod` no agrega exposición real: los mismos valores ya están en la
configuración del contenedor, y cualquiera con acceso a docker en esa máquina los ve
con `docker inspect`. Lo que sí se gana es poder operar:

```bash
cd /opt/etl-arquitectura/app/prod
docker compose -f .deploy/prod/docker-compose.yml --env-file .env.prod ps
docker compose -f .deploy/prod/docker-compose.yml --env-file .env.prod logs -f
# rollback a una imagen anterior
ETL_IMAGE=ghcr.io/<owner>/<repo>:etl-arquitectura-v1.2.3 \
  docker compose -f .deploy/prod/docker-compose.yml --env-file .env.prod up -d
```

Sin ese archivo, cualquiera de esas operaciones exigiría volver a correr el workflow
de deploy — incluido el rollback, que es justo cuando menos se quiere depender del CI.

El archivo incluye también `ETL_IMAGE`, que lo agrega el deploy: así queda registrado
en el servidor **qué imagen está corriendo** y un `docker compose up -d` manual usa
exactamente la misma.

### Producción: detalles que importan

- **El deploy NO espera a que termine el ETL en curso, y es a propósito.** Medido: con
  una carga histórica corriendo, `docker stop --timeout 3600` devuelve en 0 segundos
  — el worker de Prefect corta apenas recibe SIGTERM. Por eso `stop_grace_period` es
  de 30s: un valor largo prometería una espera que no ocurre. Es seguro porque la
  corrida interrumpida queda en `RUNNING`, el arranque siguiente la cancela
  (`cancel_stale_runs.py`) y la carga es idempotente: el rango se recalcula del estado
  en el destino y el merge por clave natural no duplica.
- `concurrency: deploy-prod` con `cancel-in-progress: false`: nunca se cancela un
  deploy en curso.
- La UI de Prefect escucha en `127.0.0.1`: se accede por túnel SSH, no se publica.
- Después de cada deploy se hace prune de imágenes con más de 7 días, para dejar
  disponibles las recientes por si hay que hacer rollback.

## Primera instalación en un servidor

1. Instalar Docker y registrar el runner self-hosted del repo (labels
   `self-hosted, Linux`).
2. Crear el directorio de deploy: `sudo mkdir -p /opt/etl-arquitectura/app/prod` y
   darle permiso al usuario del runner. Solo va a contener los archivos de compose y
   el `.env.prod`.
3. Correr `scripts/init_db_permissions.sql` contra la base managed.
4. Crear el GitHub Environment `prod` con sus secrets.
5. Disparar el deploy (tag o `workflow_dispatch`).
6. Verificar: `docker compose ps`, el health del worker y el flow
   `health-check` desde la UI de Prefect.
