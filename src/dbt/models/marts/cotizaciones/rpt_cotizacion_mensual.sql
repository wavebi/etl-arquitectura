-- REPORTE: agregado mensual por par de monedas.
--
-- Es un `rpt_`: agrega y presenta, sin reglas de negocio propias. En Kimball esto es
-- una tabla agregada ("aggregate fact table"): mismo hecho, grano más grueso, para
-- que el tablero no recalcule 265.000 filas en cada refresh.
--
-- Grano: mes × par de monedas.

with hechos as (

    select * from {{ ref('fct_cotizacion') }}

),

fechas as (

    select * from {{ ref('dim_fecha') }}

),

unidos as (

    select
        d.anio_mes,
        d.anio,
        d.mes,
        h.moneda_base,
        h.moneda_cotizada,
        h.fecha,
        h.cotizacion,
        h.variacion_pct
    from hechos as h
    inner join fechas as d on h.clave_fecha = d.clave_fecha

),

agregado as (

    select
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
    group by 1, 2, 3, 4, 5

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
