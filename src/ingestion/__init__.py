"""Capa de ingesta: trae los datos del origen y los deja crudos en raw.

Dos subpaquetes con responsabilidades separadas — respetar la división es lo que
hace mecánico sumar una fuente nueva:

    sources/    CÓMO HABLAR con el origen. Cliente HTTP/SQL/SFTP, autenticación,
                paginación, parseo. No importa dlt ni sabe que existe un warehouse.

    pipelines/  CÓMO CARGAR a raw. Envuelve lo anterior en `@dlt.resource`,
                define la estrategia de carga (replace/merge), el cursor
                incremental y el troceado de la ventana pedida.

Nada de esto conoce Prefect: la orquestación vive en `orchestration/` y llama a
las funciones `run_*_pipeline()` de `pipelines/`.

Qué se delega a dlt y qué es nuestro (la división importa: lo que delegamos no lo
mantenemos):

    de dlt      retry con backoff y jitter, respeto de `Retry-After`, timeouts,
                estado incremental con ventana de overlap (`lag`), UPSERT por
                clave, evolución de schema, paginadores y helpers de auth.
    nuestro     el troceado adaptativo de la ventana (`chunking`), el circuit
                breaker, y el catálogo declarativo de qué se extrae.
"""
