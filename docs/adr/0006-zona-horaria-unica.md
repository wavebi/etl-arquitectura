# ADR 0006 — Una sola zona horaria en todo el stack: America/Argentina/Buenos_Aires

- **Fecha:** 2026-08-18
- **Estado:** aceptado
- **Contexto:** base de datos, contenedores, dlt, dbt y Prefect

## Contexto

Un ETL toca cuatro relojes distintos: el del contenedor, el de la base, el del
proceso que escribe los datos y el del orquestador que decide cuándo correr. Si no
están alineados, no falla nada — y ese es el problema. Los síntomas aparecen como
diferencias de unas horas en los cortes diarios: un reporte "del día" que incluye
movimientos de la madrugada siguiente, un incremental que pide una ventana corrida,
un schedule que dispara tres horas antes de lo que dice el negocio.

La alternativa habitual (guardar todo en UTC y convertir en la capa de presentación)
es correcta para un producto global. Acá el negocio es argentino, quienes leen los
reportes piensan en hora local y no hay usuarios en otras zonas: la conversión
constante solo agrega superficie de error.

## Decisión

`America/Argentina/Buenos_Aires` en todo el stack, con una sola variable de entorno
(`TIMEZONE`) como fuente de verdad:

| Capa | Cómo se aplica |
|---|---|
| Base de datos | `ALTER DATABASE ... SET timezone` y `ALTER ROLE ... SET timezone` en `scripts/init_db_permissions.sql` |
| Contenedores | `TZ` en todos los servicios del compose |
| dlt | `_ingested_at` se escribe con `datetime.now(ZoneInfo(settings.TIMEZONE))` |
| dbt | hereda la sesión de la base; el macro `to_local_ts` para exponer timestamps sin zona a BI |
| Prefect | los `Cron` de los deployments se declaran con `timezone=settings.TIMEZONE` |

Los timestamps se siguen guardando como `timestamptz`, que es un **instante
absoluto**: la zona define cómo se interpreta y se muestra, no lo que se almacena.
Eso deja la puerta abierta a servir otra zona más adelante sin migrar datos.

## Consecuencias

**A favor**

- `current_date`, `now()` y los cortes diarios significan lo mismo en la base, en dbt
  y en el reporte que ve el cliente.
- Los horarios de los schedules se leen igual que se conversan con el negocio, y el
  cambio de horario no corre los procesos.
- Una sola variable para cambiarlo todo si el proyecto se muda de país.

**En contra**

- Si en el futuro hay consumidores en otra zona, hay que decidir dónde convertir.
  Como el almacenamiento es `timestamptz`, es un cambio de presentación y no de datos.
- Hay que acordarse de configurar la zona en cualquier entorno nuevo (por ejemplo, la
  base de servicio del CI).

**Mitigaciones**

- Un test de dbt (`assert_zona_horaria_es_la_del_proyecto`) falla si la sesión no está
  en la zona esperada, en cualquier entorno donde corra.
- El workflow de CI aplica la misma zona a su Postgres de servicio, así un test que
  compara contra `current_date` no pasa en el CI y falla en producción.
