#!/usr/bin/env python3
"""Renderiza un `.env.<entorno>.tpl` a un `.env.<entorno>` resolviendo `${VAR}`.

Es el reemplazo de `op inject` (1Password): acá los valores llegan como variables
de entorno, que en CI vienen de los GitHub Secrets del Environment correspondiente.

Sintaxis soportada en el template:
    VAR=${OTRA}              → requerida: si no está en el entorno, falla.
    VAR=${OTRA:-default}     → opcional: si no está, usa el default (puede ser vacío).

Uso:
    python3 .deploy/render_env.py .env.prod.tpl /ruta/al/.env.prod
    python3 .deploy/render_env.py .env.prod.tpl /ruta/al/.env.prod --from-json secrets.json
    python3 .deploy/render_env.py .env.local.tpl .env.local --skip-missing

`--from-json` lee un objeto JSON plano {"VAR": "valor"} y lo superpone al entorno.
Es lo que usa el composite action de deploy: le pasa `toJSON(secrets)` del
GitHub Environment, así no hay que enumerar cada secreto en el workflow.

`--skip-missing` no falla ante variables requeridas sin valor: las deja vacías y
las lista por stderr. Es lo que usa `make env-init` para generar el esqueleto del
.env local que el dev completa a mano.

El archivo de salida se escribe con permisos 600 (solo el dueño lo lee).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# ${NAME} | ${NAME:-default}
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def render(template: str, env: dict[str, str]) -> tuple[str, list[str]]:
    """Devuelve (texto renderizado, lista de variables requeridas que faltan).

    Las líneas de comentario se copian tal cual: los `${VAR}` que aparecen en la
    documentación del propio template no son variables a resolver.
    """
    missing: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        if name in env and env[name] != "":
            return env[name]
        if default is not None:
            return default
        missing.append(name)
        return ""

    rendered_lines = [
        line if line.lstrip().startswith("#") else _PLACEHOLDER.sub(_sub, line)
        for line in template.splitlines(keepends=True)
    ]
    return "".join(rendered_lines), sorted(set(missing))


def _load_env(argv: list[str]) -> dict[str, str]:
    """Entorno del proceso, con los valores de `--from-json` pisando por encima."""
    env = dict(os.environ)
    if "--from-json" in argv:
        json_path = Path(argv[argv.index("--from-json") + 1])
        data = json.loads(json_path.read_text(encoding="utf-8"))
        # Los secrets de GitHub llegan siempre como string; ignoramos cualquier
        # otro tipo por las dudas (y GITHUB_TOKEN, que no se usa en los .env).
        env.update({k: v for k, v in data.items() if isinstance(v, str)})
    return env


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(f"uso: {argv[0]} <ruta .env.tpl> <ruta salida .env> [--from-json <archivo>]", file=sys.stderr)
        return 2

    tpl_path, out_path = Path(argv[1]), Path(argv[2])
    rendered, missing = render(tpl_path.read_text(encoding="utf-8"), _load_env(argv))

    if missing and "--skip-missing" in argv:
        print(
            "⚠️  Quedaron vacías (completalas a mano):\n  - " + "\n  - ".join(missing),
            file=sys.stderr,
        )
        missing = []

    if missing:
        print(
            f"ERROR: faltan {len(missing)} variables requeridas por {tpl_path}:\n  - "
            + "\n  - ".join(missing)
            + "\n\nEn CI: agregalas como secrets del GitHub Environment.\n"
            "En local: exportalas o completá el .env a mano (make env-init).",
            file=sys.stderr,
        )
        return 1

    out_path.write_text(rendered, encoding="utf-8")
    out_path.chmod(0o600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
