# Playbook: agregar una fuente de datos

Receta para sumar un origen al ETL. La fuente de ejemplo (`frankfurter`) está pensada
para copiarse: si tu origen es una API REST, el 80% del trabajo es cambiar el cliente
y el catálogo.

## 0. Antes de escribir código

Averiguá y anotá en `docs/fuentes/<fuente>.md` estas seis cosas. Sin ellas no se
puede decidir la estrategia de carga, y se termina reescribiendo el pipeline:

1. **Cómo se autentica** y cuánto vive el token.
2. **Qué recursos** necesitamos y cuál es la **clave natural** de cada uno.
3. **Si tiene fecha** por la que se pueda filtrar (⇒ incremental) o si es una foto
   del presente (⇒ replace).
4. **Si pagina** y cómo (offset / page / cursor / link header).
5. **Qué límites** tiene: cuota, rate limit, tamaño máximo de rango o de página.
6. **Qué devuelve cuando no hay datos**: ¿lista vacía, 204, 404, o el último dato
   disponible? Es la pregunta que más problemas evita.

Dos trampas frecuentes:

- Que exista un campo fecha no significa que el endpoint respete el filtro.
  Verificalo con un A/B explícito (pedí dos rangos distintos y comparalos); hay
  APIs que ignoran el parámetro y devuelven siempre lo mismo. Si es el caso,
  tratalo como posicional.
- Que la respuesta traiga fechas fuera del rango pedido. Le pasa a Frankfurter con
  los fines de semana. Si la clave natural está bien declarada, el merge lo absorbe.

## 1. `sources/<fuente>/` — el conector

```
src/ingestion/sources/mi_fuente/
├── __init__.py     # exporta el cliente
└── client.py       # transporte: base URL, auth, paginación, errores del origen
```

Reglas:

- Construilo sobre los helpers de dlt, no sobre `requests` pelado:

  ```python
  from dlt.sources.helpers.requests import Client        # retry, backoff, Retry-After
  from dlt.sources.helpers.rest_client import RESTClient # paginación
  from dlt.sources.helpers.rest_client.auth import OAuth2ClientCredentials
  from dlt.sources.helpers.rest_client.paginators import PageNumberPaginator
  ```

  El retry y los timeouts se configuran por entorno (`RUNTIME__REQUEST_*`), no por
  código. Si escribís un decorador de retry propio, algo está mal.
- Traducí los errores del origen a semántica de negocio: qué es "sin datos", qué es
  "no tenés permiso", qué es "el origen se cayó". Eso es lo único que dlt no puede
  saber.
- Devolvé datos crudos. Nada de renombrar, castear ni filtrar: en `raw` los nombres
  de columna son EXACTAMENTE los del origen (el pipeline usa `naming = direct` de
  dlt). Si la API devuelve `FechaEmisión`, en raw hay una columna `FechaEmisión`.

## 2. `pipelines/<fuente>/` — la carga a raw

```
src/ingestion/pipelines/mi_fuente/
├── __init__.py     # documenta el layout y el contrato público
├── constants.py    # tablas, clave natural, overlap, ventana
├── chunking.py     # (solo si el origen necesita troceado; si no, reusá el existente)
├── resources.py    # los @dlt.resource y la @dlt.source
└── runner.py       # ejecución + chequeo estricto del resultado
```

Checklist:

- [ ] `primary_key` con la clave natural del origen. Sin clave natural, agregá una
      columna `_row_id`:
      ```python
      import hashlib
      def add_row_id(record):
          clave = "|".join(str(record.get(c, "")) for c in ("campo_a", "campo_b"))
          record["_row_id"] = hashlib.sha256(clave.encode()).hexdigest()
          return record
      ```
      El requisito no negociable es que sea **estable entre corridas**: si incluís un
      campo que el origen cambia sin que cambie el registro (un id de sesión, un
      timestamp de generación), cada corrida inserta filas nuevas y raw duplica en
      silencio.
- [ ] `write_disposition` según el recurso: `replace` posicional / `merge` temporal.
- [ ] Cursor incremental con `lag` y `range_start="closed"` si es una serie temporal.
- [ ] Los registros pasan por `add_metadata()` (`ingestion/metadata.py`).
- [ ] El runner verifica `load_info.has_failed_jobs`: **dlt no levanta excepción por
      sí solo**, y sin ese chequeo una carga parcial pasa como exitosa.
- [ ] El runner fuerza la carga histórica si la tabla de raw está vacía.

## 3. `orchestration/` — task, flow y deployment

1. **Task** en `tasks/ingestion_tasks.py`: envoltorio delgado con `retries` y `tags`,
   y el import del pipeline **dentro** de la función (importar dlt al tope encarece
   el registro de deployments y lo acopla a que todas las fuentes importen bien).
2. **Flow** en `flows/etl_flows.py`: sumá el paso con `_run_step` y decidí si es
   grave o leve (`GRAVE_STEPS`).
3. **Deployment** en `deployments/etl_deployments.py`: schedule (solo prod) y
   parámetros explícitos para que la UI los muestre.

## 4. `dbt/` — staging y el modelo dimensional

1. `models/staging/<fuente>/_sources.yml`: declarar las tablas raw con
   `loaded_at_field: _ingested_at` y bloque `freshness`. Sin freshness, un raw que
   dejó de actualizarse se ve igual que uno al día.
2. Un `stg_<fuente>__<recurso>.sql` por tabla: **acá se renombra al español**,
   se castea y se limpia. De staging en adelante, tablas y columnas van en español
   (`fecha`, `moneda_cotizada`, `cotizacion`); los nombres del origen quedan en raw.
   Como raw conserva la grafía original, las columnas del origen suelen necesitar
   comillas: `select "FechaEmisión" as fecha_emision from ...`.
3. Documentar y testear en `_models.yml`: como mínimo `unique` + `not_null` en la
   clave y `relationships` hacia las dimensiones.
4. Recién después, el modelo dimensional: identificá el **grano** del hecho antes de
   escribir una línea de SQL, y qué dimensiones lo describen.

## 5. Configuración y secretos

- [ ] Variables nuevas en `shared/settings.py` (secretos como `SecretStr`).
- [ ] Las mismas variables en **los dos** contratos: `.env.local.tpl` y
      `.env.prod.tpl` (cada uno es autocontenido).
- [ ] Secrets cargados en el GitHub Environment `prod`.
- [ ] Tu `.env` local completado (`make env-init` genera el esqueleto).

## 6. Verificar

```bash
make lint && make test                       # estático + unitarios
make test-live                               # smoke contra la fuente real

make sh                                      # dentro del container:
python -c "from ingestion.pipelines.mi_fuente.runner import run_x_pipeline; print(run_x_pipeline())"

make diagnose                                # duplicados y cobertura de raw
make dbt CMD="build --select +stg_mi_fuente__x+"
```

Antes de dar la fuente por terminada, corré el pipeline **dos veces seguidas** y
comprobá que la cantidad de filas en raw no cambió. Es el chequeo que detecta una
clave inestable, que es el error más caro de encontrar después.

## 7. Documentar

- `docs/fuentes/<fuente>.md`: endpoints, claves, límites y **rarezas verificadas con
  fecha**. Sin la fecha no se sabe si sigue siendo cierto.
- Actualizar la sección de fuentes de `CLAUDE.md`.
- Si la fuente impuso una decisión de arquitectura, un ADR en `docs/adr/`.
