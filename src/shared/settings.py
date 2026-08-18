"""Configuración única del proyecto — Pydantic Settings.

Todo lo configurable entra por variables de entorno, que en runtime vienen de los
archivos `.env` (base) y `.env.local` / `.env.prod` (por entorno). Nada de
credenciales hardcodeadas ni de `os.environ` desparramado por el código: se
importa `settings` desde acá.

Convenciones:
    - Los secretos se declaran como `SecretStr` para que no aparezcan en logs ni
      en `repr()`; se leen con `.get_secret_value()`.
    - Los defaults son los de desarrollo local. En producción el `.env.prod` los pisa.
    - Cada fuente de datos tiene su propio bloque. Al agregar una fuente: el bloque
      acá, las variables en los `.env*.tpl` y los secrets en el GitHub Environment.
"""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuración unificada. Lee del entorno o de los archivos `.env`."""

    # ── General ───────────────────────────────────────────────────────────
    APP_NAME: str = "etl-arquitectura"
    ENV: str = "dev"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "America/Argentina/Buenos_Aires"

    @property
    def is_dev(self) -> bool:
        return self.ENV.lower() in ("dev", "development", "local")

    @property
    def is_prod(self) -> bool:
        return self.ENV.lower() in ("prod", "production")

    # ── Warehouse (Postgres) ──────────────────────────────────────────────
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "warehouse"
    DB_USER: str = "etl_app"
    DB_PASSWORD: SecretStr = SecretStr("dev_password")
    DB_SSLMODE: str = "disable"

    # ── Prefect ───────────────────────────────────────────────────────────
    PREFECT_WORK_POOL_NAME: str = "etl-process-pool"

    # ── Notificaciones ────────────────────────────────────────────────────
    # Vacío = notificaciones deshabilitadas (ver utils/notifications.py).
    TELEGRAM_BOT_TOKEN: SecretStr = SecretStr("")
    TELEGRAM_CHAT_ID: SecretStr = SecretStr("")

    # ── dbt ───────────────────────────────────────────────────────────────
    # Paths relativos al root del repo; en el container el compose los pisa con
    # los absolutos de /app.
    DBT_PROJECT_DIR: str = "src/dbt"
    DBT_TARGET: str = "dev"
    DBT_LOG_PATH: str = "logs/dbt"
    # El target va dentro del proyecto: `dbt docs serve` lo sirve desde ahí.
    DBT_TARGET_PATH: str = "src/dbt/target"

    # =====================================================================
    # FUENTE: Frankfurter (tipos de cambio del BCE) — https://frankfurter.dev
    # =====================================================================
    # API pública: no hay credenciales. Cuando la fuente las necesite, van acá
    # como SecretStr (los helpers de auth de dlt las consumen en el cliente).
    FRANKFURTER_BASE_URL: str = "https://api.frankfurter.dev/v1"
    FRANKFURTER_BASE_CURRENCY: str = "EUR"
    FRANKFURTER_HISTORY_START: str = "1999-01-04"

    # ── Ingesta: ventana y overlap ────────────────────────────────────────
    # Días que se re-piden hacia atrás en la corrida incremental diaria (el `lag`
    # de dlt). Cubre la corrección que el origen publica dentro de la misma semana.
    INGEST_OVERLAP_DAYS: int = 7
    # Días que re-pide el ETL de reconciliación, que corre con otra cadencia y
    # existe para atrapar correcciones viejas que el overlap corto no alcanza.
    INGEST_RECONCILE_OVERLAP_DAYS: int = 365
    # Ventana máxima que se le pide a la API de una vez; el troceado adaptativo
    # arranca acá y la baja sola si el origen falla.
    INGEST_WINDOW_MAX_DAYS: int = 365

    model_config = SettingsConfigDict(
        # Solo el archivo de desarrollo. En producción las variables llegan por el
        # entorno del contenedor (el compose las inyecta con `env_file`), y el
        # entorno tiene prioridad sobre cualquier archivo. Leer `.env.prod` acá
        # haría que un archivo a medio completar en la máquina de alguien pisara su
        # configuración local.
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",  # el .env trae variables para docker y dbt que no declaramos
        case_sensitive=True,
    )


@lru_cache
def get_settings() -> Settings:
    """Instancia cacheada — los `.env` se leen una sola vez por proceso."""
    return Settings()


# Instancia global: `from shared.settings import settings`
settings = get_settings()
