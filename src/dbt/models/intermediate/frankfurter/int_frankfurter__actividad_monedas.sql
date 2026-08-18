-- Actividad de cada moneda a lo largo de todo el histórico.
--
-- Resuelve una discrepancia real del origen: el catálogo expone las ~30 monedas que
-- el BCE publica HOY, pero el histórico de 27 años contiene ~46 (la dracma, el
-- tolar, la kuna, la lira turca vieja). Si la dimensión se armara solo con el
-- catálogo, un tercio de los hechos históricos quedaría sin padre y los joins
-- perderían filas.
--
-- Es intermediate y no un mart porque la respuesta ("qué monedas existieron y
-- cuáles siguen vigentes") la necesitan la dimensión y los reportes.

with cotizaciones as (

    select * from {{ ref('stg_frankfurter__cotizaciones') }}

),

catalogo as (

    select * from {{ ref('stg_frankfurter__monedas') }}

),

-- Toda moneda que apareció alguna vez como cotizada, con su ventana de actividad.
observadas as (

    select
        c.moneda_cotizada                   as codigo_moneda,
        min(c.fecha)                        as primera_fecha,
        max(c.fecha)                        as ultima_fecha,
        count(distinct c.fecha)             as cantidad_dias_cotizados
    from cotizaciones as c
    group by 1

),

-- La moneda base también es una moneda: tiene que existir en la dimensión para que
-- el hecho pueda apuntarle (la dimensión juega dos roles).
bases as (

    select distinct c.moneda_base           as codigo_moneda
    from cotizaciones as c

),

universo as (

    select codigo_moneda from observadas
    union
    select codigo_moneda from bases
    union
    select codigo_moneda from catalogo

),

final as (

    select
        u.codigo_moneda,
        c.nombre_moneda,
        o.primera_fecha,
        o.ultima_fecha,
        coalesce(o.cantidad_dias_cotizados, 0)  as cantidad_dias_cotizados,
        -- Vigente = la publica el catálogo actual del origen.
        (c.codigo_moneda is not null)           as es_vigente,
        (b.codigo_moneda is not null)           as es_moneda_base

    from universo as u
    left join observadas as o on u.codigo_moneda = o.codigo_moneda
    left join catalogo as c on u.codigo_moneda = c.codigo_moneda
    left join bases as b on u.codigo_moneda = b.codigo_moneda

)

select * from final
