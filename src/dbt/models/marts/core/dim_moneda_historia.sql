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

-- ## El piso de vigencia de la PRIMERA versión
--
-- El snapshot empieza a capturar el día que corre por primera vez. Sin corregirlo,
-- la primera versión de cada moneda queda vigente "desde 2026-08-18", y los 27 años
-- de hechos anteriores no encuentran ninguna versión: el SCD Type 2 pasaría a ser
-- decorativo justo para la historia, que es lo único que justifica su costo.
-- Verificado el 2026-08-19: 265.209 de 265.238 hechos quedaban sin versión.
--
-- Kimball resuelve esto con un piso: la primera versión de una fila de dimensión
-- vale "desde el principio de los tiempos". Acá ese principio es `start_date`, el
-- mismo piso que usa `dim_fecha`, así que ningún hecho puede ser anterior.
con_piso as (

    select
        h.*,
        row_number() over (
            partition by h.codigo_moneda
            order by h.dbt_valid_from
        ) as nro_version
    from historia as h

),

final as (

    select
        -- Clave de la VERSIÓN (no de la moneda): identifica una fila de historia.
        -- Se deriva del `dbt_valid_from` ORIGINAL, no del piso: así la clave es
        -- estable aunque mañana se cambie `start_date`.
        {{ dbt_utils.generate_surrogate_key(['codigo_moneda', 'dbt_valid_from']) }} as clave_version,
        {{ dbt_utils.generate_surrogate_key(['codigo_moneda']) }}                   as clave_moneda,

        codigo_moneda,
        nombre_moneda,

        case
            when nro_version = 1
                then cast(cast('{{ var("start_date") }}' as date) as timestamptz)
            else {{ to_local_ts('dbt_valid_from') }}
        end                                     as valido_desde,
        {{ to_local_ts('dbt_valid_to') }}       as valido_hasta,
        (dbt_valid_to is null)                  as es_version_vigente,

        -- La fecha real en que el snapshot detectó esta versión. Se conserva para
        -- auditar: `valido_desde` de la primera versión es un piso convencional, no
        -- un hecho observado.
        {{ to_local_ts('dbt_valid_from') }}     as capturado_en

    from con_piso

),

-- Miembro desconocido (Kimball). El hecho apunta acá con `clave_version_moneda_*`;
-- una cotización anterior a la primera versión capturada por el snapshot, o de una
-- moneda que el catálogo nunca publicó (la dracma, el tolar), cae en esta fila en
-- lugar de quedar con una FK huérfana.
desconocido as (

    select
        cast('-1' as text)              as clave_version,
        cast('-1' as text)              as clave_moneda,
        'N/D'                           as codigo_moneda,
        'Sin identificar'               as nombre_moneda,
        cast(null as timestamptz)       as valido_desde,
        cast(null as timestamptz)       as valido_hasta,
        cast(false as boolean)          as es_version_vigente,
        cast(null as timestamptz)       as capturado_en

)

select * from final
union all
select * from desconocido
