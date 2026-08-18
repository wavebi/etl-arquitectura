-- HECHO: cotizaciones diarias.
--
-- Tipo de hecho (Kimball): **snapshot periódico**. No es un hecho transaccional (no
-- hay un evento de negocio por fila) ni acumulativo: es la foto del valor de un par
-- de monedas al cierre de cada día publicado.
--
-- Grano: una fila por fecha y par de monedas (base, cotizada). El grano se declara
-- acá y se testea abajo; es lo primero que hay que mirar antes de agregar una
-- columna a este modelo.
--
-- Aditividad de las medidas — importa para no sumar lo que no se puede sumar:
--   cotizacion           SEMI-ADITIVA. No se suma entre fechas; se promedia o se
--                        toma la última (típico de un snapshot periódico).
--   cotizacion_inversa   ídem.
--   variacion_pct        NO ADITIVA. Solo se promedia con cuidado.
--
-- Las claves foráneas son subrogadas (`clave_*`) y se conservan los códigos
-- naturales para que una consulta simple no necesite el join.

with cotizaciones as (

    select * from {{ ref('int_frankfurter__cotizaciones_diarias') }}

),

monedas as (

    select * from {{ ref('dim_moneda') }}

),

fechas as (

    select * from {{ ref('dim_fecha') }}

),

final as (

    select
        -- Claves foráneas
        f.clave_fecha,
        base.clave_moneda                   as clave_moneda_base,
        cotizada.clave_moneda               as clave_moneda_cotizada,

        -- Claves naturales (degeneradas): evitan un join para las consultas simples
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
    inner join fechas as f on c.fecha = f.fecha
    inner join monedas as base on c.moneda_base = base.codigo_moneda
    inner join monedas as cotizada on c.moneda_cotizada = cotizada.codigo_moneda

)

select * from final
