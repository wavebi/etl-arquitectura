"""Conectores a los sistemas de origen — un subpaquete por fuente.

En este repo hay uno solo, `frankfurter/`, que es el ejemplo de referencia: una
API REST pública de tipos de cambio, con histórico desde 1999. Sirve para mostrar
el ciclo completo (carga histórica, incremental, reproceso) sin depender de
credenciales de ningún cliente.

Contrato que debe cumplir toda fuente nueva:

1. Un `client.py` que encapsule el transporte: base URL, autenticación, timeouts,
   paginación y traducción de los errores del origen. Se construye sobre los
   helpers de dlt (`dlt.sources.helpers.requests` y `rest_client.RESTClient`), no
   sobre `requests` pelado: así el retry, el backoff y el respeto de `Retry-After`
   son configuración y no código nuestro.
2. Devolver datos CRUDOS: sin renombrar campos, sin castear tipos, sin lógica de
   negocio. Eso es trabajo de dbt.
3. Nada de dlt en este subpaquete: los `@dlt.resource` viven en `pipelines/`.

El playbook completo está en docs/agregar_una_fuente.md.
"""
