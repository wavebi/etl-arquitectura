-- Dimensión de monedas (conformada, con dos roles) — FOTO ACTUAL.
--
-- Esta tabla responde "¿cómo es la moneda hoy?": un registro por moneda, con sus
-- atributos vigentes. Es lo que consume BI y a lo que apuntan los hechos.
--
-- La HISTORIA de esos atributos (cuándo cambió el nombre, cuándo el origen dejó de
-- publicar una moneda) vive aparte, en `dim_moneda_historia`, construida sobre el
-- snapshot SCD Type 2. Están separadas a propósito:
--
--   - un hecho tiene que poder unirse a la dimensión con UN join y sin filtrar por
--     rango de vigencia; si la dimensión tuviera varias versiones por moneda, cada
--     query del tablero necesitaría `where valido_hasta is null` y el que se olvide
--     multiplica sus filas;
--   - las preguntas de auditoría ("qué decía esta moneda en 2015") son otras y
--     tienen su propia tabla.
--
-- Es una dimensión "role-playing": el hecho la referencia DOS veces, como moneda
-- base y como moneda cotizada. En Kimball eso se resuelve con dos claves foráneas a
-- la misma dimensión.
--
-- Incluye monedas que ya no se publican (la dracma, el tolar): un hecho histórico
-- tiene que poder unirse a su dimensión, y `es_vigente` distingue las actuales.
-- Sacarlas rompería el 100% de la integridad referencial del histórico.

with actividad as (

    select * from {{ ref('int_frankfurter__actividad_monedas') }}

),

regiones as (

    select * from {{ ref('seed_moneda_region') }}

),

final as (

    select
        -- Clave subrogada: aísla los hechos del código natural. Si mañana el origen
        -- renombra un código, la dimensión absorbe el cambio y los hechos no se tocan.
        {{ dbt_utils.generate_surrogate_key(['a.codigo_moneda']) }}      as clave_moneda,

        a.codigo_moneda,
        coalesce(a.nombre_moneda, r.nombre_alternativo, a.codigo_moneda) as nombre_moneda,
        coalesce(r.region, 'Sin clasificar')                            as region,

        a.es_vigente,
        a.es_moneda_base,
        a.primera_fecha,
        a.ultima_fecha,
        a.cantidad_dias_cotizados

    from actividad as a
    left join regiones as r on a.codigo_moneda = r.codigo_moneda

)

select * from final
