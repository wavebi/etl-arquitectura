"""
Prefect flow hooks que despachan notificaciones via Telegram.

Estos hooks se pasan al decorator `@enterprise_flow` como `on_completion` y
`on_failure`. Reciben `(flow, flow_run, state)` desde Prefect, calculan
duración y detalles, y delegan el envío a `notify_telegram`.

Uso:
    from shared.services.telegram import notify_flow_success, notify_flow_failure

    @enterprise_flow(
        name="etl-full",
        on_completion=[notify_flow_success],
        on_failure=[notify_flow_failure],
    )
    def etl_full_flow():
        ...

El nivel de la notif `on_completion` depende del result del flow: si retorna
`{"status": "degraded", ...}` (patrón de `finalize_flow`), se manda como
warning; si retorna "ok" o cualquier otro valor truthy, se manda como info.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from shared.utils.notifications import notify_telegram

if TYPE_CHECKING:
    from prefect import Flow
    from prefect.client.schemas.objects import FlowRun
    from prefect.states import State


def _format_duration(seconds: float) -> str:
    """Formato legible: '12.3s', '3m 45s', '1h 23m'."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    mins, secs = divmod(int(seconds), 60)
    if mins < 60:
        return f"{mins}m {secs}s"
    hours, mins = divmod(mins, 60)
    return f"{hours}h {mins}m"


def _elapsed_seconds(flow_run: FlowRun, state: State) -> float:
    """Segundos transcurridos. Prefiere `state.timestamp - flow_run.start_time`
    porque es lo más preciso; cae a `flow_run.total_run_time` si falta alguno.
    """
    end_time = getattr(state, "timestamp", None)
    start_time = getattr(flow_run, "start_time", None)
    if end_time and start_time:
        return (end_time - start_time).total_seconds()
    total = getattr(flow_run, "total_run_time", None)
    if total:
        return total.total_seconds()
    return 0.0


def _read_result(state: State) -> Any:
    """Lee el result del state con defensa: nunca tira."""
    with contextlib.suppress(Exception):
        return state.result(raise_on_failure=False)
    return None


def notify_flow_success(flow: Flow, flow_run: FlowRun, state: State) -> None:
    """Hook `on_completion`: distingue `ok` vs `degraded` según el result.

    Si el flow retorna un dict con `status: "degraded"` (patrón `finalize_flow`),
    manda warning con los steps que fallaron. Si retorna `status: "ok"` o
    cualquier otro valor, manda info.
    """
    elapsed = _elapsed_seconds(flow_run, state)
    result = _read_result(state)

    status = "ok"
    failed_steps: list[str] = []
    if isinstance(result, dict):
        status = result.get("status", "ok")
        failed_steps = list(result.get("failed_steps") or [])

    details: dict[str, Any] = {
        "flow": flow.name,
        "run_id": str(flow_run.id),
        "duration": _format_duration(elapsed),
    }

    if status == "degraded":
        details["failed_steps"] = failed_steps
        notify_telegram(
            "warning",
            f"{flow.name} completado en modo DEGRADADO",
            details=details,
        )
    else:
        notify_telegram(
            "info",
            f"{flow.name} completado OK",
            details=details,
        )


def notify_flow_failure(flow: Flow, flow_run: FlowRun, state: State) -> None:
    """Hook `on_failure`: notifica el fallo con el mensaje del state."""
    elapsed = _elapsed_seconds(flow_run, state)
    error_msg = (getattr(state, "message", None) or "Unknown error")[:500]

    notify_telegram(
        "error",
        f"{flow.name} FALLÓ",
        details={
            "flow": flow.name,
            "run_id": str(flow_run.id),
            "duration": _format_duration(elapsed),
            "error": error_msg,
        },
    )
