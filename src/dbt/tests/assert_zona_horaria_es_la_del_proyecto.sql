-- Test singular: la sesión de dbt corre en la zona horaria del proyecto.
--
-- Todo el stack (contenedores, base, dlt, Prefect) está configurado en hora de
-- Argentina. Si la sesión de dbt quedara en UTC, `current_date` y `now()` cambiarían
-- de día tres horas antes y los cortes diarios de los reportes saldrían mal — sin
-- ningún error visible.
--
-- La zona la fija `scripts/init_db_permissions.sql` (a nivel de base y de rol). Este
-- test verifica que efectivamente esté aplicada donde corre dbt.

select
    current_setting('TimeZone')             as zona_horaria_de_la_sesion,
    '{{ var("display_timezone") }}'         as zona_horaria_esperada
where current_setting('TimeZone') <> '{{ var("display_timezone") }}'
