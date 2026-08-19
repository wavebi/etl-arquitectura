-- REPORTE: agregado mensual por par de monedas.
--
-- Es un `rpt_`: agrega y presenta, sin reglas de negocio propias. En Kimball esto es
-- una tabla agregada ("aggregate fact table"): mismo hecho, grano más grueso, para
-- que el tablero no recalcule 265.000 filas en cada refresh.
--
-- Grano: mes × par de monedas.
--
-- Lleva las MISMAS claves foráneas que el hecho atómico (`clave_moneda_*`) y una FK a
-- `dim_mes`, que es la dimensión conformada REDUCIDA de `dim_fecha`. Un agregado que
-- solo guardara los textos 'anio_mes' y 'moneda_base' obligaría a BI a unir por clave
-- natural y no podría traer `region` ni el resto de los atributos de la dimensión.
--
-- El agregado NUNCA es la única fuente: `fct_cotizacion` sigue debajo con el grano
-- atómico, y este modelo se deriva de él (no de staging), así que no puede divergir.

with hechos as (

    select * from {{ ref('fct_cotizacion') }}

),

fechas as (

    select * from {{ ref('dim_fecha') }}

),

unidos as (

    select
        cast(to_char(d.fecha, 'YYYYMM') as integer) as clave_mes,
        d.anio_mes,
        d.anio,
        d.mes,
        h.clave_moneda_base,
        h.clave_moneda_cotizada,
        h.moneda_base,
        h.moneda_cotizada,
        h.fecha,
        h.cotizacion,
        h.variacion_pct
    from hechos as h
    -- `inner join` acá es correcto y no pierde nada: `clave_fecha` del hecho ya viene
    -- resuelta contra la misma dimensión, incluido su miembro desconocido.
    inner join fechas as d on h.clave_fecha = d.clave_fecha
    -- Las filas sin fecha resoluble no se agregan por mes: no tienen mes al que ir.
    where d.clave_fecha <> -1

),

agregado as (

    select
        u.clave_mes,
        u.clave_moneda_base,
        u.clave_moneda_cotizada,

        u.anio_mes,
        u.anio,
        u.mes,
        u.moneda_base,
        u.moneda_cotizada,

        count(*)                                            as cantidad_dias_publicados,
        round(avg(u.cotizacion), 8)                         as cotizacion_promedio,
        min(u.cotizacion)                                   as cotizacion_minima,
        max(u.cotizacion)                                   as cotizacion_maxima,

        -- Apertura y cierre del mes: primer y último día publicado. `array_agg` con
        -- orden es la forma portable de un "primer/último valor por grupo".
        (array_agg(u.cotizacion order by u.fecha asc))[1]   as cotizacion_apertura,
        (array_agg(u.cotizacion order by u.fecha desc))[1]  as cotizacion_cierre,

        -- Volatilidad del mes: desvío estándar de las variaciones diarias.
        round(coalesce(stddev_samp(u.variacion_pct), 0), 6) as volatilidad_pct

    from unidos as u
    group by 1, 2, 3, 4, 5, 6, 7, 8

),

final as (

    select
        a.*,
        case
            when a.cotizacion_apertura is null or a.cotizacion_apertura = 0 then null
            else round(
                100 * (a.cotizacion_cierre - a.cotizacion_apertura) / a.cotizacion_apertura, 6
            )
        end                                                 as variacion_mensual_pct
    from agregado as a

)

select * from final
