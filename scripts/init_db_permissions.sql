-- =========================================================================
-- Inicialización de la base: extensiones, schemas, roles, permisos y zona horaria.
-- =========================================================================
-- Idempotente: se puede correr tantas veces como haga falta.
--
-- Ejecutar como SUPERUSER (o como el admin del cluster managed):
--
--   psql -h <host> -p <port> -U <superuser> -d <base> \
--     -v etl_password=... \
--     -v prefect_password=... \
--     -v bi_password=... \
--     -v analyst_password=... \
--     -f scripts/init_db_permissions.sql
--
-- Las passwords van SIN comillas: el script las cita con `:'var'`.
--
-- En el entorno local lo corre solo el init del contenedor
-- (scripts/db/01-permissions.sh) tomando las passwords del .env.local.
--
-- ROLES
--   etl_app     dueño de los schemas de datos. Lo usan dlt y dbt.
--   prefect_app dueño del schema `prefect`, con `search_path` fijo en ese schema.
--               Es el rol con el que se conecta el server de Prefect: su migrador
--               (alembic) crea tablas SIN calificar el schema, así que la única
--               forma de que no las cree en `public` es que su rol tenga el
--               search_path apuntado al schema correcto.
--   bi_reader   solo lectura sobre marts y seeds. Es el usuario de la herramienta
--               de BI: no puede ver raw ni staging, así nadie construye un tablero
--               sobre datos sin transformar.
--   analyst     solo lectura sobre todas las capas de datos. Para explorar y
--               diagnosticar sin poder escribir.
-- =========================================================================

\set ON_ERROR_STOP on

-- Las cuatro passwords son obligatorias. Si falta alguna, se corta acá con un
-- mensaje claro en lugar de crear roles sin password o a medio configurar.
\if :{?etl_password}
\else
\echo '*** Falta -v etl_password ***'
DO $$ BEGIN RAISE EXCEPTION 'etl_password no fue provisto'; END $$;
\endif

\if :{?prefect_password}
\else
\echo '*** Falta -v prefect_password ***'
DO $$ BEGIN RAISE EXCEPTION 'prefect_password no fue provisto'; END $$;
\endif

\if :{?bi_password}
\else
\echo '*** Falta -v bi_password ***'
DO $$ BEGIN RAISE EXCEPTION 'bi_password no fue provisto'; END $$;
\endif

\if :{?analyst_password}
\else
\echo '*** Falta -v analyst_password ***'
DO $$ BEGIN RAISE EXCEPTION 'analyst_password no fue provisto'; END $$;
\endif


-- =========================================================================
-- 1. EXTENSIONES
-- =========================================================================
CREATE EXTENSION IF NOT EXISTS pg_trgm;             -- búsqueda por similitud (fuzzy match de nombres)
CREATE EXTENSION IF NOT EXISTS pgcrypto;            -- gen_random_uuid(), hashes del lado de la base
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;  -- diagnóstico de queries lentas


-- =========================================================================
-- 2. SCHEMAS — alineados con shared/constants.py y con dbt_project.yml
-- =========================================================================
CREATE SCHEMA IF NOT EXISTS raw;             -- crudo, EXACTO como llegó del origen (lo escribe dlt)
CREATE SCHEMA IF NOT EXISTS raw_staging;     -- área temporal que usa dlt durante el merge
CREATE SCHEMA IF NOT EXISTS staging;         -- stg_*: views 1:1 con raw, tipadas y en español
CREATE SCHEMA IF NOT EXISTS marts;           -- dim_/fct_/rpt_: lo que consume BI
CREATE SCHEMA IF NOT EXISTS scd2;            -- historia de lo que el origen pisa (SCD Type 2)
CREATE SCHEMA IF NOT EXISTS seeds;           -- dbt seeds (CSVs versionados)
CREATE SCHEMA IF NOT EXISTS dbt_test_audit;  -- store_failures: filas que fallaron los tests
CREATE SCHEMA IF NOT EXISTS prefect;         -- metadata del orquestador (flow runs, deployments)

-- NO se crea `intermediate`: sus modelos son ephemeral (dbt los inlinea en quien
-- los consume) y el schema quedaría vacío. Si alguna vez uno se materializa como
-- tabla, dbt lo crea solo — para eso etl_app tiene CREATE sobre la base.


-- =========================================================================
-- 3. ROLES
-- =========================================================================
-- psql NO interpola variables dentro de un bloque $$...$$, así que la existencia
-- del rol se pregunta afuera (\gset) y el CREATE ROLE va como sentencia suelta.
--
-- ## Qué pasa con las passwords cuando el rol YA existe
--
-- Este script corre en cada deploy, así que la respuesta importa y NO es la misma
-- para los cuatro roles:
--
--   etl_app y prefect_app  →  SE SINCRONIZAN siempre (ALTER ROLE más abajo).
--       Son los roles del stack: sus claves ya viajan en el mismo `.env` que se
--       renderiza desde los secrets, y el worker se conecta con ellas. Si el secret
--       cambiara y la base no, el deploy dejaría al ETL sin poder conectarse. Acá el
--       secret ES la fuente de verdad.
--
--   bi_reader y analyst    →  se crean si faltan, y NUNCA se les pisa la clave.
--       Son de personas y de herramientas configuradas a mano (el tablero de BI, el
--       cliente SQL del analista). Sincronizarlas desde un secret significaría que un
--       placeholder olvidado rompe el tablero en el próximo deploy, sin aviso y sin
--       relación aparente con lo que se desplegó. Rotarlas es un ALTER ROLE explícito.
SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_app'))::int AS need_etl \gset
\if :need_etl
CREATE ROLE etl_app LOGIN PASSWORD :'etl_password';
\echo 'Rol etl_app creado.'
\endif

SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'prefect_app'))::int AS need_prefect \gset
\if :need_prefect
CREATE ROLE prefect_app LOGIN PASSWORD :'prefect_password';
\echo 'Rol prefect_app creado.'
\endif

SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bi_reader'))::int AS need_bi \gset
\if :need_bi
CREATE ROLE bi_reader LOGIN PASSWORD :'bi_password';
\echo 'Rol bi_reader creado.'
\endif

SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'analyst'))::int AS need_analyst \gset
\if :need_analyst
CREATE ROLE analyst LOGIN PASSWORD :'analyst_password';
\echo 'Rol analyst creado.'
\endif

-- Sincronización de las claves del stack. Va SIEMPRE, exista o no el rol de antes:
-- es lo que hace que rotar una clave sea "cambiar el secret y desplegar".
-- `LOGIN` se reafirma por las dudas de que alguien lo haya revocado a mano.
ALTER ROLE etl_app     WITH LOGIN PASSWORD :'etl_password';
ALTER ROLE prefect_app WITH LOGIN PASSWORD :'prefect_password';

-- Conexión a la base para los cuatro roles, y CREATE para el dueño del ETL: dlt y
-- dbt necesitan poder crear un schema nuevo (un dataset nuevo, o `intermediate` si
-- algún día deja de ser ephemeral).
DO $$
DECLARE
    db text := current_database();
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO etl_app, prefect_app, bi_reader, analyst', db);
    EXECUTE format('GRANT CREATE ON DATABASE %I TO etl_app', db);
END $$;


-- =========================================================================
-- 4. ZONA HORARIA — hora de Argentina en todo el stack
-- =========================================================================
-- La base manda: toda sesión que no la pise explícitamente ve y escribe en hora
-- local. Esto cubre a dlt, a dbt, a Prefect y a cualquier consulta manual, sin
-- depender de que cada cliente esté bien configurado.
--
-- Los timestamps se siguen guardando como `timestamptz` (un instante absoluto):
-- lo que fija la zona es cómo se interpretan y se muestran, no lo que se almacena.
-- Mezclar zonas es de los errores más caros en un ETL: los reportes cierran mal por
-- unas horas y nadie entiende por qué.
DO $$
DECLARE
    db text := current_database();
BEGIN
    EXECUTE format('ALTER DATABASE %I SET timezone TO ''America/Argentina/Buenos_Aires''', db);
    EXECUTE format('ALTER DATABASE %I SET datestyle TO ''ISO, DMY''', db);
END $$;

-- Y también a nivel de ROL, para los que escriben y consultan datos: si alguien
-- cambia el default de la base, estas sesiones siguen en hora local.
ALTER ROLE etl_app SET timezone TO 'America/Argentina/Buenos_Aires';
ALTER ROLE bi_reader SET timezone TO 'America/Argentina/Buenos_Aires';
ALTER ROLE analyst SET timezone TO 'America/Argentina/Buenos_Aires';
-- prefect_app queda con el default de la base (el mismo valor): no se le toca la
-- sesión para no alterar cómo el orquestador maneja sus propios timestamps.


-- =========================================================================
-- 5. etl_app — dueño y escritor de todos los schemas del ETL
-- =========================================================================
-- Necesita ser OWNER (no solo tener CREATE): dbt dropea y recrea tablas y vistas en
-- cada corrida, y eso solo lo puede hacer el dueño del objeto.
DO $$
DECLARE
    s text;
    etl_schemas text[] := ARRAY[
        'raw', 'raw_staging', 'staging', 'marts', 'scd2', 'seeds', 'dbt_test_audit'
    ];
BEGIN
    FOREACH s IN ARRAY etl_schemas LOOP
        EXECUTE format('ALTER SCHEMA %I OWNER TO etl_app', s);
        EXECUTE format('GRANT USAGE, CREATE ON SCHEMA %I TO etl_app', s);
        EXECUTE format('GRANT ALL ON ALL TABLES IN SCHEMA %I TO etl_app', s);
        EXECUTE format('GRANT ALL ON ALL SEQUENCES IN SCHEMA %I TO etl_app', s);
        -- Default privileges: aplica a los objetos que se creen a futuro. Sin esto,
        -- cada tabla nueva de dlt/dbt necesitaría un GRANT manual.
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON TABLES TO etl_app', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT ALL ON SEQUENCES TO etl_app', s);
    END LOOP;
END $$;


-- =========================================================================
-- 6. prefect_app — dueño del schema del orquestador
-- =========================================================================
-- El `search_path` a nivel de ROL es lo que hace que alembic (el migrador de
-- Prefect) cree sus tablas en `prefect` y no en `public`. Sin esto el arranque del
-- server falla con "permission denied for schema public".
--
-- `prefect` primero (ahí crea sus tablas) y `public` después: sus migraciones crean
-- índices GIN con `gin_trgm_ops`, que es un operador de la extensión pg_trgm y vive
-- en `public`. Sin `public` en el path falla con:
--   operator class "gin_trgm_ops" does not exist for access method "gin"
ALTER SCHEMA prefect OWNER TO prefect_app;
GRANT USAGE, CREATE ON SCHEMA prefect TO prefect_app;
ALTER ROLE prefect_app SET search_path = prefect, public;

-- El schema queda AISLADO: ningún otro rol lo lee. La metadata del orquestador es
-- estado interno de una herramienta, no datos de negocio, y modelarla con dbt tiene
-- un costo alto (ver docs/adr/0003). Para ver cómo vienen las corridas está la UI de
-- Prefect, que es su interfaz natural.


-- =========================================================================
-- 7. bi_reader — solo lectura sobre marts y seeds
-- =========================================================================
-- Deliberadamente NO ve raw ni staging: si la herramienta de BI puede leer datos sin
-- transformar, alguien va a construir un tablero sobre ellos y ese tablero se va a
-- romper en la próxima corrida.
--
-- Tampoco ve `scd2`: son tablas de historia con versiones vigentes y vencidas
-- mezcladas. Lo que BI consume es la dimensión (foto actual) o la vista de historia
-- publicada en marts.
REVOKE ALL ON SCHEMA public FROM bi_reader;

DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['marts', 'seeds'] LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO bi_reader', s);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO bi_reader', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE etl_app IN SCHEMA %I GRANT SELECT ON TABLES TO bi_reader', s);
    END LOOP;
END $$;


-- =========================================================================
-- 8. analyst — solo lectura sobre todas las capas de datos
-- =========================================================================
-- Incluye raw (para diagnosticar de dónde salió un número) y excluye `prefect`
-- (estado interno del orquestador, no datos de negocio).
DO $$
DECLARE
    s text;
BEGIN
    FOREACH s IN ARRAY ARRAY['raw', 'staging', 'marts', 'scd2', 'seeds', 'dbt_test_audit'] LOOP
        EXECUTE format('GRANT USAGE ON SCHEMA %I TO analyst', s);
        EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO analyst', s);
        EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE etl_app IN SCHEMA %I GRANT SELECT ON TABLES TO analyst', s);
    END LOOP;
END $$;


-- =========================================================================
-- 9. public — cerrado
-- =========================================================================
-- Desde Postgres 15 `public` ya no es escribible por todos, pero en bases migradas
-- puede seguir abierto. Se cierra explícitamente: ningún objeto del proyecto vive
-- ahí (salvo las extensiones).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;


-- =========================================================================
-- 10. Verificación
-- =========================================================================
SELECT
    n.nspname                              AS schema,
    pg_catalog.pg_get_userbyid(n.nspowner) AS owner
FROM pg_catalog.pg_namespace AS n
WHERE n.nspname IN (
    'raw', 'raw_staging', 'staging', 'marts', 'scd2', 'seeds', 'dbt_test_audit', 'prefect'
)
ORDER BY 1;

SELECT current_setting('TimeZone') AS timezone_de_la_sesion;
