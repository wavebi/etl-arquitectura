---
name: modelado-kimball
description: Modelar los marts de etl-arquitectura con Kimball estricto — grano, claves subrogadas, miembro desconocido, dimensiones conformadas, role-playing, SCD, tipos de hecho y aditividad, tablas agregadas. Usar al crear o modificar cualquier modelo de marts/ o scd2/, al agregar una dimensión o un hecho, o cuando el usuario pregunte si el modelo cumple Kimball.
allowed-tools: Bash, Read, Edit, Write
---

# Modelado dimensional — Kimball estricto

Los marts de este proyecto siguen Kimball **al 100%**, no "en espíritu". Las reglas de
abajo no son sugerencias: hay tests de dbt que las verifican y un ADR que las registra.

Los nombres van **en español** (invariante 13 de CLAUDE.md) y el SQL castea con
`cast(x as t)`, nunca `x::t`.

---

## 1. El grano, primero y siempre

Antes de escribir una columna, escribí una frase: *"una fila por ______"*.

- Va en el comentario de cabecera del modelo **y** en `_models.yml`.
- Se **testea** con `dbt_utils.unique_combination_of_columns`, con
  `severity: error`. El grano es el contrato con BI: si se duplica, todas las
  medidas quedan infladas y nadie se entera hasta que un número no cierra.
- Elegí siempre el grano **más atómico** que el origen permita. Agregar es fácil
  después (ver §8); desagregar es imposible.

```yaml
- dbt_utils.unique_combination_of_columns:
    combination_of_columns: [fecha, moneda_base, moneda_cotizada]
    config:
      severity: error
```

---

## 2. Claves subrogadas en toda dimensión

```sql
{{ dbt_utils.generate_surrogate_key(['codigo_moneda']) }} as clave_moneda
```

- `clave_{entidad}` = subrogada. `codigo_{entidad}` / `id_{entidad}` = natural.
- Los hechos apuntan **solo** con `clave_*`. Aíslan al modelo de un renombre en el
  origen.
- **Única excepción autorizada**: `dim_fecha` usa una clave "inteligente"
  `AAAAMMDD` entera. Kimball la admite explícitamente porque es compacta, ordenable
  y legible en un query ad-hoc.

---

## 3. Miembro desconocido: toda dimensión lo tiene

**Regla dura.** Cada dimensión incluye una fila con clave fija `-1` para lo que no se
pudo resolver, y **los hechos se unen con `left join` + `coalesce`**, nunca con
`inner join`.

```sql
-- En la dimensión
desconocido as (
    select
        cast(-1 as text)    as clave_moneda,
        'N/D'               as codigo_moneda,
        'Sin identificar'   as nombre_moneda,
        ...
)
select * from final union all select * from desconocido
```

```sql
-- En el hecho
coalesce(base.clave_moneda, cast(-1 as text)) as clave_moneda_base
...
from cotizaciones as c
left join monedas as base on c.moneda_base = base.codigo_moneda
```

**Por qué es innegociable.** Un `inner join` contra una dimensión **descarta la fila
del hecho en silencio**: sin error, sin test en rojo, sin fila en ninguna tabla. Es
la misma clase de falla que `has_failed_jobs` en la ingesta — una pérdida parcial que
pasa por éxito. Con miembro desconocido el problema se vuelve un número que se puede
contar y alertar:

```sql
select count(*) from marts.fct_x where clave_dim = '-1'
```

Que hoy "no pueda pasar" porque la dimensión se construye desde los propios hechos no
alcanza: eso es una garantía por construcción, y se rompe el día que entra una
segunda fuente.

Acompañalo siempre con un test `relationships` y `not_null` sobre la FK.

---

## 4. Dimensiones conformadas y `dim_fecha`

- Una dimensión conformada se define **una vez** y la comparten todos los hechos.
  Viven en `marts/core/`.
- `dim_fecha` se genera **por rango** (`dbt_utils.date_spine`), nunca desde los
  hechos: tiene que cubrir días sin hechos para que un reporte pueda mostrar "sin
  datos" en vez de saltear el día.
- Nada de snowflaking: los atributos de un seed o de una tabla de referencia se
  **aplanan dentro** de la dimensión, no se cuelgan como sub-dimensión.

---

## 5. Role-playing

Cuando un hecho referencia la misma dimensión con dos sentidos distintos, se usan
**dos claves foráneas a la misma tabla**, con nombres que digan el rol:

```sql
base.clave_moneda      as clave_moneda_base,
cotizada.clave_moneda  as clave_moneda_cotizada,
```

No se duplica la dimensión ni se crean vistas por rol.

---

## 6. SCD: elegir el tipo, y conectarlo

| Tipo | Qué hace | Cuándo |
|---|---|---|
| 1 | pisa el valor | corrección de un error; no interesa la historia |
| 2 | fila nueva por versión, con vigencia | el atributo cambia y hay que reportar "como era entonces" |
| 3 | columna `valor_anterior` | un solo cambio previsible, interés acotado |

Este proyecto usa el patrón **foto + historia**:

- `dim_{entidad}` — Type 1, una fila por entidad, atributos vigentes. Es a la que
  apuntan los hechos para el análisis del día a día.
- `dim_{entidad}_historia` — Type 2, construida sobre el snapshot de `scd2/`.

**Si existe la Type 2, el hecho tiene que poder llegar a ella.** Un Type 2 al que
ningún hecho referencia no sirve para lo único que justifica su costo: reportar con
los atributos vigentes *en la fecha del hecho*. Por eso el hecho lleva **las dos**
claves:

```sql
base.clave_moneda           as clave_moneda_base,          -- durable (Type 1)
hb.clave_version            as clave_version_moneda_base,  -- versión a la fecha (Type 2)
...
left join historia as hb
       on c.moneda_base = hb.codigo_moneda
      and c.fecha >= cast(hb.valido_desde as date)
      and (hb.valido_hasta is null or c.fecha < cast(hb.valido_hasta as date))
```

Kimball llama a esto *dual foreign key*: la durable para "como es hoy", la de versión
para "como era entonces". Sin ella, el Type 2 es documentación, no un modelo.

---

## 7. Hechos: tipo y aditividad, declarados

Todo hecho declara en su cabecera **qué tipo es** y **cómo se puede sumar cada
medida**. Las tres clases:

| Tipo | Una fila por | Ejemplo |
|---|---|---|
| Transaccional | evento ocurrido | una venta, un pago |
| **Snapshot periódico** | entidad × período, haya pasado algo o no | saldo diario, cotización del día |
| Snapshot acumulativo | proceso con hitos, la fila se actualiza | un pedido y sus fechas de etapa |

Aditividad — es lo que evita que un tablero sume lo insumable:

- **Aditiva**: se suma por cualquier dimensión (importes, cantidades).
- **Semi-aditiva**: se suma por algunas y no por el tiempo (saldos, cotizaciones →
  se promedian o se toma la última).
- **No aditiva**: no se suma nunca (porcentajes, ratios).

Reglas del hecho:

- Solo claves foráneas, medidas y dimensiones degeneradas. **Nada de atributos
  descriptivos**: el nombre, la región o la categoría van en la dimensión.
- Una medida derivada (variación, valor previo) se guarda solo si el hecho se
  reconstruye entero en cada corrida (`+materialized: table`). Si el hecho fuera
  `incremental`, se calcula en la consulta.

### "Dimensión degenerada" quiere decir otra cosa

Una dimensión degenerada es un identificador operativo **que NO tiene tabla de
dimensión**: número de factura, número de ticket. Se guarda en el hecho porque no hay
atributos que colgarle.

Si el atributo **sí tiene dimensión** (una moneda, una fecha) y lo copiás igual al
hecho, eso es **desnormalización por comodidad de consulta**. Es válido y acá se hace
a propósito, pero llamalo por su nombre en los comentarios: confundirlos lleva a
meter atributos descriptivos en los hechos, que es lo que Kimball prohíbe.

---

## 8. Tablas agregadas (`rpt_`)

Un `rpt_` es una *aggregate fact table*: mismo hecho, grano más grueso.

**Tiene que llevar claves de dimensión, no strings.** Un agregado que solo guarda
`anio_mes` y `moneda_base` en texto obliga a BI a unir por clave natural y no puede
traer los atributos de la dimensión.

Kimball pide **shrunken conformed dimensions**: una dimensión reducida, conformada
con la completa. Un agregado mensual se une a `dim_mes`, que es `dim_fecha` colapsada
a nivel mes y comparte sus atributos (`anio`, `mes`, `nombre_mes`, `trimestre`).

```sql
d.clave_mes,                    -- FK a dim_mes (AAAAMM entero)
h.clave_moneda_base,            -- las mismas FK que el hecho atómico
h.clave_moneda_cotizada,
```

El agregado **nunca** es la única fuente: siempre existe el hecho atómico debajo.

---

## 9. Antipatrones

| Antipatrón | Por qué está mal |
|---|---|
| `inner join` del hecho a la dimensión | pierde filas en silencio → usar `left join` + miembro `-1` |
| FK nula en un hecho | no existe "sin dimensión" → usar `-1` |
| Snowflaking | aplanar los atributos dentro de la dimensión |
| Atributos descriptivos en el hecho | van en la dimensión |
| Grano sin declarar ni testear | es el contrato con BI |
| Type 2 que ningún hecho referencia | es costo sin beneficio (§6) |
| Sacar de la dimensión las entidades dadas de baja | deja hechos históricos huérfanos |
| Agregado sin claves de dimensión | no se puede unir a las conformadas |

---

## Checklist antes de dar por terminado un modelo

- [ ] Grano en una frase, en la cabecera y en `_models.yml`
- [ ] `unique_combination_of_columns` con `severity: error`
- [ ] Claves subrogadas `clave_*`; naturales `codigo_*` / `id_*`
- [ ] Miembro `-1` en cada dimensión nueva
- [ ] Hechos con `left join` + `coalesce(..., '-1')`
- [ ] Tests `not_null` y `relationships` en cada FK
- [ ] Tipo de hecho y aditividad por medida, documentados
- [ ] Sin atributos descriptivos en el hecho
- [ ] Si hay Type 2, el hecho lleva la clave de versión
- [ ] Los `rpt_` llevan claves de dimensión, no strings
- [ ] `make sqlfmt` y `make dbt-build` en verde
