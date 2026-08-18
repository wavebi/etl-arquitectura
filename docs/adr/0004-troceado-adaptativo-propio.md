# ADR 0004 — El troceado adaptativo de la ventana es código propio

- **Fecha:** 2026-08-18
- **Estado:** aceptado
- **Contexto:** `ingestion/pipelines/*/chunking.py`

## Contexto

Una carga histórica pide años de datos. Pedirlos de una vez termina en timeout o en
un 5xx; pedirlos de a un día son miles de requests y una carga que tarda horas.

La regla de la arquitectura es delegar todo lo que exista como librería probada:
dlt ya aporta retry con backoff y jitter, respeto de `Retry-After`, timeouts,
estado incremental con ventana de overlap y UPSERT por clave. Antes de escribir
código propio se buscó lo mismo para esto.

Lo que hay disponible resuelve otra cosa:

- `tenacity`, `backoff`, y el cliente de dlt reintentan **el mismo request**. No
  saben que el request se puede volver a hacer *pidiendo menos*.
- Los rate limiters (`pyrate-limiter`, `limits`) controlan la frecuencia, no el
  tamaño del pedido.
- Los helpers de paginación de dlt (`OffsetPaginator`, `PageNumberPaginator`)
  trocean cuando el ORIGEN expone paginación. Muchas APIs de datos históricos no la
  tienen: exponen un rango de fechas y nada más.

No se encontró una librería mantenida que haga control adaptativo del tamaño de la
ventana. Tiene sentido: la unidad divisible (días, ids, páginas) y qué error
significa "pediste demasiado" son decisiones de dominio.

## Decisión

Implementar el troceado en `chunking.py`, con control **AIMD** (crecimiento
aditivo, reducción multiplicativa), el mismo esquema que usa TCP para congestión:

- arranca con la ventana máxima permitida;
- ante un error *de tamaño* (timeout, 5xx, payload grande) la divide y reintenta el
  mismo tramo;
- tras N tramos consecutivos exitosos vuelve a agrandarla;
- si un tramo del tamaño mínimo sigue fallando, lo registra como perdido y avanza.

Se acota deliberadamente a ~150 líneas con una interfaz mínima (`fetch_adaptive`),
sin abstraer sobre "cualquier dimensión divisible": generalizarlo antes de tener un
segundo caso de uso costaría más que duplicarlo el día que aparezca.

## Consecuencias

**A favor**

- La carga histórica del ejemplo (27 años) se resuelve en 28 requests de un año en
  ~12 segundos, y sigue funcionando si el origen empieza a rechazar rangos grandes.
- La recuperación importa tanto como la defensa: sin el crecimiento, una lentitud
  pasajera dejaría toda la carga en la ventana mínima.
- Un tramo que el origen no puede servir no cuelga el ETL: queda listado en el
  reporte y en los logs para reprocesarlo.

**En contra**

- Es código propio, con sus tests y su mantenimiento.
- Los parámetros (ventana máxima, divisor, factor de crecimiento) son otra cosa que
  ajustar por proyecto.

**Mitigaciones**

- `tests/unit/test_chunking.py` cubre el recorrido completo sin red: cobertura del
  rango sin huecos, reducción ante fallas, recuperación tras éxitos, piso de
  ventana y propagación de los errores que no son de tamaño.
- Los defaults salen del `.env` (`INGEST_WINDOW_MAX_DAYS`), así que ajustarlos no
  requiere tocar código.
