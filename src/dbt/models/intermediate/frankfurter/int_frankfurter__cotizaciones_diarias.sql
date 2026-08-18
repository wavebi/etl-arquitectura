-- Cotizaciones con las medidas derivadas de la publicación anterior.
--
-- Las funciones de ventana viven acá y no en el mart por una razón concreta: el
-- "día anterior" NO es `fecha - 1` (el BCE no publica sábados, domingos ni
-- feriados). Definirlo con `lag()` sobre las fechas realmente publicadas es una
-- regla de negocio, y una sola: si estuviera copiada en cada mart, el primer feriado
-- haría que dos reportes dieran números distintos.

with cotizaciones as (

    select * from {{ ref('stg_frankfurter__cotizaciones') }}

),

con_anterior as (

    select
        c.fecha,
        c.moneda_base,
        c.moneda_cotizada,
        c.cotizacion,

        lag(c.cotizacion) over (
            partition by c.moneda_base, c.moneda_cotizada
            order by c.fecha
        )                                   as cotizacion_anterior,

        lag(c.fecha) over (
            partition by c.moneda_base, c.moneda_cotizada
            order by c.fecha
        )                                   as fecha_anterior,

        c.cargado_en,
        c.origen_dato

    from cotizaciones as c

),

final as (

    select
        a.fecha,
        a.moneda_base,
        a.moneda_cotizada,
        a.cotizacion,
        a.cotizacion_anterior,
        a.fecha_anterior,

        -- Días calendario desde la publicación anterior: 3 un lunes normal, más si
        -- hubo feriado. Sirve para detectar huecos reales en la serie.
        (a.fecha - a.fecha_anterior)        as dias_desde_anterior,

        -- La inversa: cuántas unidades de la base equivalen a 1 de la cotizada.
        -- Se calcula acá porque es la pregunta natural del negocio ("¿cuánto vale un
        -- dólar en euros?") y no debería recalcularse en cada tablero.
        --
        -- SIN redondear, a propósito. Las cotizaciones del histórico abarcan siete
        -- órdenes de magnitud (0,86 el dólar; 1.900.000 la lira turca vieja), así que
        -- un número fijo de DECIMALES no controla la precisión: lo que importa son
        -- las cifras significativas. Con 8 decimales el producto cotización × inversa
        -- se apartaba de 1 en 1e-4 (1.963 filas de IDR y KRW); con 12 seguía fallando
        -- en 1.968 de TRL y ROL. Postgres divide con ~24 decimales y el error queda en
        -- 1e-19. Lo vigila tests/assert_cotizacion_e_inversa_son_coherentes.sql.
        (1 / a.cotizacion)                  as cotizacion_inversa,

        case
            when a.cotizacion_anterior is null then null
            else round(100 * (a.cotizacion - a.cotizacion_anterior) / a.cotizacion_anterior, 6)
        end                                 as variacion_pct,

        a.cargado_en,
        a.origen_dato

    from con_anterior as a

)

select * from final
