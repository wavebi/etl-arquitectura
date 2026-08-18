-- Dimensión de monedas — HISTORIA (SCD Type 2).
--
-- Contraparte de `dim_moneda`: una fila por moneda Y período de vigencia. Responde
-- "¿qué decía el origen sobre esta moneda en tal fecha?", que es la pregunta de
-- auditoría que la foto actual no puede contestar.
--
-- Se construye sobre el snapshot (`scd2_frankfurter__monedas`), que es quien detecta
-- los cambios. Este modelo solo lo publica en marts con nombres de negocio y un flag
-- de vigencia, para que BI no tenga que conocer las columnas internas de dbt
-- (`dbt_valid_from`, `dbt_valid_to`).
--
-- Cómo se usa: para reconstruir el estado a una fecha,
--     where fecha_consulta >= valido_desde
--       and (fecha_consulta < valido_hasta or valido_hasta is null)

with historia as (

    select * from {{ ref('scd2_frankfurter__monedas') }}

),

final as (

    select
        -- Clave de la VERSIÓN (no de la moneda): identifica una fila de historia.
        {{ dbt_utils.generate_surrogate_key(['codigo_moneda', 'dbt_valid_from']) }} as clave_version,
        {{ dbt_utils.generate_surrogate_key(['codigo_moneda']) }}                   as clave_moneda,

        codigo_moneda,
        nombre_moneda,

        {{ to_local_ts('dbt_valid_from') }}     as valido_desde,
        {{ to_local_ts('dbt_valid_to') }}       as valido_hasta,
        (dbt_valid_to is null)                  as es_version_vigente

    from historia

)

select * from final
