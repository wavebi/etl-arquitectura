"""Carga a raw con dlt — un subpaquete por fuente.

Cada subpaquete expone funciones `run_*_pipeline()`, que son el único contrato
público: orquestación las llama desde sus tasks y no depende de cómo estén armados
los resources por dentro.

Estrategias de carga (`write_disposition`) y cuándo usar cada una:

    replace  Foto del presente: catálogos y maestros que el origen pisa. Para
             tener el histórico de lo que se pisa, se agrega un snapshot de dbt
             (SCD Type 2), no se cambia la estrategia de carga.

    merge    Series temporales y transaccionales. UPSERT por clave natural, con
             cursor incremental y ventana de overlap (`lag`) para capturar
             correcciones del origen.

    append   Solo cuando el origen garantiza que nunca reenvía una fila (un log de
             eventos). En la práctica casi nunca es el caso: si te equivocás,
             raw duplica en silencio. Ante la duda, `merge`.
"""
