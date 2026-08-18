-- =========================================================================
-- Datos mínimos de `raw` para que el CI pueda correr `dbt build` de verdad.
-- =========================================================================
-- Por qué existe: compilar los modelos no alcanza. Un `dbt compile` no detecta
-- una columna que no existe, un cast imposible, un join que multiplica filas ni un
-- test que no se cumple — todo eso aparece recién al ejecutar. Sin esto, un cambio
-- en los modelos se descubre roto en la próxima corrida del ETL, en producción.
--
-- Es un fixture DELIBERADAMENTE chico: no busca cubrir datos, busca ejecutar todo
-- el DAG (staging → intermediate → marts → snapshots → tests) sobre filas reales.
--
-- Las columnas son las de `raw`, o sea las del ORIGEN (ver ADR 0005): si la API
-- cambia sus nombres, este archivo deja de cargar y el CI avisa antes de que falle
-- el staging.
-- =========================================================================

CREATE TABLE IF NOT EXISTS raw.raw_frankfurter_exchange_rates (
    "date"         date NOT NULL,
    "base"         varchar NOT NULL,
    "currency"     varchar NOT NULL,
    "rate"         numeric(20, 8) NOT NULL,
    "amount"       numeric(20, 8),
    _ingested_at   timestamptz NOT NULL,
    _source        varchar NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.raw_frankfurter_currencies (
    "code"         varchar NOT NULL,
    "name"         varchar NOT NULL,
    _ingested_at   timestamptz NOT NULL,
    _source        varchar NOT NULL
);

TRUNCATE raw.raw_frankfurter_exchange_rates;
TRUNCATE raw.raw_frankfurter_currencies;

-- Cotizaciones: viernes, lunes y martes (el fin de semana NO tiene filas, igual que
-- en el origen). Así `dias_desde_anterior` da 3 en el lunes y el modelo de
-- intermediate se ejercita de verdad.
--
-- GRD (dracma) aparece solo en el histórico y NO está en el catálogo: reproduce el
-- caso real de una moneda discontinuada, que es lo que fuerza a la dimensión a
-- unir observadas + catálogo.
INSERT INTO raw.raw_frankfurter_exchange_rates ("date", "base", "currency", "rate", "amount", _ingested_at, _source) VALUES
    ('2026-01-02', 'EUR', 'USD', 1.17210000, 1, now(), 'frankfurter.raw_frankfurter_exchange_rates'),
    ('2026-01-02', 'EUR', 'BRL', 6.37430000, 1, now(), 'frankfurter.raw_frankfurter_exchange_rates'),
    ('2026-01-02', 'EUR', 'GRD', 340.75000000, 1, now(), 'frankfurter.raw_frankfurter_exchange_rates'),
    ('2026-01-05', 'EUR', 'USD', 1.16640000, 1, now(), 'frankfurter.raw_frankfurter_exchange_rates'),
    ('2026-01-05', 'EUR', 'BRL', 6.34700000, 1, now(), 'frankfurter.raw_frankfurter_exchange_rates'),
    ('2026-01-05', 'EUR', 'GRD', 340.75000000, 1, now(), 'frankfurter.raw_frankfurter_exchange_rates'),
    ('2026-01-06', 'EUR', 'USD', 1.17070000, 1, now(), 'frankfurter.raw_frankfurter_exchange_rates'),
    ('2026-01-06', 'EUR', 'BRL', 6.32010000, 1, now(), 'frankfurter.raw_frankfurter_exchange_rates'),
    -- Cotización enorme: reproduce el caso de las monedas con valores de seis cifras
    -- (la lira turca vieja), que es el que rompe la precisión de la inversa.
    ('2026-01-06', 'EUR', 'IDR', 20677.34000000, 1, now(), 'frankfurter.raw_frankfurter_exchange_rates');

INSERT INTO raw.raw_frankfurter_currencies ("code", "name", _ingested_at, _source) VALUES
    ('USD', 'United States Dollar', now(), 'frankfurter.raw_frankfurter_currencies'),
    ('BRL', 'Brazilian Real', now(), 'frankfurter.raw_frankfurter_currencies'),
    ('IDR', 'Indonesian Rupiah', now(), 'frankfurter.raw_frankfurter_currencies');
