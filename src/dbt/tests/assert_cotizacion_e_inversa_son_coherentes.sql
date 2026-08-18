-- Test singular: la cotización y su inversa tienen que ser coherentes.
--
-- Un test singular (SQL suelto en tests/) es para las reglas que cruzan modelos y no
-- encajan en un test de columna. Devuelve las filas que VIOLAN la regla: 0 filas = pasa.
--
-- Verifica que `cotizacion * cotizacion_inversa ≈ 1` con tolerancia 1e-8. No es
-- decorativo: con la inversa redondeada a 8 decimales fallaba en 1.963 filas (IDR,
-- KRW) y con 12 en 1.968 (TRL, ROL, con cotizaciones de hasta 1,9 millones). Por eso
-- intermediate no la redondea. Si este test vuelve a fallar, lo más probable es que
-- alguien haya agregado un `round()`.

select
    fecha,
    moneda_base,
    moneda_cotizada,
    cotizacion,
    cotizacion_inversa,
    cotizacion * cotizacion_inversa as producto_deberia_ser_uno
from {{ ref('fct_cotizacion') }}
where abs(cotizacion * cotizacion_inversa - 1) > 0.00000001
