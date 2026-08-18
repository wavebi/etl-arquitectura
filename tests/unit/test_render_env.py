"""Render del .env: es el reemplazo de 1Password y lo usa el deploy de CI."""

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("render_env", REPO_ROOT / ".deploy" / "render_env.py")
render_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render_env)


def test_resuelve_variables_del_entorno():
    rendered, missing = render_env.render("DB_HOST=${DB_HOST}\n", {"DB_HOST": "db.interno"})
    assert rendered == "DB_HOST=db.interno\n"
    assert missing == []


def test_usa_el_default_cuando_falta():
    rendered, missing = render_env.render("PORT=${DB_PORT:-5432}\n", {})
    assert rendered == "PORT=5432\n"
    assert missing == []


def test_default_vacio_es_valido():
    """Los opcionales (Telegram) se declaran como ${VAR:-} y quedan vacíos."""
    rendered, missing = render_env.render("TOKEN=${TELEGRAM_BOT_TOKEN:-}\n", {})
    assert rendered == "TOKEN=\n"
    assert missing == []


def test_reporta_las_requeridas_que_faltan():
    _, missing = render_env.render("A=${A}\nB=${B}\n", {"A": "1"})
    assert missing == ["B"]


def test_variable_vacia_en_el_entorno_cuenta_como_faltante():
    """Un secret sin valor en GitHub llega como string vacío: no sirve."""
    _, missing = render_env.render("A=${A}\n", {"A": ""})
    assert missing == ["A"]


def test_el_tpl_local_arranca_con_los_defaults():
    """`make env-init && make up` tiene que funcionar sin configurar nada."""
    tpl = (REPO_ROOT / ".env.local.tpl").read_text()
    _, missing = render_env.render(tpl, {})
    assert missing == [], f".env.local.tpl no debería requerir variables: faltan {missing}"


def test_los_dos_entornos_declaran_las_mismas_variables():
    """Cada .env es autocontenido: si una variable existe en uno y no en el otro, en
    algún entorno el proceso arranca sin ella."""
    import re

    def variables(nombre):
        texto = (REPO_ROOT / nombre).read_text()
        return {m.group(1) for m in re.finditer(r"^([A-Z][A-Z0-9_]*)=", texto, re.M)}

    local = variables(".env.local.tpl")
    prod = variables(".env.prod.tpl")

    # Producción no publica puertos en el host ni monta el repo: esas variables son
    # exclusivas del entorno local.
    #
    # Las credenciales de admin y las de los roles de solo lectura SÍ están en los
    # dos: desde que el deploy aplica scripts/init_db_permissions.sql, producción
    # también crea roles y necesita el mismo contrato que dev.
    solo_local = {
        "POSTGRES_PORT",
        "PREFECT_UI_PORT",
        "DBT_DOCS_PORT",
        "DOCKER_UID",
        "DOCKER_GID",
    }
    # En local no hay imagen publicada: el compose de dev compila desde el repo.
    solo_prod = {"ETL_IMAGE"}

    assert local - prod == solo_local, f"diferencia inesperada en local: {local - prod}"
    assert prod - local == solo_prod, f"diferencia inesperada en prod: {prod - local}"


def test_el_contrato_de_prod_cubre_lo_que_usa_su_compose():
    """Si el compose interpola una variable que el .tpl no declara, el deploy levanta
    con ese valor vacío y el error aparece recién en runtime."""
    import re

    compose = (REPO_ROOT / ".deploy" / "prod" / "docker-compose.yml").read_text()
    usadas = set(re.findall(r"\$\{([A-Z][A-Z0-9_]*)", compose))
    declaradas = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", (REPO_ROOT / ".env.prod.tpl").read_text(), re.M))

    assert usadas <= declaradas, f"el compose de prod usa variables sin declarar: {usadas - declaradas}"


def test_la_zona_horaria_esta_en_los_dos_entornos():
    """Es la variable que alinea contenedores, base, dlt y Prefect: no puede faltar."""
    for nombre in (".env.local.tpl", ".env.prod.tpl"):
        assert "TIMEZONE=" in (REPO_ROOT / nombre).read_text(), f"{nombre} sin TIMEZONE"


def test_el_tpl_de_prod_declara_la_db_como_requerida():
    """En producción no hay defaults que adivinar: si falta algo, el deploy corta."""
    tpl = (REPO_ROOT / ".env.prod.tpl").read_text()
    _, missing = render_env.render(tpl, {})
    assert {"DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD", "PREFECT_DB_PASSWORD"} <= set(missing)


def test_from_json_pisa_el_entorno(tmp_path, monkeypatch):
    json_file = tmp_path / "secrets.json"
    json_file.write_text(json.dumps({"DB_HOST": "desde-secrets", "github_token": {"no": "string"}}))
    monkeypatch.setenv("DB_HOST", "desde-entorno")

    env = render_env._load_env(["render_env.py", "t", "o", "--from-json", str(json_file)])
    assert env["DB_HOST"] == "desde-secrets"
    assert "github_token" not in env
