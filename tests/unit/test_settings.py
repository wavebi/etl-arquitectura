"""Settings: defaults sanos y secretos que no se filtran."""

from shared.settings import Settings


def test_defaults_apuntan_a_dev():
    settings = Settings(_env_file=None)
    assert settings.is_dev
    assert not settings.is_prod


def test_flags_de_entorno_son_excluyentes():
    """Solo hay dos entornos: dev y prod (stg se eliminó del proyecto)."""
    for env, expected in [("prod", "prod"), ("production", "prod"), ("dev", "dev"), ("local", "dev")]:
        settings = Settings(ENV=env, _env_file=None)
        flags = {"dev": settings.is_dev, "prod": settings.is_prod}
        assert [k for k, v in flags.items() if v] == [expected]


def test_los_secretos_no_aparecen_en_el_repr():
    """Si un secreto entra en un log de Prefect, queda expuesto para siempre."""
    settings = Settings(DB_PASSWORD="superclave", _env_file=None)
    assert "superclave" not in repr(settings)
    assert "superclave" not in str(settings.DB_PASSWORD)
    assert settings.DB_PASSWORD.get_secret_value() == "superclave"


def test_variables_desconocidas_se_ignoran():
    """El .env trae variables para docker y para dbt que Settings no declara."""
    settings = Settings(VARIABLE_QUE_NO_EXISTE="x", _env_file=None)
    assert not hasattr(settings, "VARIABLE_QUE_NO_EXISTE")
