-- Dimensión de fechas (conformada).
--
-- En Kimball es la primera dimensión que se construye y la que comparten todos los
-- hechos. Dos decisiones de diseño clásicas:
--
--   1. Clave subrogada "inteligente" `clave_fecha` en formato AAAAMMDD (entero). Es
--      compacta, ordenable y legible en un query ad-hoc; igual se expone `fecha`
--      para los filtros del BI.
--   2. Se genera por rango, no desde los hechos: la dimensión tiene que cubrir
--      fechas SIN hechos (feriados, fines de semana) para que un reporte pueda
--      mostrar "no hubo cotización" en lugar de saltear el día.

{% set fecha_inicio = var('start_date') %}

with fechas as (

    {{ dbt_utils.date_spine(
        datepart="day",
        start_date="cast('" ~ fecha_inicio ~ "' as date)",
        end_date="cast(date_trunc('year', current_date) + interval '2 years' as date)"
    ) }}

),

final as (

    select
        cast(to_char(d.date_day, 'YYYYMMDD') as integer)          as clave_fecha,
        cast(d.date_day as date)                                  as fecha,

        cast(extract(year from d.date_day) as integer)            as anio,
        cast(extract(quarter from d.date_day) as integer)         as trimestre,
        cast(extract(month from d.date_day) as integer)           as mes,
        cast(extract(day from d.date_day) as integer)             as dia_del_mes,
        cast(extract(isodow from d.date_day) as integer)          as dia_de_semana,
        cast(extract(week from d.date_day) as integer)            as semana_iso,

        to_char(d.date_day, 'TMMonth')                            as nombre_mes,
        to_char(d.date_day, 'TMDay')                              as nombre_dia,
        to_char(d.date_day, 'YYYY-MM')                            as anio_mes,
        'T' || cast(extract(quarter from d.date_day) as text)     as nombre_trimestre,

        (extract(isodow from d.date_day) between 1 and 5)         as es_dia_habil,
        (d.date_day = date_trunc('month', d.date_day))            as es_primer_dia_del_mes,
        (d.date_day = date_trunc('month', d.date_day) + interval '1 month' - interval '1 day')
                                                                  as es_ultimo_dia_del_mes,

        cast(date_trunc('month', d.date_day) as date)             as primer_dia_del_mes,
        cast(
            date_trunc('month', d.date_day) + interval '1 month' - interval '1 day' as date
        )                                                         as ultimo_dia_del_mes

    from fechas as d

)

select * from final
