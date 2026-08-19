-- HECHO: cotizaciones diarias.
--
-- Tipo de hecho (Kimball): **snapshot periódico**. No es un hecho transaccional (no
-- hay un evento de negocio por fila) ni acumulativo: es la foto del valor de un par
-- de monedas al cierre de cada día publicado.
--
-- Grano: una fila por fecha y par de monedas (base, cotizada). El grano se declara
-- acá y se testea en `_models.yml`; es lo primero que hay que mirar antes de agregar
-- una columna a este modelo.
--
-- Aditividad de las medidas — importa para no sumar lo que no se puede sumar:
--   cotizacion           SEMI-ADITIVA. No se suma entre fechas; se promedia o se
--                        toma la última (típico de un snapshot periódico).
--   cotizacion_inversa   ídem.
--   variacion_pct        NO ADITIVA. Solo se promedia con cuidado.
--
-- ## Las uniones son LEFT, no INNER
--
-- Con `inner join`, una fila cuyo código de moneda no resuelva contra la dimensión
-- DESAPARECE: sin error, sin test en rojo y sin rastro en ninguna tabla. Es la misma
-- clase de falla que una carga parcial de dlt que pasa por exitosa.
--
-- Con `left join` + miembro desconocido (`-1`), esa fila entra igual y el problema
-- se vuelve un número que se cuenta y se alerta:
--     select count(*) from marts.fct_cotizacion where clave_moneda_base = '-1'
--
-- ## Doble clave foránea a la dimensión de monedas (Kimball: dual foreign key)
--
--   clave_moneda_*          → dimensión DURABLE (`dim_moneda`, Type 1). Responde
--                             "¿cómo es esta moneda hoy?". Es la que usa el 95% de
--                             los tableros: un join, sin filtrar por vigencia.
--   clave_version_moneda_*  → dimensión de HISTORIA (`dim_moneda_historia`, Type 2).
--                             Responde "¿qué decía el origen sobre esta moneda EN LA
--                             FECHA del hecho?".
--
-- Sin la segunda, el snapshot SCD Type 2 sería costo sin beneficio: se detectan los
-- cambios pero ningún hecho puede reportarse con los atributos de entonces.

with cotizaciones as (

    select * from {{ ref('int_frankfurter__cotizaciones_diarias') }}

),

monedas as (

    select * from {{ ref('dim_moneda') }}

),

historia as (

    select * from {{ ref('dim_moneda_historia') }}

),

fechas as (

    select * from {{ ref('dim_fecha') }}

),

final as (

    select
        -- Claves foráneas a las dimensiones conformadas.
        coalesce(f.clave_fecha, -1)                     as clave_fecha,
        coalesce(base.clave_moneda, '-1')               as clave_moneda_base,
        coalesce(cotizada.clave_moneda, '-1')           as clave_moneda_cotizada,

        -- Claves de VERSIÓN: la fila de historia vigente a la fecha del hecho.
        coalesce(hb.clave_version, '-1')                as clave_version_moneda_base,
        coalesce(hc.clave_version, '-1')                as clave_version_moneda_cotizada,

        -- Claves naturales DESNORMALIZADAS en el hecho, para que una consulta simple
        -- no necesite el join. Ojo con el vocabulario: NO son dimensiones
        -- degeneradas —esas son identificadores operativos SIN tabla de dimensión,
        -- como un número de factura— y estas tres sí tienen la suya.
        c.fecha,
        c.moneda_base,
        c.moneda_cotizada,

        -- Medidas
        c.cotizacion,
        c.cotizacion_inversa,
        c.cotizacion_anterior,
        c.variacion_pct,
        c.dias_desde_anterior,

        -- Trazabilidad hasta la ingesta
        c.cargado_en,
        c.origen_dato

    from cotizaciones as c
    left join fechas as f on c.fecha = f.fecha
    left join monedas as base on c.moneda_base = base.codigo_moneda
    left join monedas as cotizada on c.moneda_cotizada = cotizada.codigo_moneda

    -- La versión vigente a la fecha del hecho. El rango es [desde, hasta): cerrado
    -- abajo y abierto arriba, para que una fecha límite pertenezca a una sola
    -- versión y el join no duplique filas del hecho.
    left join historia as hb
        on c.moneda_base = hb.codigo_moneda
        and c.fecha >= cast(hb.valido_desde as date)
        and (hb.valido_hasta is null or c.fecha < cast(hb.valido_hasta as date))

    left join historia as hc
        on c.moneda_cotizada = hc.codigo_moneda
        and c.fecha >= cast(hc.valido_desde as date)
        and (hc.valido_hasta is null or c.fecha < cast(hc.valido_hasta as date))

)

select * from final
