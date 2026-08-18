# ADR 0005 — La capa raw conserva los nombres del origen

- **Fecha:** 2026-08-18
- **Estado:** aceptado
- **Contexto:** capa de ingesta (`ingestion/pipelines/*/runner.py`) y staging de dbt

## Contexto

La primera capa del warehouse se llama `raw` porque su contrato es exactamente ese:
guardar lo que el origen dijo, sin interpretar. Es la única copia que tenemos de la
respuesta del origen; si transformamos al ingerir y la regla estaba mal, hay que
volver a pedirle todo al cliente (lento, y a veces imposible porque el sistema ya
pisó el dato).

Por defecto, dlt **normaliza los nombres**: aplica una convención `snake_case` que
pasa todo a minúsculas y reemplaza los separadores. Una API que devuelve
`FechaEmisión` termina en una columna `fecha_emision`, y una que devuelve `Ano-Mes`
en `ano_mes`. Eso significa que raw ya no es auditable contra el origen: para saber
si el ETL perdió un campo hay que reconstruir mentalmente la transformación.

Peor: la normalización puede colapsar dos campos distintos del origen en el mismo
nombre (`Total` y `TOTAL` → `total`), y ese conflicto aparece como datos pisados, no
como error.

## Decisión

Configurar dlt con la convención `direct`, que preserva los nombres tal cual:

```python
dlt.config["schema.naming"] = "direct"
```

Se fija **en código** (`make_pipeline`) y no solo por variable de entorno: si
dependiera de un `.env`, un archivo incompleto haría que raw cambie de nombres sin
que nadie lo note.

El renombre —y el pasaje al español— pasa a ser responsabilidad exclusiva de la capa
de staging, donde queda versionado, revisable en un diff y documentado en el YAML del
modelo.

## Consecuencias

**A favor**

- `raw` es auditable contra la respuesta del origen: se puede comparar columna por
  columna con la documentación de la API o con un `curl`.
- El renombre es explícito y está en un solo lugar. Antes estaba repartido entre una
  convención implícita de dlt y el SQL de staging.
- Desaparece el riesgo de que dos campos distintos colisionen en un mismo nombre.

**En contra**

- Los identificadores del origen suelen necesitar comillas en SQL, porque Postgres
  pliega a minúsculas todo lo que no esté citado:
  `select "FechaEmisión" as fecha_emision from raw...`. En el ejemplo pasa incluso
  con nombres simples: `date` es palabra reservada.
- Un origen con nombres muy sucios (espacios, acentos, mayúsculas mezcladas) hace
  que los modelos de staging se lean peor. Es el lugar correcto para que ese ruido
  duela: en la frontera, una sola vez.

**Mitigaciones**

- Un test de integración
  (`test_los_nombres_de_columna_son_los_del_origen`) verifica que las columnas de raw
  sigan siendo las del origen. Si alguien saca la configuración, falla ahí y no en el
  primer modelo de staging que deje de compilar.
