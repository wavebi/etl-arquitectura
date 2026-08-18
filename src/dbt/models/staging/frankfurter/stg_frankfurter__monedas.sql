-- Staging del catálogo de monedas vigentes.

with origen as (

    select * from {{ source('frankfurter', 'raw_frankfurter_currencies') }}

),

renombrado as (

    select
        upper(trim("code"))                 as codigo_moneda,
        nullif(trim("name"), '')            as nombre_moneda,

        _ingested_at                        as cargado_en,
        _source                             as origen_dato

    from origen

)

select * from renombrado
