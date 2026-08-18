-- Test singular: no puede haber cotizaciones con fecha futura.
--
-- El origen devuelve 404 para rangos futuros, así que una fila adelantada solo puede
-- venir de un error nuestro: un chunk mal calculado o un problema de zona horaria en
-- el cálculo de "hoy".

select
    fecha,
    count(*) as cantidad_filas
from {{ ref('fct_cotizacion') }}
where fecha > current_date
group by 1
