# ADR 0003 — Los modelos dbt sobre la metadata de Prefect se materializan como tabla

- **Fecha:** 2026-08-18
- **Estado:** aceptado
- **Contexto:** `dbt/models/staging/prefect/`, `marts/ops/`

## Contexto

Prefect guarda su estado (flow runs, deployments, tareas) en el mismo Postgres que
el warehouse, en el schema `prefect`. Eso permite modelarlo con dbt y tener un
tablero de control de los pipelines —`marts/ops/rpt_corridas_pipeline`— sin
infraestructura extra. Es una de las mejores propiedades de esta arquitectura: el
monitoreo del ETL sale del mismo stack que el ETL.

Los modelos de staging se materializan como **vistas** por convención, y así se
hizo también con estos. Al actualizar el server de Prefect, el arranque falló:

```
asyncpg.exceptions.DependentObjectsStillExistError:
cannot drop column flow_runner_type of table flow_run because other objects depend on it
DETAIL: view staging.stg_prefect__flow_runs depends on column flow_runner_type
        view marts.rpt_corridas_pipeline depends on view staging.stg_prefect__flow_runs
ERROR: Application startup failed. Exiting.
```

Una vista de Postgres crea una dependencia **dura** sobre las columnas que
referencia. Las migraciones de Prefect dropean columnas al actualizar de versión, y
Postgres se niega mientras exista la vista. Resultado: **el orquestador entero no
arranca por culpa de un modelo de dbt**, y el error aparece durante un upgrade,
que es justo cuando uno menos quiere depurar dependencias de SQL.

## Decisión

**No se modela la metadata de Prefect con dbt.** Se eliminaron los modelos
`stg_prefect__*` y el mart de monitoreo.

La decisión anterior —materializarlos como tabla para no bloquear las migraciones—
resolvía el síntoma, pero dejaba en pie el problema de fondo: el proyecto de dbt
quedaba acoplado al schema interno de una herramienta de terceros, que cambia cuando
se actualiza y sin previo aviso. Cada upgrade de Prefect pasaba a ser un riesgo para
el ETL, a cambio de un tablero que la UI de Prefect ya ofrece.

Para ver cómo vienen las corridas está la UI de Prefect (y las notificaciones de
Telegram, que avisan sin que haya que ir a mirar). El schema `prefect` queda aislado:
solo `prefect_app` lo lee y lo escribe.

## Consecuencias

**A favor**

- El proyecto de dbt no depende del schema interno de Prefect: actualizar el
  orquestador deja de ser un riesgo para la capa de transformación.
- Menos superficie: dos modelos y una fuente menos que mantener y documentar.
- El schema `prefect` queda aislado, con un solo rol que lo toca.

**En contra**

- No hay un mart con el histórico de corridas para cruzar con datos de negocio
  ("¿cuántas veces falló el ETL el mes que los números no cerraron?"). La UI de
  Prefect responde el 95% de esas preguntas, pero no se puede unir con SQL.

**Si alguna vez se vuelve a modelar** (el escenario realista: el cliente quiere el
estado del ETL dentro de su tablero de BI), la trampa a evitar quedó documentada acá:
**nunca con vistas**. Una vista de Postgres crea una dependencia dura sobre las
columnas del origen, y las migraciones de Prefect dropean columnas al actualizar:

```
asyncpg.exceptions.DependentObjectsStillExistError:
cannot drop column flow_runner_type of table flow_run because other objects depend on it
DETAIL: view staging.stg_prefect__flow_runs depends on column flow_runner_type
ERROR: Application startup failed. Exiting.
```

El orquestador entero no arranca por culpa de un modelo de dbt, y el error aparece
durante un upgrade. Si se rehace, va como tabla y con la fuente declarada aparte para
poder excluirla del build con un `--exclude`.
