{% macro generate_schema_name(custom_schema_name, node) -%}
    {#
        Controla en qué schema escribe cada modelo.

        Si el modelo define +schema (staging, intermediate, marts, snapshots),
        usa ese nombre directamente — sin prefijar con el target schema.

        Si NO define +schema, usa el schema por defecto del profile (raw).
    #}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
