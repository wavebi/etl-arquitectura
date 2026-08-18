-- Staging de las cotizaciones.
--
-- Acá pasan las tres cosas que definen esta capa, y ninguna más:
--   1. RENOMBRE al español (los nombres crudos del origen quedan en `raw`),
--   2. casteo y limpieza,
--   3. filtro de datos imposibles.
-- Sin joins, sin agregaciones, sin reglas de negocio.
--
-- Las columnas del origen se citan con comillas porque `raw` conserva los nombres
-- exactos de la API y algunos (`date`) son palabras reservadas de SQL.

with origen as (

    select * from {{ source('frankfurter', 'raw_frankfurter_exchange_rates') }}

),

renombrado as (

    select
        "date"                              as fecha,
        upper(trim("base"))                 as moneda_base,
        upper(trim("currency"))             as moneda_cotizada,
        "rate"                              as cotizacion,
        "amount"                            as monto_base,

        -- Metadata de la ingesta: se propaga a todas las capas. Sin esto no se puede
        -- auditar de dónde salió una fila de un mart.
        _ingested_at                        as cargado_en,
        _source                             as origen_dato

    from origen
    -- Una cotización cero o negativa no existe: sería un dato corrupto del origen y
    -- rompería las inversas y las variaciones porcentuales aguas abajo.
    where "rate" > 0

)

select * from renombrado
