{% snapshot scd2_frankfurter__monedas %}

{{
    config(
        target_schema='scd2',
        unique_key='codigo_moneda',
        strategy='check',
        check_cols=['nombre_moneda'],
        invalidate_hard_deletes=True
    )
}}

--
-- Historia del catálogo de monedas (SCD Type 2).
--
-- Por qué existe: la ingesta carga el catálogo con `replace`, así que raw solo tiene
-- la foto de hoy. Cuando el BCE deja de publicar una moneda (pasó con la kuna al
-- entrar Croacia al euro, y con el rublo en marzo de 2022), la fila desaparece del
-- origen y con ella la posibilidad de explicar por qué un reporte de hace dos años
-- la incluía.
--
-- `invalidate_hard_deletes=True` es justamente lo que registra esa baja: la versión
-- vigente se cierra con `dbt_valid_to` en lugar de desaparecer.
--
-- Estrategia `check` y no `timestamp`: el origen no expone ninguna fecha de
-- modificación del catálogo. El único timestamp disponible (`_ingested_at`) cambia en
-- cada corrida y generaría una versión nueva por corrida.
--
-- `check_cols` explícitas y no 'all': con 'all', cualquier columna nueva del origen
-- crearía versiones falsas.
--
-- Este snapshot NO se consume directo desde BI: se publica en marts como
-- `dim_moneda_historia`, con nombres de negocio y un flag de vigencia.
--
select
    codigo_moneda,
    nombre_moneda
from {{ ref('stg_frankfurter__monedas') }}

{% endsnapshot %}
