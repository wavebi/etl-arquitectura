"""Circuit breaker sobre un origen de datos.

Es la capa que falta cuando ya tenés retry: el retry cubre la falla puntual de un
request; el breaker cubre el caso distinto de que el origen esté caído. Sin él,
cada corrida sigue golpeando un servicio degradado, alarga el ETL y —si el origen
tiene cuota— la quema al vacío.

Implementado sobre `pybreaker`, que es la máquina de estados estándar en Python
(closed → open → half-open). Acá solo se agrega la política del proyecto:

    - los errores 4xx del cliente NO abren el breaker (son problemas nuestros de
      configuración o permisos, no del origen);
    - la apertura dispara un callback, que se usa para alertar.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pybreaker
import requests

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# 408 y 429 sí cuentan: son señal de que el origen está saturado.
_CLIENT_ERROR_EXCEPTIONS = (408, 429)


class CircuitOpenError(Exception):
    """El breaker está abierto: no se intentó llamar al origen."""


def _is_client_error(exc: BaseException) -> bool:
    """True para los 4xx que no indican un problema del origen."""
    if not isinstance(exc, requests.HTTPError) or exc.response is None:
        return False
    status = exc.response.status_code
    return 400 <= status < 500 and status not in _CLIENT_ERROR_EXCEPTIONS


class _StateListener(pybreaker.CircuitBreakerListener):
    """Traduce los cambios de estado del breaker a logs y callbacks."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._on_open: list[Callable[[], None]] = []

    def add_on_open(self, callback: Callable[[], None]) -> None:
        self._on_open.append(callback)

    def state_change(self, breaker: Any, old: Any, new: Any) -> None:  # noqa: ARG002
        new_state = getattr(new, "name", str(new))
        logger.warning("Circuit breaker '%s' → %s", self._name, new_state)
        if new_state == "open":
            for callback in self._on_open:
                try:
                    callback()
                except Exception:  # pragma: no cover — un callback roto no debe tumbar el ETL
                    logger.exception("Callback on_open del breaker '%s' falló", self._name)


class CircuitBreaker:
    """Breaker con la política del proyecto.

    Uso:
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30, name="mi-api")
        breaker.add_on_open_callback(lambda: notify_telegram("error", "API caída"))
        data = breaker.call(lambda: client.get("/recurso"))
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        name: str = "source",
    ) -> None:
        self.name = name
        self._listener = _StateListener(name)
        self._breaker = pybreaker.CircuitBreaker(
            fail_max=failure_threshold,
            reset_timeout=recovery_timeout,
            exclude=[_is_client_error],
            listeners=[self._listener],
            name=name,
        )

    def add_on_open_callback(self, callback: Callable[[], None]) -> None:
        """Registra un callback para cuando el breaker se abre (p. ej. alertar)."""
        self._listener.add_on_open(callback)

    def call(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """Ejecuta `fn` a través del breaker.

        Raises:
            CircuitOpenError: si el breaker está abierto. Ojo con el detalle: la
                llamada que ALCANZA el umbral también sale como `CircuitOpenError`
                y no con la excepción original (pybreaker abre el circuito y
                reporta la apertura). Quien llame debe estar preparado para las
                dos: la excepción del origen mientras el circuito está cerrado, y
                `CircuitOpenError` desde la falla que lo abre en adelante.
            La excepción original: cualquier falla previa al umbral.
        """
        try:
            return self._breaker.call(fn, *args, **kwargs)
        except pybreaker.CircuitBreakerError as exc:
            raise CircuitOpenError(f"Circuit breaker '{self.name}' abierto — {exc}") from exc

    @property
    def current_state(self) -> str:
        return self._breaker.current_state
