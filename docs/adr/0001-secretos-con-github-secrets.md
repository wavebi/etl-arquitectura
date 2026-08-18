# ADR 0001 — Secretos con GitHub Secrets en vez de 1Password CLI

- **Fecha:** 2026-08-18
- **Estado:** aceptado
- **Contexto:** arquitectura base de ETLs

## Contexto

Los ETLs anteriores del equipo resuelven los secretos con 1Password CLI: los
`.env.tpl` contienen referencias `op://vault/item/campo` y `op inject` las resuelve,
tanto en la máquina del desarrollador como en CI (con un Service Account token).

Para esta arquitectura base se decidió usar **GitHub Secrets**.

Consecuencias del esquema anterior que motivaron el cambio:

- Cada entorno de cada cliente necesita un vault y un Service Account de
  1Password, con su token en el repo. Es una dependencia externa más para dar de
  alta y rotar, por proyecto.
- El desarrollador necesita `op` instalado y autenticado para hacer `make up`. En
  la práctica es fricción de onboarding.
- Los secretos de deploy ya viven en GitHub de todas formas (el token de
  1Password entre ellos), así que 1Password no eliminaba a GitHub del perímetro de
  confianza: lo sumaba.

## Decisión

1. El repo guarda el **contrato** de variables en `.env.<entorno>.tpl` —uno por
   entorno, completo— con placeholders `${VAR}` (requerida) y `${VAR:-default}`
   (opcional).
2. `.deploy/render_env.py` resuelve el contrato contra variables de entorno y
   **falla** si falta una requerida.
3. En CI, el composite action `run-compose` le pasa `toJSON(secrets)` del GitHub
   Environment correspondiente, escribe los `.env` con permisos 600 y los borra en
   un paso `always()`.
4. En local, `make env-init` genera el `.env.<entorno>` desde el contrato y el
   desarrollador completa los valores a mano. Los archivos están gitignoreados.

## Consecuencias

**A favor**

- Un solo lugar donde viven los secretos de CI, con los Environments de GitHub
  como frontera de permisos (quién puede deployar a prod).
- Onboarding sin dependencias: `make setup && make env-init && make up`.
- `toJSON(secrets)` desacopla el workflow del contrato: agregar una variable no
  requiere editar YAML de CI.

**En contra**

- Los secretos de producción quedan solo en GitHub: si hay que rotarlos, se hace
  ahí (no hay una fuente de verdad compartida con el resto de la organización).
- No hay auditoría de accesos a nivel secreto como la que da 1Password.
- En local los secretos quedan en un archivo en disco (600, gitignoreado) en vez
  de resolverse en memoria en cada `up`.

**Mitigaciones**

- `.gitignore` cubre `.env` y `.env.*` (con excepción explícita para `.env.tpl`), y
  el hook de `gitleaks` corre en pre-commit.
- `.claude/settings.json` tiene los `.env` en `deny` para que los agentes no los lean.
- Si a futuro hace falta auditoría o rotación centralizada, el punto de cambio es
  uno solo: `render_env.py` puede resolver desde otro backend sin tocar los
  contratos ni los compose.
