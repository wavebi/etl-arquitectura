-- Dimensión de meses — CONFORMADA REDUCIDA (Kimball: shrunken conformed dimension).
--
-- Es `dim_fecha` colapsada a nivel mes. Existe para que las tablas agregadas (`rpt_`)
-- tengan a qué apuntar: un agregado mensual que solo guardara el texto '2026-08'
-- obligaría a BI a unir por clave natural y no podría traer atributos de la
-- dimensión.
--
-- "Conformada reducida" significa que sus atributos son EXACTAMENTE los de la
-- dimensión completa en ese nivel (mismo `anio`, mismo `nombre_mes`, mismo
-- `trimestre`). Por eso se deriva de `dim_fecha` en lugar de recalcularse: si
-- mañana cambia el idioma de `nombre_mes`, cambia en las dos a la vez.
--
-- Grano: una fila por mes calendario.
--
-- Clave "inteligente" AAAAMM, coherente con el AAAAMMDD de `dim_fecha`.

with fechas as (

    select * from {{ ref('dim_fecha') }}
    -- El miembro desconocido de dim_fecha no colapsa a un mes: tiene el suyo abajo.
    where clave_fecha <> -1

),

final as (

    select distinct
        cast(to_char(f.fecha, 'YYYYMM') as integer) as clave_mes,

        f.anio_mes,
        f.anio,
        f.mes,
        f.trimestre,
        f.nombre_mes,
        f.nombre_trimestre,
        f.primer_dia_del_mes,
        f.ultimo_dia_del_mes

    from fechas as f

),

-- Miembro desconocido, por la misma razón que en el resto de las dimensiones.
desconocido as (

    select
        cast(-1 as integer)     as clave_mes,
        'N/D'                   as anio_mes,
        cast(null as integer)   as anio,
        cast(null as integer)   as mes,
        cast(null as integer)   as trimestre,
        'Sin identificar'       as nombre_mes,
        'N/D'                   as nombre_trimestre,
        cast(null as date)      as primer_dia_del_mes,
        cast(null as date)      as ultimo_dia_del_mes

)

select * from final
union all
select * from desconocido
