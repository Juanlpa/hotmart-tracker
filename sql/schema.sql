-- ============================================================
-- Hotmart Tracker — Schema SQL completo para Supabase
-- ============================================================
-- INSTRUCCIÓN: ejecutar completo en Supabase SQL Editor
-- El orden de CREATE TABLE importa por foreign keys

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Tabla de productos (datos base)
CREATE TABLE IF NOT EXISTS productos (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    hotmart_id      VARCHAR(50) UNIQUE NOT NULL,
    nombre          TEXT NOT NULL,
    categoria       TEXT,
    precio          NUMERIC(10,2),
    comision_pct    NUMERIC(5,2),
    url_venta       TEXT,
    creado_en       TIMESTAMPTZ DEFAULT NOW()
);

-- Snapshots diarios con señales y scores
CREATE TABLE IF NOT EXISTS snapshots_diarios (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    producto_id         UUID NOT NULL REFERENCES productos(id) ON DELETE CASCADE,
    fecha               DATE NOT NULL,
    -- Datos de Hotmart
    temperatura         NUMERIC(5,2),
    rating              NUMERIC(3,2),
    num_ratings         INTEGER,
    precio_snapshot     NUMERIC(10,2),
    comision_snapshot   NUMERIC(5,2),
    -- Datos de señales externas
    fb_advertisers      INTEGER,
    fb_producer_only    BOOLEAN,
    fb_impression_range TEXT,
    trends_slope        NUMERIC(6,4),
    trends_at_peak      BOOLEAN,
    trends_seasonal     BOOLEAN,
    yt_recent_videos    INTEGER,
    yt_affiliate_videos INTEGER,
    -- Score calculado
    score_hotmart       NUMERIC(5,2),
    score_fb            NUMERIC(5,2),
    score_trends        NUMERIC(5,2),
    score_youtube       NUMERIC(5,2),
    score_total         NUMERIC(5,2),
    viable_channels     TEXT[],
    channel_risk        TEXT,
    -- Control
    scraper_ok          BOOLEAN DEFAULT TRUE,
    UNIQUE(producto_id, fecha)
);

-- Alertas enviadas
CREATE TABLE IF NOT EXISTS alertas (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    producto_id     UUID NOT NULL REFERENCES productos(id),
    snapshot_id     UUID NOT NULL REFERENCES snapshots_diarios(id),
    fecha_alerta    TIMESTAMPTZ DEFAULT NOW(),
    score_total     NUMERIC(5,2),
    canales         TEXT[],
    mensaje_enviado TEXT,
    -- Retroalimentación manual del operador
    promovido       BOOLEAN,
    resultado       TEXT CHECK (resultado IN ('ganador', 'perdedor', 'no_promovido'))
);

-- Caché de Google Trends (obligatorio per spec)
CREATE TABLE IF NOT EXISTS trends_cache (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    keyword     TEXT NOT NULL,
    geo         TEXT NOT NULL DEFAULT 'BR',
    data        JSONB NOT NULL,
    cached_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(keyword, geo)
);

-- Índices para queries frecuentes del backtesting
CREATE INDEX IF NOT EXISTS idx_snapshots_producto_fecha ON snapshots_diarios(producto_id, fecha DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_score ON snapshots_diarios(score_total DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_fecha ON alertas(fecha_alerta DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_resultado ON alertas(resultado) WHERE resultado IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_trends_cache_keyword ON trends_cache(keyword, geo);
