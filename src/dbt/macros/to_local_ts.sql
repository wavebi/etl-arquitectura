{% macro to_local_ts(ts_column) -%}
    {#-
        Convierte un timestamptz (UTC) a la hora local de visualización del
        cliente, devolviendo un timestamp sin timezone (lo que espera Power BI).
        La zona horaria se controla con la var `display_timezone`
        (default America/Argentina/Buenos_Aires).
    -#}
    ({{ ts_column }} at time zone '{{ var("display_timezone", "America/Argentina/Buenos_Aires") }}')
{%- endmacro %}
