"""Cliente de la API de Frankfurter (tipos de cambio publicados por el BCE).

https://frankfurter.dev — API pública, sin autenticación ni cuota declarada, con
histórico diario desde 1999-01-04.

Qué aporta este módulo y qué no:

    NO implementa retry, backoff, jitter ni respeto de `Retry-After`: todo eso lo
    da `dlt.sources.helpers.requests`, configurado por variables de entorno
    (`RUNTIME__REQUEST_MAX_ATTEMPTS`, `RUNTIME__REQUEST_BACKOFF_FACTOR`,
    `RUNTIME__REQUEST_TIMEOUT`, `RUNTIME__REQUEST_MAX_RETRY_DELAY`). Ver `.env.tpl`.

    SÍ implementa lo que dlt no puede saber: qué significa cada respuesta de ESTA
    API. En particular los dos comportamientos no obvios, verificados el
    2026-08-18 (ver docs/fuentes/frankfurter.md):

      1. Un rango sin cotizaciones (fin de semana, feriado, rango futuro) puede
         devolver 404 con `{"message":"not found"}`. Es "no hay datos", no un
         error: se traduce a un resultado vacío.
      2. Para un rango que cae íntegramente en días sin publicación, la API
         devuelve la cotización del ÚLTIMO día hábil anterior, con su fecha real
         — que queda FUERA del rango pedido. Por eso el pipeline nunca asume que
         las fechas devueltas están dentro de la ventana: filtra por el cursor y
         deduplica por clave natural.

    Y suma un circuit breaker: si la API se cae, se deja de insistir por un rato
    en lugar de arrastrar la corrida entera.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from dlt.common.configuration import resolve_configuration
from dlt.common.configuration.specs import RuntimeConfiguration
from dlt.sources.helpers.requests import Client
from dlt.sources.helpers.rest_client import RESTClient

from shared.settings import settings
from shared.utils.notifications import notify_telegram
from shared.utils.resilience import CircuitBreaker

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

logger = logging.getLogger(__name__)

# Breaker a nivel de módulo: el recurso que protege (la API) también es uno solo.
_BREAKER = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0, name="frankfurter")


def _alert_breaker_open() -> None:
    notify_telegram(
        "error",
        "Circuit breaker de Frankfurter ABIERTO",
        details={
            "motivo": "5 fallas consecutivas tras los reintentos de dlt",
            "efecto": "se pausan los requests 30s",
            "accion": "revisar https://frankfurter.dev y los logs del flow",
        },
    )


_BREAKER.add_on_open_callback(_alert_breaker_open)


def _build_session() -> Any:
    """Sesión HTTP de dlt: retry, backoff, jitter y timeouts ya resueltos.

    La política sale de la `RuntimeConfiguration` de dlt, que se alimenta de las
    variables `RUNTIME__*`. Se loguea al construirla para que quede en el run log
    con qué política se corrió.
    """
    runtime = resolve_configuration(RuntimeConfiguration())
    logger.info(
        "HTTP de dlt — timeout=%ss intentos=%s backoff=%s max_delay=%ss",
        runtime.request_timeout,
        runtime.request_max_attempts,
        runtime.request_backoff_factor,
        runtime.request_max_retry_delay,
    )
    return Client(
        request_timeout=runtime.request_timeout,
        request_max_attempts=runtime.request_max_attempts,
        request_backoff_factor=runtime.request_backoff_factor,
        request_max_retry_delay=runtime.request_max_retry_delay,
        # El 429 y los 5xx los reintenta dlt; el 404 lo interpretamos nosotros.
        respect_retry_after_header=True,
        raise_for_status=True,
    ).session


class FrankfurterClient:
    """Acceso a los dos recursos de la API: monedas y cotizaciones.

    Uso:
        client = FrankfurterClient()
        monedas = client.get_currencies()
        rates = client.get_rates(date(2026, 1, 1), date(2026, 1, 31))
    """

    def __init__(self, base_currency: str | None = None) -> None:
        self._base_currency = base_currency or settings.FRANKFURTER_BASE_CURRENCY
        self._client = RESTClient(
            base_url=settings.FRANKFURTER_BASE_URL,
            session=_build_session(),
        )

    @property
    def base_currency(self) -> str:
        return self._base_currency

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """GET a través del breaker. Devuelve `None` cuando la API dice "sin datos".

        El chequeo del status es EXPLÍCITO y no se delega en `raise_for_status`. Motivo
        (verificado leyendo dlt 1.30): la sesión de dlt aplica el retry envolviendo
        `Session.send`, que es justo lo que usa `RESTClient` — o sea que el retry, el
        backoff y el respeto de `Retry-After` sí funcionan. Pero `raise_for_status` está
        en `Session.request`, que `RESTClient` NO usa: los 4xx y 5xx vuelven como
        respuestas normales, sin excepción.

        Si no se chequeara acá, un 500 sostenido devolvería `{}` en lugar de fallar: la
        carga terminaría "bien" con cero filas, el circuit breaker nunca se abriría y el
        troceado adaptativo nunca reduciría la ventana.

        Raises:
            CircuitOpenError: el breaker está abierto.
            requests.HTTPError: cualquier error que no sea 404.
        """

        def _do_request() -> dict[str, Any] | None:
            response = self._client.get(path, params=params)

            if response.status_code == 404:
                # Rango sin publicaciones o fuera del histórico disponible: es "no hay
                # datos", no un error. Ver docs/fuentes/frankfurter.md.
                logger.info("Frankfurter: sin datos para %s (%s)", path, params or {})
                return None

            response.raise_for_status()
            return response.json()

        return _BREAKER.call(_do_request)

    def get_currencies(self) -> dict[str, str]:
        """Catálogo de monedas disponibles: `{"USD": "United States Dollar", ...}`.

        Es una foto del presente: la API expone las monedas que publica HOY. El
        histórico incluye monedas que ya no existen (la lira, el marco alemán), y
        esas aparecen en las cotizaciones pero no en este catálogo — el modelo
        dimensional reconcilia las dos cosas.
        """
        payload = self._get("currencies")
        return payload or {}

    def get_rates(
        self,
        date_from: date,
        date_to: date,
        symbols: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Cotizaciones de un rango. Devuelve el payload del origen, tal cual.

        El único ajuste es unificar el shape de `rates`: para un rango la API lo
        devuelve anidado por fecha y para un solo día lo devuelve plano (con la
        fecha en el campo `date`). Se normaliza al anidado, que es el general.

        Args:
            date_from / date_to: rango pedido (inclusive).
            symbols: monedas a traer; vacío = todas las que publique la API.

        Returns:
            `{"amount": 1.0, "base": "EUR", "rates": {fecha: {moneda: valor}}}`, o un
            dict vacío si el origen dice que no hay datos.

        Las fechas devueltas pueden NO estar dentro del rango pedido: ver el
        comportamiento 2 documentado arriba.
        """
        params: dict[str, Any] = {"base": self._base_currency}
        if symbols:
            params["symbols"] = ",".join(symbols)

        payload = self._get(f"{date_from.isoformat()}..{date_to.isoformat()}", params)
        if not payload:
            return {}

        rates = payload.get("rates") or {}
        if rates and not isinstance(next(iter(rates.values())), dict):
            single_date = payload.get("date") or date_from.isoformat()
            payload["rates"] = {single_date: rates}
        else:
            payload["rates"] = rates
        return payload


def with_breaker(fn: Callable) -> Any:
    """Ejecuta un callable a través del mismo breaker que usa el cliente.

    Lo usa el pipeline para que el troceado adaptativo y el cliente compartan el
    estado del breaker: si la API está caída, no tiene sentido que el chunking
    siga bisecando ventanas.
    """
    return _BREAKER.call(fn)
