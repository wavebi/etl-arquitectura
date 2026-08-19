import { query } from "@/lib/db";

/**
 * Consultas del dashboard — todas contra `marts`, ninguna contra `raw` ni `staging`.
 *
 * Se apoyan en el modelo dimensional: los hechos traen las claves foráneas y las
 * dimensiones los atributos. Ojo con dos cosas que vienen del modelado (ver la skill
 * `modelado-kimball`):
 *
 *   1. Las dimensiones tienen un miembro desconocido con clave `-1`. Hay que
 *      excluirlo de los listados, si no aparece "Sin identificar" en cada selector.
 *   2. `cotizacion` es SEMI-ADITIVA: se promedia o se toma la última, NUNCA se suma
 *      entre fechas. `variacion_pct` es NO ADITIVA.
 */

export type Kpis = {
  ultima_fecha: string;
  primera_fecha: string;
  vigentes: number;
  retiradas: number;
  observaciones: number;
  dias_publicados: number;
};

export async function getKpis(): Promise<Kpis> {
  const [row] = await query<Kpis>(`
    select
      max(f.fecha)::text                                              as ultima_fecha,
      min(f.fecha)::text                                              as primera_fecha,
      count(*)::int                                                   as observaciones,
      count(distinct f.fecha)::int                                    as dias_publicados,
      (select count(*)::int from marts.dim_moneda
        where es_vigente and clave_moneda <> '-1')                    as vigentes,
      (select count(*)::int from marts.dim_moneda
        where not es_vigente and clave_moneda <> '-1')                as retiradas
    from marts.fct_cotizacion as f
  `);
  return row;
}

export type Movimiento = {
  codigo_moneda: string;
  nombre_moneda: string;
  region: string;
  cotizacion: number;
  variacion_pct: number | null;
};

/** Mayores movimientos del último día publicado. */
export async function getMovimientosDelDia(): Promise<Movimiento[]> {
  return query<Movimiento>(`
    select
      m.codigo_moneda, m.nombre_moneda, m.region,
      f.cotizacion, f.variacion_pct
    from marts.fct_cotizacion as f
    inner join marts.dim_moneda as m on f.clave_moneda_cotizada = m.clave_moneda
    where f.fecha = (select max(fecha) from marts.fct_cotizacion)
      and f.variacion_pct is not null
    order by abs(f.variacion_pct) desc
  `);
}

export type Moneda = {
  codigo_moneda: string;
  nombre_moneda: string;
  region: string;
  es_vigente: boolean;
  primera_fecha: string;
  ultima_fecha: string;
  cantidad_dias_cotizados: number;
};

/** Catálogo para los selectores. Excluye el miembro desconocido. */
export async function getMonedas(): Promise<Moneda[]> {
  return query<Moneda>(`
    select
      codigo_moneda, nombre_moneda, region, es_vigente,
      primera_fecha::text as primera_fecha,
      ultima_fecha::text  as ultima_fecha,
      cantidad_dias_cotizados::int as cantidad_dias_cotizados
    from marts.dim_moneda
    where clave_moneda <> '-1' and codigo_moneda <> 'EUR'
    order by es_vigente desc, codigo_moneda
  `);
}

export type PuntoSerie = { fecha: string; cotizacion: number; variacion_pct: number | null };

/**
 * Serie diaria de una moneda. `desde` acota el rango.
 *
 * Se filtra por `moneda_cotizada` (clave natural desnormalizada en el hecho) y no
 * por la clave subrogada: evita un join para algo que el hecho ya trae.
 */
export async function getSerie(codigo: string, desde: string): Promise<PuntoSerie[]> {
  return query<PuntoSerie>(
    `
    select fecha::text as fecha, cotizacion, variacion_pct
    from marts.fct_cotizacion
    where moneda_cotizada = $1 and fecha >= $2::date
    order by fecha
    `,
    [codigo, desde],
  );
}

export type ResumenMensual = {
  anio_mes: string;
  cantidad_dias_publicados: number;
  cotizacion_promedio: number;
  cotizacion_minima: number;
  cotizacion_maxima: number;
  cotizacion_apertura: number;
  cotizacion_cierre: number;
  volatilidad_pct: number;
};

/** Agregado mensual. Sale de `rpt_`, que ya lo tiene calculado. */
export async function getResumenMensual(codigo: string, meses: number): Promise<ResumenMensual[]> {
  return query<ResumenMensual>(
    `
    select
      anio_mes,
      cantidad_dias_publicados::int as cantidad_dias_publicados,
      cotizacion_promedio, cotizacion_minima, cotizacion_maxima,
      cotizacion_apertura, cotizacion_cierre, volatilidad_pct
    from marts.rpt_cotizacion_mensual
    where moneda_cotizada = $1
    order by clave_mes desc
    limit $2
    `,
    [codigo, meses],
  );
}

export type MonedaRetirada = Moneda & { anio_salida: number };

/**
 * Las monedas que el origen dejó de publicar.
 *
 * Es el ángulo más distintivo de esta fuente: casi todas salen un 31 de diciembre
 * porque su país adoptó el euro. El rublo es la excepción (marzo de 2022).
 */
export async function getMonedasRetiradas(): Promise<MonedaRetirada[]> {
  return query<MonedaRetirada>(`
    select
      codigo_moneda, nombre_moneda, region, es_vigente,
      primera_fecha::text as primera_fecha,
      ultima_fecha::text  as ultima_fecha,
      cantidad_dias_cotizados::int as cantidad_dias_cotizados,
      extract(year from ultima_fecha)::int as anio_salida
    from marts.dim_moneda
    where not es_vigente and clave_moneda <> '-1'
    order by ultima_fecha desc
  `);
}

export type CoberturaMes = { anio_mes: string; dias_publicados: number; monedas: number };

/** Días con publicación y monedas cubiertas por mes. Para el tablero de calidad. */
export async function getCoberturaMensual(meses: number): Promise<CoberturaMes[]> {
  return query<CoberturaMes>(
    `
    with por_mes as (
      select
        d.anio_mes,
        d.clave_mes,
        count(distinct f.fecha)::int            as dias_publicados,
        count(distinct f.moneda_cotizada)::int  as monedas
      from marts.fct_cotizacion as f
      inner join marts.dim_mes as d
        on cast(to_char(f.fecha, 'YYYYMM') as integer) = d.clave_mes
      group by 1, 2
    )
    select anio_mes, dias_publicados, monedas
    from por_mes
    order by clave_mes desc
    limit $1
    `,
    [meses],
  );
}

export type Integridad = {
  filas_hecho: number;
  fk_moneda_desconocida: number;
  fk_fecha_desconocida: number;
  version_desconocida: number;
};

/**
 * Integridad referencial del hecho.
 *
 * Estos números existen gracias al miembro desconocido: con `inner join` las filas
 * que no resuelven desaparecerían y no habría nada que contar (ver ADR 0007). Que
 * `version_desconocida` sea alto es ESPERADO: son monedas retiradas que el catálogo
 * del origen nunca publicó, así que el snapshot no tiene historia sobre ellas.
 */
export async function getIntegridad(): Promise<Integridad> {
  const [row] = await query<Integridad>(`
    select
      count(*)::int                                                              as filas_hecho,
      count(*) filter (where clave_moneda_cotizada = '-1')::int                  as fk_moneda_desconocida,
      count(*) filter (where clave_fecha = -1)::int                              as fk_fecha_desconocida,
      count(*) filter (where clave_version_moneda_cotizada = '-1')::int          as version_desconocida
    from marts.fct_cotizacion
  `);
  return row;
}

export type ConteoRegion = { region: string; monedas: number };

export async function getMonedasPorRegion(): Promise<ConteoRegion[]> {
  return query<ConteoRegion>(`
    select region, count(*)::int as monedas
    from marts.dim_moneda
    where clave_moneda <> '-1' and es_vigente
    group by 1
    order by 2 desc, 1
  `);
}
