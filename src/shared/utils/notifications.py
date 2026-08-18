"""
Telegram notifications — alertas de runtime para flows y tasks.

Política de severidad:
    info     → ETL terminó OK normal (resumen).
    warning  → ETL terminó en modo degradado (algún paso no-crítico falló).
    error    → ETL falló en un paso crítico (Prefect rojo).

Reglas estrictas:
    - Esta función NUNCA tira excepción al caller. Si Telegram cae o las
      credenciales son inválidas, sólo se loguea un warning y el flow sigue.
    - Si el bot está en modo mock (token == "mock_bot") o las credenciales
      están vacías, la notificación se descarta silenciosamente.

Uso:
    from shared.utils.notifications import notify_telegram

    notify_telegram(
        "error",
        "etl-informe-mensual falló",
        details={"failed_steps": ["dbt_run"], "elapsed_seconds": 247.8},
    )
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

import requests

from shared.settings import settings

logger = logging.getLogger(__name__)

Level = Literal["info", "warning", "error"]

_ICONS: dict[Level, str] = {
    "info": "ℹ️",  # noqa: RUF001
    "warning": "⚠️",
    "error": "🚨",
}

_TELEGRAM_API_TIMEOUT = 10  # segundos
_MAX_DETAILS_CHARS = 3000  # Telegram message hard-limit es 4096; dejamos margen


def _is_disabled(token: str, chat_id: str) -> bool:
    # "mock_bot"/"mock_chat" son centinelas de "sin configurar", no secretos reales.
    return not token or not chat_id or token == "mock_bot" or chat_id == "mock_chat"  # noqa: S105


def notify_telegram(
    level: Level,
    title: str,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Envía una notificación a Telegram con el chat configurado en settings.

    Args:
        level:   Severidad — "info" | "warning" | "error".
        title:   Texto principal del mensaje (1 línea).
        details: Dict opcional con contexto. Se serializa a JSON y se trunca
                 a 3000 caracteres para no superar el límite de Telegram.
    """
    token = settings.TELEGRAM_BOT_TOKEN.get_secret_value()
    chat_id = settings.TELEGRAM_CHAT_ID.get_secret_value()

    if _is_disabled(token, chat_id):
        logger.debug("Telegram notification skipped (disabled or mock credentials).")
        return

    icon = _ICONS[level]
    body = f"{icon} *{settings.APP_NAME} \\[{settings.ENV}]* — {title}"

    if details:
        try:
            payload = json.dumps(details, default=str, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            payload = str(details)
        if len(payload) > _MAX_DETAILS_CHARS:
            payload = payload[:_MAX_DETAILS_CHARS] + "\n... (truncated)"
        body += f"\n```\n{payload}\n```"

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": body,
                "parse_mode": "Markdown",
                "disable_web_page_preview": "true",
            },
            timeout=_TELEGRAM_API_TIMEOUT,
        )
        if not response.ok:
            logger.warning(
                "Telegram notify returned %s: %s (notification dropped, flow continues).",
                response.status_code,
                response.text[:200],
            )
    except Exception as exc:
        logger.warning("Telegram notify failed (non-critical): %s — %s", type(exc).__name__, exc)
