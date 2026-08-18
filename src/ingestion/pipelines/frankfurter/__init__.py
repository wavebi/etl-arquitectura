"""Pipelines de ingesta Frankfurter → raw. Layout del subpaquete:

    constants   parámetros de carga (tablas, clave natural, overlaps, ventana).
    chunking    troceado adaptativo de la ventana de fechas (AIMD).
    resources   los `@dlt.resource` y una `@dlt.source` POR RECURSO.
    runner      ejecución de cada pipeline y chequeo estricto del resultado.

Un pipeline de dlt por recurso, no uno por fuente: cada uno tiene su estado y su
cursor, así que son ETLs independientes.

Contrato público:

    from ingestion.pipelines.frankfurter.runner import (
        run_currencies_pipeline,
        run_rates_pipeline,
    )
"""
