import { Pool, types } from "pg";

/**
 * Conexión al warehouse — SOLO LECTURA.
 *
 * Se conecta con el rol `bi_reader`, que tiene `SELECT` únicamente sobre `marts` y
 * `seeds`. No es una precaución del dashboard: es la política del warehouse (ver
 * scripts/init_db_permissions.sql). Deliberadamente NO ve `raw` ni `staging`, para
 * que nadie construya un tablero sobre datos sin transformar y se le rompa en la
 * próxima corrida del ETL.
 *
 * O sea que el contrato entre el ETL y este dashboard son los marts, y nada más.
 */

// `pg` devuelve NUMERIC como string para no perder precisión con decimales grandes.
// Acá los valores son cotizaciones y porcentajes que van directo a un gráfico, así
// que se convierten a number en el borde. Los enteros de 8 bytes se dejan como
// vienen: ninguno de los conteos se acerca a los límites de un number de JS, pero
// convertirlos en silencio sería una trampa si algún día lo hicieran.
types.setTypeParser(types.builtins.NUMERIC, (v) => Number.parseFloat(v));

const globalForPool = globalThis as unknown as { pool?: Pool };

// En desarrollo, Next recarga los módulos en cada cambio. Sin este singleton, cada
// recarga abriría un pool nuevo y Postgres terminaría rechazando conexiones.
export const pool =
  globalForPool.pool ??
  new Pool({
    host: process.env.DB_HOST ?? "localhost",
    port: Number(process.env.DB_PORT ?? 5442),
    database: process.env.DB_NAME ?? "warehouse",
    user: process.env.DB_USER ?? "bi_reader",
    password: process.env.DB_PASSWORD,
    ssl: process.env.DB_SSLMODE === "require" ? { rejectUnauthorized: false } : false,
    max: 5,
    idleTimeoutMillis: 30_000,
    // Si el warehouse no responde, es mejor un error claro que un tablero colgado.
    connectionTimeoutMillis: 5_000,
  });

if (process.env.NODE_ENV !== "production") globalForPool.pool = pool;

/** Ejecuta una consulta parametrizada y devuelve las filas tipadas. */
export async function query<T>(sql: string, params: unknown[] = []): Promise<T[]> {
  const { rows } = await pool.query(sql, params);
  return rows as T[];
}
