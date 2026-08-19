# Dashboard de cotizaciones

Tableros sobre los marts del warehouse. Next.js 16 · React 19 · shadcn/ui · Recharts.

## Cómo lee los datos

Server Components consultando Postgres **directo**, sin capa de API, con el rol
`bi_reader`. Ese rol tiene `SELECT` únicamente sobre `marts` y `seeds`; no ve `raw` ni
`staging` a propósito, para que nadie construya un tablero sobre datos sin transformar
y se le rompa en la próxima corrida del ETL (ver `scripts/init_db_permissions.sql`).

O sea que **el contrato entre el ETL y el dashboard son los marts**, y nada más. Si un
tablero necesita un dato que no está ahí, la respuesta es agregar un modelo de dbt, no
consultar staging desde acá.

Todas las páginas declaran `dynamic = "force-dynamic"`: se renderizan por request y el
build no necesita una base viva.

## Los tableros

| Ruta | Qué muestra |
|---|---|
| `/` | KPIs del histórico, mayores movimientos del día, monedas por región |
| `/monedas` | Serie diaria de una moneda con selector y rango, más el resumen mensual |
| `/euro` | Las monedas que dejaron de publicarse, agrupadas por año de salida |
| `/calidad` | Integridad referencial del hecho y cobertura mensual |

## Correrlo

Con el stack completo (recomendado) — queda en http://localhost:3000:

```bash
make up
```

Suelto, contra el Postgres del compose:

```bash
cd dashboard
cp .env.example .env.local     # y completá la clave de bi_reader
npm install
npm run dev
```

## Notas de implementación

- **Los filtros van al SQL, no al navegador.** El selector escribe en la query string y
  el Server Component vuelve a consultar. Mandar 27 años de serie al cliente para
  recortarla en JS sería absurdo.
- **`pg` devuelve `NUMERIC` como string** para no perder precisión. Se convierte a
  `number` en `lib/db.ts`, en el borde, porque los valores van directo a un gráfico.
- **El eje Y de las series no arranca en cero.** Son tipos de cambio: lo que importa es
  la variación relativa, y forzar el cero volvería invisible un movimiento del 3%.
- **`cotizacion` es semi-aditiva**: se promedia o se toma la última, nunca se suma entre
  fechas. `variacion_pct` no es aditiva. Está documentado en el hecho.
