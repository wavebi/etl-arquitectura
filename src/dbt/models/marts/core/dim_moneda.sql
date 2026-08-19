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

),

-- Miembro desconocido (Kimball). Existe para que NINGÚN hecho se quede sin padre:
-- los hechos se unen con `left join` y caen acá cuando el código no resuelve.
--
-- Sin esta fila habría que usar `inner join`, y una moneda que no esté en la
-- dimensión haría DESAPARECER la fila del hecho: sin error, sin test en rojo y sin
-- rastro. Con el miembro desconocido el problema se vuelve un número que se cuenta
-- y se alerta:  select count(*) from marts.fct_cotizacion where clave_moneda_base = '-1'
--
-- Hoy no puede dispararse porque la dimensión se arma con la unión de lo observado
-- en los propios hechos. Eso es una garantía por construcción, no por diseño: se
-- rompe el día que una segunda fuente alimente el hecho.
desconocido as (

    select
        cast('-1' as text)      as clave_moneda,
        'N/D'                   as codigo_moneda,
        'Sin identificar'       as nombre_moneda,
        'Sin clasificar'        as region,
        cast(false as boolean)  as es_vigente,
        cast(false as boolean)  as es_moneda_base,
        cast(null as date)      as primera_fecha,
        cast(null as date)      as ultima_fecha,
        cast(0 as bigint)       as cantidad_dias_cotizados

)

select * from final
union all
select * from desconocido
