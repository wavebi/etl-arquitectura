"""Coherencia entre la configuración de dbt y la del código Python.

Son los desajustes que no dan error hasta que un mart aparece vacío: un schema
que existe en dbt pero no en `shared/constants.py`, o un modelo sin YAML.
"""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[2]
DBT_DIR = REPO_ROOT / "src" / "dbt"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_los_schemas_de_dbt_coinciden_con_los_de_python():
    """Los schemas que usa dbt tienen que existir en la base (los crea el init SQL)."""
    from shared.constants import PHYSICAL_SCHEMAS

    project = _load(DBT_DIR / "dbt_project.yml")
    layers = project["models"]["etl_arquitectura"]
    schemas = {config["+schema"] for config in layers.values() if isinstance(config, dict) and "+schema" in config}
    schemas.add(project["snapshots"]["etl_arquitectura"]["+schema"])
    schemas.add(project["seeds"]["etl_arquitectura"]["+schema"])
    assert schemas <= set(PHYSICAL_SCHEMAS), (
        f"schemas de dbt que no crea scripts/init_db_permissions.sql: {schemas - set(PHYSICAL_SCHEMAS)}"
    )


def test_intermediate_no_tiene_schema_propio():
    """Sus modelos son ephemeral: no crean objetos, así que el schema sobraba."""
    project = _load(DBT_DIR / "dbt_project.yml")
    intermediate = project["models"]["etl_arquitectura"]["intermediate"]
    assert intermediate["+materialized"] == "ephemeral"
    assert "+schema" not in intermediate


def test_el_profile_del_proyecto_existe_en_profiles_yml():
    project = _load(DBT_DIR / "dbt_project.yml")
    profiles = _load(DBT_DIR / "profiles.yml")
    assert project["profile"] in profiles


def test_los_targets_estan_definidos():
    """Solo dev y prod: el entorno stg se eliminó del proyecto."""
    profiles = _load(DBT_DIR / "profiles.yml")
    outputs = profiles["etl_arquitectura"]["outputs"]
    assert set(outputs) == {"dev", "prod"}


def test_todo_modelo_sql_esta_documentado_en_un_models_yml():
    documented: set[str] = set()
    for yml in DBT_DIR.glob("models/**/_models.yml"):
        content = _load(yml) or {}
        documented |= {model["name"] for model in content.get("models", [])}

    sql_models = {p.stem for p in DBT_DIR.glob("models/**/*.sql")}
    assert sql_models <= documented, f"modelos sin documentar: {sorted(sql_models - documented)}"


def test_no_se_modela_la_metadata_del_orquestador():
    """dbt no debe leer el schema `prefect`: acopla el proyecto al schema interno de
    una herramienta de terceros que cambia en cada upgrade. Ver docs/adr/0003."""
    fuentes = [
        source["name"]
        for yml in DBT_DIR.glob("models/**/_sources.yml")
        for source in (_load(yml) or {}).get("sources", [])
    ]
    assert "prefect" not in fuentes, "volvió a aparecer una fuente sobre la metadata de Prefect"


def test_el_prefijo_del_modelo_coincide_con_su_capa():
    for path in DBT_DIR.glob("models/**/*.sql"):
        layer = path.relative_to(DBT_DIR / "models").parts[0]
        name = path.stem
        if layer == "staging":
            assert name.startswith("stg_"), name
        elif layer == "intermediate":
            assert name.startswith("int_"), name
        elif layer == "marts":
            assert name.startswith(("dim_", "fct_", "rpt_")), name


def test_los_snapshots_viven_en_scd2():
    """La carpeta y el schema se llaman igual que lo que contienen."""
    project = _load(DBT_DIR / "dbt_project.yml")
    assert project["snapshot-paths"] == ["scd2"]
    assert project["snapshots"]["etl_arquitectura"]["+schema"] == "scd2"
    assert (DBT_DIR / "scd2").is_dir()
    for path in (DBT_DIR / "scd2").glob("*.sql"):
        assert path.stem.startswith("scd2_"), path.stem


def test_el_paquete_dbt_instalado_no_queda_tapado_por_la_carpeta_del_proyecto():
    """`src/dbt/` comparte nombre con el paquete `dbt` de dbt-core.

    Los dos son namespace packages, así que Python los fusiona y el de site-packages
    gana; pero si algún día eso cambia, el ETL dejaría de poder invocar dbt. Este test
    lo detecta al instante en vez de en el primer deploy.
    """
    from dbt.cli.main import dbtRunner

    assert dbtRunner is not None
