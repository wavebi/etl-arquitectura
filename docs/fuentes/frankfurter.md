# Frankfurter — tipos de cambio del BCE

- **Tipo:** API REST pública, sin autenticación
- **URL:** https://frankfurter.dev — `https://api.frankfurter.dev/v1`
- **Qué publica:** tipos de cambio de referencia del Banco Central Europeo, diarios
- **Histórico:** desde `1999-01-04`
- **Límites:** no declara cuota ni rate limit. El histórico completo (27 años, todas
  las monedas) son ~3,5 MB y ~5 segundos en una sola respuesta.

Es la fuente de ejemplo de este repo. Se eligió porque permite mostrar el ciclo
completo de una ingesta real —carga histórica, incremental, reproceso, troceado— sin
credenciales de ningún cliente y sin costo.

## Recursos que traemos

| Endpoint | Tabla raw | Clave natural | Cursor | Estrategia |
|---|---|---|---|---|
| `/currencies` | `raw_frankfurter_currencies` | `currency_code` | — | `replace` |
| `/{desde}..{hasta}` | `raw_frankfurter_exchange_rates` | `rate_date`, `base_currency`, `quote_currency` | `rate_date` | `merge` |

La respuesta de cotizaciones viene anidada (`{"rates": {fecha: {moneda: valor}}}`) y
el pipeline la aplana a formato largo, una fila por fecha y moneda. **No es una
transformación de negocio, es evitar un schema que muta**: el conjunto de monedas
cambia a lo largo del histórico, así que una columna por moneda haría que raw
cambie de forma cada vez que el BCE agrega o retira una.

## Rarezas verificadas (2026-08-18)

1. **Un rango sin publicaciones devuelve el último día hábil anterior.** Pedir
   `2026-01-03..2026-01-04` (sábado y domingo) devuelve la cotización del viernes
   `2026-01-02`, con su fecha real — o sea, FUERA del rango pedido.
   *Consecuencia:* el pipeline no asume que las fechas devueltas caen dentro de la
   ventana. El merge por clave natural absorbe los duplicados entre tramos
   contiguos (en la carga histórica de 28 tramos aparecieron ~370 filas repetidas,
   todas deduplicadas correctamente).

2. **Un rango fuera del histórico devuelve HTTP 404** con `{"message":"not found"}`,
   no una lista vacía. Pasa con fechas futuras y con fechas anteriores a 1999.
   *Consecuencia:* el cliente traduce el 404 a "sin datos". Tratarlo como error
   dejaría el ETL en rojo cada vez que se pide un rango que termina en fin de semana.
   Ojo con el detalle de implementación: el `RESTClient` de dlt pasa por
   `Session.send`, donde dlt aplica el retry pero NO `raise_for_status`, así que los
   4xx/5xx llegan como respuestas normales. Por eso el cliente chequea el status a
   mano — si no, un 500 sostenido devolvería cero filas sin fallar.

3. **El catálogo de monedas es solo el presente, y no acepta fechas.**
   `/currencies` devuelve las 30 monedas que el BCE publica hoy, pero el histórico
   contiene ~46: la dracma, el tolar, la kuna, la lira turca vieja, el rublo
   (discontinuado en marzo de 2022). Pasarle una fecha no cambia nada: devuelve
   HTTP 200 y el payload de `/currencies?date=1999-01-04` es idéntico **byte a
   byte** al de `/currencies`. Comparado el 2026-08-18; `/1999-01-04` sí trae las
   35 monedas de entonces (GRD, CYP, EEK, LTL, LVL, MTL, ROL, SIT, SKK, TRL).
   *Consecuencia 1:* la dimensión de monedas se arma con la UNIÓN de lo observado en
   las cotizaciones y el catálogo actual, y marca `es_vigente`. Armarla solo con el
   catálogo dejaría un tercio de los hechos históricos sin fila en la dimensión.
   *Consecuencia 2:* el ETL del catálogo **no tiene reconciliación ni backfill**.
   No es una simplificación: no hay historia que reprocesar, así que un segundo ETL
   "con overlap hacia atrás" sería el mismo request otra vez.

4. **El rango de valores abarca siete órdenes de magnitud.** Del 0,86 del dólar al
   1.900.000 de la lira turca vieja.
   *Consecuencia:* la cotización inversa NO se redondea a un número fijo de
   decimales (lo que importa son las cifras significativas, no los decimales). Ver
   `int_frankfurter__rates_daily` y el test `assert_rate_and_inverse_are_consistent`.

5. **Publica solo días hábiles del BCE.** Ni fines de semana ni feriados europeos.
   *Consecuencia:* "el día anterior" no es `fecha - 1`; se calcula con `lag()` sobre
   las fechas realmente publicadas. La dimensión de fechas sí incluye todos los días,
   para que un reporte pueda mostrar "sin cotización" en lugar de saltear el día.

## Cadencia

El BCE publica alrededor de las 16:00 CET (~12:00 en Argentina).

| Deployment | Cuándo | Qué hace |
|---|---|---|
| `frankfurter-currencies-scheduled` | 13:20, L-V | foto del catálogo (`replace`) |
| `frankfurter-rates-scheduled` | 13:30, L-V | incremental, overlap `INGEST_OVERLAP_DAYS` (7d) |
| `frankfurter-rates-reconcile-scheduled` | 03:30, todos los días | re-pide `INGEST_RECONCILE_OVERLAP_DAYS` (365d) |
| `dbt-docs-scheduled` | 15:00, L-V | regenera catálogo y linaje |

El catálogo va antes que las cotizaciones para que la dimensión de monedas no quede
un ciclo atrasada. No es una dependencia dura: los dos subgrafos se reconstruyen
solos.

La reconciliación corre también sábado y domingo porque no depende de que el BCE
publique hoy, sino de que pueda haber corregido algo publicado semanas atrás.

## Pendientes

- La API acepta `?base=XXX` para cambiar la moneda base, pero devuelve la conversión
  calculada por ella. Si algún día se necesitan varias bases, conviene ingestar solo
  la base del BCE (EUR) y derivar los cruces en dbt, para no depender de su redondeo.
