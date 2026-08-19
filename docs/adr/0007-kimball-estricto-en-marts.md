# ADR 0007 — Kimball estricto en marts: miembro desconocido y doble clave foránea

- **Fecha:** 2026-08-19
- **Estado:** aceptado
- **Contexto:** `src/dbt/models/marts/`, `src/dbt/models/marts/core/`

## Contexto

El modelo dimensional seguía Kimball en lo grueso —estrella sin snowflaking, claves
subrogadas, `dim_fecha` conformada generada por rango, dimensión role-playing, grano
declarado y testeado, aditividad documentada— pero una auditoría contra el estándar
encontró cinco desvíos. Dos de ellos no eran cuestiones de purismo:

**1. Los hechos se unían a las dimensiones con `inner join`.** Una fila cuyo código de
moneda no resolviera contra la dimensión **desaparecía**: sin error, sin test en rojo
y sin rastro. Es la misma clase de falla que una carga parcial de dlt que pasa por
exitosa (ver invariante 5 de CLAUDE.md), y en ese caso el proyecto ya decidió que una
pérdida silenciosa es inaceptable.

Que en ese momento no pudiera dispararse —`dim_moneda` se construye con la unión de lo
observado en los propios hechos— no alcanzaba: era una garantía *por construcción*,
que se rompe el día que una segunda fuente alimente el hecho.

**2. El snapshot SCD Type 2 no lo referenciaba ningún hecho.** `dim_moneda_historia`
existía y se mantenía en cada corrida, pero `fct_cotizacion` apuntaba solo a la
dimensión Type 1. Se pagaba el costo del Type 2 sin poder usarlo para lo único que lo
justifica: reportar un hecho con los atributos vigentes **en su fecha**.

Los otros tres eran menores: el agregado mensual guardaba texto en vez de claves de
dimensión, el hecho llamaba "dimensiones degeneradas" a claves naturales
desnormalizadas (una degenerada es un identificador *sin* tabla de dimensión), y las
columnas de auditoría viven en el hecho en lugar de una audit dimension.

## Decisión

**Toda dimensión lleva un miembro desconocido con clave `-1`, y los hechos se unen con
`left join` + `coalesce`.** Nunca `inner join` contra una dimensión.

**Si existe una dimensión Type 2, el hecho lleva las dos claves** (patrón *dual foreign
key* de Kimball): `clave_{entidad}` a la dimensión durable para "como es hoy", y
`clave_version_{entidad}` a la de historia para "como era entonces", resuelta por
rango `[valido_desde, valido_hasta)`.

**La primera versión de cada fila del Type 2 vale desde `start_date`**, no desde el
momento en que el snapshot corrió por primera vez.

**Las tablas agregadas (`rpt_`) llevan claves de dimensión**, no texto. Los niveles
agregados usan dimensiones conformadas reducidas (`dim_mes` derivada de `dim_fecha`).

Las reglas completas están en la skill `modelado-kimball`, y se verifican con tests de
dbt (`relationships` y `not_null` en cada FK, `unique_combination_of_columns` en cada
grano).

## Consecuencias

**A favor**

- Una fila que no resuelve contra su dimensión deja de perderse y pasa a ser un número
  que se cuenta y se alerta: `select count(*) from marts.fct_x where clave_dim = '-1'`.
- El Type 2 pasa a servir para algo. Medido: antes del piso de vigencia, **265.209 de
  265.238 hechos** quedaban sin versión; después, 0 en la moneda base.
- BI puede unir el agregado mensual a `dim_moneda` y traer `region`, que antes era
  imposible sin pasar por la clave natural.
- La integridad referencial queda verificada por tests, no asumida.

**En contra**

- Cada dimensión nueva cuesta un bloque `union all` con su miembro desconocido, y hay
  que acordarse de acotar los `not_null` que esa fila viola a propósito
  (`config: where: "clave <> -1"`).
- El hecho tiene dos FK más por cada dimensión con historia.
- El join por rango contra el Type 2 es más caro que un join por igualdad. A este
  volumen no se nota; con cientos de millones de filas habría que materializar la
  resolución en `intermediate`.
- Quedan hechos con versión desconocida y es correcto que así sea: 63.531 corresponden
  a monedas retiradas (la libra chipriota, la dracma) que el catálogo del origen nunca
  publicó, así que el snapshot no tiene nada que contar sobre ellas. El miembro
  desconocido lo hace visible en lugar de esconderlo en un NULL.

**Lo que NO se hizo**

No se creó una *audit dimension* para `cargado_en` / `origen_dato`. Kimball la
prescribe, pero acá son dos columnas de linaje por fila que se usan para diagnosticar,
y sacarlas del hecho agregaría un join a cada consulta de auditoría sin ganar nada.
Queda registrado como desvío consciente.
