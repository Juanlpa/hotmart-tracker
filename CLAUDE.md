# SPEC: Hotmart Affiliate Product Tracker
# Optimizado para Claude Code — prioridad: ejecución sobre explicación

---

## REGLAS DE INTERPRETACIÓN PARA CLAUDE CODE

1. Cada `## PHASE` es una sesión de trabajo independiente. No saltes fases.
2. Cada `### TASK` tiene un `ACCEPTANCE_CRITERIA` — no marques la tarea como completa si el criterio no se cumple.
3. Los `# CONTRACT:` en funciones son invariantes. No los cambies sin actualizar todos los llamadores.
4. Si encuentras ambigüedad en una tarea, resuelve con el principio: **errores explícitos > fallos silenciosos**.
5. Nunca uses `print()` para logging. Usa siempre el módulo `logging` configurado en `src/core/logger.py`.
6. Cada módulo nuevo requiere su test en `tests/` antes de integrarlo al pipeline principal.

---

## PROJECT STRUCTURE (crear exactamente esto)

```
hotmart-tracker/
├── CLAUDE.md                    ← este archivo
├── .env.example                 ← variables requeridas (sin valores)
├── .env                         ← valores reales (gitignore)
├── requirements.txt
├── pyproject.toml
│
├── src/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── logger.py            ← configuración central de logging
│   │   ├── config.py            ← carga y valida .env con pydantic
│   │   └── db.py                ← cliente Supabase singleton
│   │
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── hotmart.py           ← Playwright scraper con resiliencia
│   │   └── integrity.py         ← validación de datos antes de escribir DB
│   │
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── facebook.py          ← FB Ad Library API
│   │   ├── trends.py            ← Google Trends via pytrends
│   │   └── youtube.py           ← YouTube Data API v3
│   │
│   ├── scoring/
│   │   ├── __init__.py
│   │   ├── calculator.py        ← Score compuesto 0-100
│   │   ├── channel_filter.py    ← filtro de viabilidad de canal
│   │   └── weights.py           ← pesos W1-W4, recalibrables
│   │
│   ├── alerts/
│   │   ├── __init__.py
│   │   └── telegram.py          ← formatea y envía alertas
│   │
│   ├── backtesting/
│   │   ├── __init__.py
│   │   └── analyzer.py          ← correlación señales → resultados
│   │
│   └── pipeline.py              ← orquestador principal, llamado por cron
│
├── tests/
│   ├── test_integrity.py
│   ├── test_scoring.py
│   ├── test_channel_filter.py
│   └── test_alerts.py
│
├── sql/
│   └── schema.sql               ← DDL completo para Supabase
│
└── scripts/
    ├── setup_db.py              ← ejecuta schema.sql contra Supabase
    └── run_backtest.py          ← ejecuta backtesting manualmente
```

---

## ENVIRONMENT VARIABLES (.env.example)

```bash
# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=        # service_role key, NO la anon key

# APIs externas
FB_ACCESS_TOKEN=             # Meta for Developers → Ad Library API
YT_API_KEY=                  # Google Cloud Console → YouTube Data API v3

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Hotmart (solo para separar IPs — ver nota ToS)
HOTMART_SCRAPER_PROXY=       # opcional: ip:puerto de proxy residencial

# Configuración del pipeline
TARGET_MARKET=BR             # código de país para FB + Trends + YouTube
SCORE_ALERT_THRESHOLD=65     # score mínimo para disparar alerta (0-100)
MIN_COMMISSION_PCT=60        # filtro duro: comisión mínima aceptable
MIN_RATING=4.0               # filtro duro: evaluación mínima aceptable
SCRAPER_DELAY_MIN=3          # segundos mínimos entre requests
SCRAPER_DELAY_MAX=7          # segundos máximos entre requests
```

---

## REQUIREMENTS (requirements.txt)

```
playwright==1.44.0
playwright-stealth==1.0.6       # anti-detección de headless browser
supabase==2.4.2
pydantic==2.7.1
pydantic-settings==2.3.0
pytrends==4.9.2
google-api-python-client==2.131.0
requests==2.32.2
numpy==1.26.4
python-dotenv==1.0.1
fake-useragent==1.5.1            # User-Agent aleatorio para scraper
tenacity==8.3.0                  # retry centralizado con backoff
pytest==8.2.0
pytest-asyncio==0.23.7
```

---

## TIPOS COMPARTIDOS (definir en src/core/config.py)

```python
# Todos los módulos importan estos tipos desde aquí
# NO redefinir tipos en otros módulos

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

@dataclass
class ProductSnapshot:
    hotmart_id: str
    nombre: str
    categoria: str
    precio: float
    moneda: str = "BRL"           # ISO 4217, para soporte multi-mercado futuro
    comision_pct: float          # 0-100
    temperatura: float           # 0-100, métrica de Hotmart
    rating: float                # 0-5
    num_ratings: int
    url_venta: str
    fecha: date

@dataclass
class SignalData:
    fb_advertisers_count: int        # anunciantes únicos en últimas 2 semanas
    fb_is_producer_only: bool        # True si el único anunciante es el productor
    fb_impression_range: str         # "LOW"(<1K) | "MEDIUM"(1K-10K) | "HIGH"(>10K)
    trends_slope_30d: float          # pendiente normalizada -1 a 1
    trends_at_peak: bool             # True si estamos en máximo histórico
    trends_seasonal: bool            # True si el pico es predeciblemente estacional
    yt_recent_videos_count: int      # videos del tema en últimos 14 días
    yt_affiliate_videos: int         # videos que son reseñas de afiliados

@dataclass
class ScoredProduct:
    snapshot: ProductSnapshot
    signals: SignalData
    score_hotmart: float             # 0-25
    score_fb: float                  # 0-35
    score_trends: float              # 0-25
    score_youtube: float             # 0-15
    score_total: float               # 0-100
    viable_channels: list[str]       # ["FB_ADS", "YOUTUBE", "SEO"]
    channel_risk: Literal["LOW", "MEDIUM", "HIGH"]
    alert_triggered: bool
```

---

## PHASE 1 — Core Infrastructure

**Objetivo:** Configuración, DB y logging funcionando. Sin esto nada más corre.
**Duración estimada para Claude Code:** 1 sesión

---

### TASK 1.1 — Config con validación

**Archivo:** `src/core/config.py`

```python
# INSTRUCCIÓN: usar pydantic-settings para cargar .env con validación estricta
# Si falta cualquier variable requerida → lanzar error descriptivo al iniciar
# NO usar os.getenv() directamente en ningún otro módulo

from pydantic_settings import BaseSettings
from pydantic import validator

class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    fb_access_token: str
    yt_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    hotmart_scraper_proxy: str | None = None
    target_market: str = "BR"
    score_alert_threshold: int = 65
    min_commission_pct: float = 60.0
    min_rating: float = 4.0
    scraper_delay_min: float = 3.0
    scraper_delay_max: float = 7.0

    @validator('score_alert_threshold')
    def threshold_range(cls, v):
        assert 0 <= v <= 100, "SCORE_ALERT_THRESHOLD debe estar entre 0 y 100"
        return v

    class Config:
        env_file = ".env"

# Singleton — importar `settings` en todos los módulos, no instanciar Settings() de nuevo
settings = Settings()
```

**ACCEPTANCE_CRITERIA:**
```bash
# Debe pasar sin errores con .env completo
python -c "from src.core.config import settings; print('OK:', settings.target_market)"

# Debe fallar con mensaje claro si falta variable
# Eliminar SUPABASE_URL del .env temporalmente → debe mostrar error de validación, no KeyError
```

---

### TASK 1.2 — Schema SQL

**Archivo:** `sql/schema.sql`

```sql
-- INSTRUCCIÓN: ejecutar completo en Supabase SQL Editor
-- El orden de CREATE TABLE importa por foreign keys

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

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

-- Índices para queries frecuentes del backtesting
CREATE INDEX IF NOT EXISTS idx_snapshots_producto_fecha ON snapshots_diarios(producto_id, fecha DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots_score ON snapshots_diarios(score_total DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_fecha ON alertas(fecha_alerta DESC);
CREATE INDEX IF NOT EXISTS idx_alertas_resultado ON alertas(resultado) WHERE resultado IS NOT NULL;
```

**ACCEPTANCE_CRITERIA:**
```bash
# Ejecutar setup_db.py después de crear el schema
python scripts/setup_db.py
# Debe imprimir: "Tables created: productos, snapshots_diarios, alertas"
# Verificar en Supabase Table Editor que las 3 tablas existen con sus columnas
```

---

### TASK 1.3 — Cliente DB Singleton

**Archivo:** `src/core/db.py`

```python
# CONTRACT: esta es la ÚNICA forma de acceder a Supabase en todo el proyecto
# Todos los módulos hacen: from src.core.db import db
# Nadie instancia supabase.create_client() por su cuenta

# Implementar:
# - get_or_create_product(hotmart_id, nombre, ...) → UUID del producto
# - save_snapshot(producto_id, snapshot_data: dict) → UUID del snapshot
#     IMPORTANTE: usar UPSERT con on_conflict="producto_id,fecha"
#     para evitar errores si el pipeline se re-ejecuta el mismo día
# - get_yesterday_snapshot(producto_id) → dict | None
# - save_alert(producto_id, snapshot_id, scored_product) → UUID de alerta
# - get_products_for_backtest(dias_atras: int) → list[dict]
# - get_cached_trends(keyword, max_age_hours=24) → dict | None
# - save_trends_cache(keyword, data: dict) → None
```

---

## PHASE 2 — Hotmart Scraper

**Objetivo:** Scraper funcional con resiliencia. Esta phase no toca señales externas.
**Regla crítica de este phase:** IP del scraper NUNCA debe ser la misma que la cuenta Hotmart del operador.

---

### TASK 2.1 — Scraper principal

**Archivo:** `src/scrapers/hotmart.py`

```python
# ANTI-DETECCIÓN: usar playwright-stealth para evitar bloqueos
# from playwright_stealth import stealth_sync
# Después de crear la página: stealth_sync(page)

# RETRY CENTRALIZADO: usar tenacity en vez de retry manual
from tenacity import retry, stop_after_attempt, wait_exponential

# CONTRACT de scrape_category():
#   Input:  category_url: str, max_retries: int = 3
#   Output: list[ProductSnapshot] | None
#   - Retorna None (NO lanza excepción) si falla después de max_retries
#   - Llama notify_scraper_failure() antes de retornar None
#   - Delays aleatorios entre settings.scraper_delay_min y settings.scraper_delay_max
#   - User-Agent aleatorio en cada request (usar fake_useragent)
#   - Si settings.hotmart_scraper_proxy está definido, úsalo en Playwright
#   - Backoff exponencial via @retry de tenacity

# CONTRACT de scrape_all_categories():
#   Input:  categories: list[str]  (lista de URLs de categorías Hotmart)
#   Output: list[ProductSnapshot]  (lista plana, todas las categorías)
#   - Si una categoría falla, continúa con las demás (no aborta todo)
#   - Loguea cuántas categorías fallaron al final

# CAMPOS A EXTRAER de cada producto en Hotmart marketplace:
#   hotmart_id   → atributo data-id o equivalente en el DOM
#   nombre       → título del producto
#   categoria    → de la URL o breadcrumb
#   precio       → precio en la moneda local
#   moneda       → detectar del DOM o usar default según TARGET_MARKET
#   comision_pct → porcentaje de comisión mostrado
#   temperatura  → valor numérico de "temperatura" de Hotmart
#   rating       → puntuación promedio (ej: 4.7)
#   num_ratings  → número de evaluaciones
#   url_venta    → link a la página de ventas del producto

# NOTA PARA CLAUDE CODE: el DOM de Hotmart puede cambiar.
# Si los selectores no funcionan, inspeccionar https://hotmart.com/es/marketplace
# y actualizar los selectores antes de continuar.
# Documentar los selectores usados en un comentario al inicio del archivo.
```

---

### TASK 2.2 — Validación de integridad

**Archivo:** `src/scrapers/integrity.py`

```python
# CONTRACT de validate_scrape_result():
#   Input:  today: list[ProductSnapshot], yesterday: list[ProductSnapshot] | None
#   Output: tuple[bool, str]  → (es_valido, motivo_si_falla)
#
# REGLAS DE VALIDACIÓN (todas deben pasar):
#   R1: len(today) >= 10
#       motivo: "Menos de 10 productos — scraper probablemente bloqueado"
#
#   R2: Si yesterday existe → len(today) >= len(yesterday) * 0.80
#       motivo: f"Solo {len(today)} productos vs {len(yesterday)} de ayer (umbral 80%)"
#
#   R3: Si len(today) > 1:
#       temperaturas = [p.temperatura for p in today]
#       max(temperaturas) - min(temperaturas) > 1.0
#       motivo: "Todas las temperaturas son iguales — datos congelados"
#
#   R4: Al menos 80% de productos tienen url_venta no vacía
#       motivo: f"Solo {pct}% con url_venta — posible cambio de DOM"

# TEST requerido en tests/test_integrity.py:
#   - test caso: 5 productos → R1 falla
#   - test caso: hoy 50 / ayer 100 → R2 falla
#   - test caso: todos temperatura=50.0 → R3 falla
#   - test caso: datos válidos → retorna (True, "")
```

---

## PHASE 3 — External Signals

**Objetivo:** Implementar las 3 fuentes de señal con sus sub-scores.
**Regla:** Cada señal tiene un método `calculate_score()` que retorna float en su rango definido.

---

### TASK 3.1 — Facebook Ad Library

**Archivo:** `src/signals/facebook.py`

```python
# SETUP REQUERIDO (documentar en README):
# 1. Ir a https://developers.facebook.com
# 2. Crear app → tipo "Business"
# 3. Agregar producto "Marketing API"
# 4. Generar User Access Token con permiso ads_read
# 5. Convertir a Long-Lived Token (válido 60 días, renovar manualmente)

# CONTRACT de fetch_ad_signals():
#   Input:  product_name: str, country: str = settings.target_market
#   Output: SignalData (solo campos fb_*)  |  None si API falla
#   - Buscar ads de los últimos 14 días
#   - Contar anunciantes únicos por page_id (no por ad_id)
#   - Detectar si el único anunciante coincide con el nombre del productor
#   - Mapear impression range: "<1000"→LOW, "1000-10000"→MEDIUM, ">10000"→HIGH

# CONTRACT de calculate_fb_score():
#   Input:  signals: SignalData
#   Output: float  (rango 0.0 a 35.0)
#
#   LÓGICA DE SCORING:
#   base = 0
#   if signals.fb_is_producer_only:          return 0.0  # no replicable
#   if signals.fb_advertisers_count == 0:    return 5.0  # oportunidad virgen
#   if 3 <= signals.fb_advertisers_count <= 8:
#       base = 35.0  # señal óptima
#   elif signals.fb_advertisers_count < 3:
#       base = 15.0  # poco movimiento
#   elif signals.fb_advertisers_count > 8:
#       base = 20.0  # posible saturación
#
#   # Ajuste por impresiones
#   if signals.fb_impression_range == "MEDIUM": base *= 1.0  # sin cambio
#   if signals.fb_impression_range == "LOW":    base *= 0.7
#   if signals.fb_impression_range == "HIGH":   base *= 0.6  # muy competido
#
#   return min(base, 35.0)
```

---

### TASK 3.2 — Google Trends

**Archivo:** `src/signals/trends.py`

```python
# NOTA: pytrends usa la API no oficial de Google Trends
# Rate limit real: ~5 requests/minuto. Respetar con time.sleep(12) entre calls.
# Si pytrends lanza TooManyRequestsError: esperar 60s y reintentar 1 vez.
# IMPORTANTE: pytrends es INESTABLE. Se rompe con frecuencia por cambios en Google.

# CACHÉ OBLIGATORIO: guardar resultados en Supabase (tabla trends_cache o db.py helpers)
# - Antes de llamar a pytrends, revisar si hay datos cacheados de <24h: db.get_cached_trends(keyword)
# - Si hay caché válido → usarlo directamente (ahorra rate limit y evita bloqueos)
# - Si NO hay caché → llamar pytrends → guardar resultado: db.save_trends_cache(keyword, data)
# - Si pytrends FALLA y hay caché expirado → usar caché expirado como fallback
# - Si pytrends FALLA y NO hay caché → usar DEFAULT_SIGNALS

# CONTRACT de fetch_trend_signals():
#   Input:  keyword: str  (el PROBLEMA que resuelve el producto, no su nombre)
#           geo: str = settings.target_market
#   Output: SignalData (solo campos trends_*)  |  None si API falla
#
#   PROCESO:
#   0. Verificar caché en DB (< 24h) → si existe, retornar sin llamar API
#   1. Fetch timeframe='today 12-m' para detección de estacionalidad
#   2. Calcular pendiente lineal de los últimos 30 días (numpy.polyfit)
#   3. Normalizar pendiente a rango -1.0..1.0 dividiendo por max absoluto
#   4. Detectar pico histórico: valor_hoy >= percentil_90 de últimos 12 meses
#   5. Detectar estacionalidad: comparar semana actual vs misma semana año anterior
#      Si diferencia < 15% → estacional = True
#   6. Guardar resultado en caché DB

# CONTRACT de calculate_trends_score():
#   Input:  signals: SignalData
#   Output: float  (rango 0.0 a 25.0)
#
#   LÓGICA:
#   if signals.trends_at_peak and signals.trends_seasonal: return 5.0  # ruido estacional
#   if signals.trends_at_peak and not signals.trends_seasonal: return 15.0  # pico real
#   base = (signals.trends_slope_30d + 1) / 2 * 25.0  # normalizar -1..1 → 0..25
#   if signals.trends_seasonal: base *= 0.6  # penalizar estacionalidad
#   return min(max(base, 0.0), 25.0)
```

---

### TASK 3.3 — YouTube Data API

**Archivo:** `src/signals/youtube.py`

```python
# SETUP REQUERIDO:
# 1. Google Cloud Console → crear proyecto
# 2. Habilitar "YouTube Data API v3"
# 3. Crear API Key (sin restricciones de inicio, luego restringir por IP del servidor)
# Quota: 10,000 unidades/día. Una búsqueda cuesta 100 unidades.
# Con 10,000 unidades/día → máximo 100 búsquedas diarias.
#
# ⚠️ OPTIMIZACIÓN DE QUOTA CRÍTICA:
# NO hacer una búsqueda por producto. Agrupar por KEYWORD ÚNICA de categoría.
# Ejemplo: 30 productos de 8 categorías → 8 búsquedas (800 unidades) en vez de 30 (3000).
# Usar fetch_youtube_signals_batch() que recibe set de keywords únicas.

# CONTRACT de fetch_youtube_signals_batch():
#   Input:  keywords: set[str], days_back: int = 14
#   Output: dict[str, SignalData]  → {keyword: SignalData(solo campos yt_*)}
#   - UNA sola búsqueda por keyword única
#   - Reutilizar resultado para todos los productos de la misma categoría
#   - Si una keyword falla, continuar con las demás (no abortar)

# CONTRACT de fetch_youtube_signals():
#   Input:  topic: str, days_back: int = 14
#   Output: SignalData (solo campos yt_*)  |  None si API falla
#   NOTA: usar solo si se necesita buscar un keyword individual.
#   Para el pipeline, preferir fetch_youtube_signals_batch().
#
#   PROCESO:
#   1. search().list con order='date', publishedAfter=(hoy - days_back días)
#   2. Contar total de resultados (field: pageInfo.totalResults)
#   3. Filtrar por videoDuration='long' (>20 min) → posibles VSLs de afiliados
#   4. Marcar como "affiliate" si el título contiene: "review", "reseña", "vale la pena",
#      "funciona", "comprei", "resultado", "depoimento"

# CONTRACT de calculate_youtube_score():
#   Input:  signals: SignalData
#   Output: float  (rango 0.0 a 15.0)
#
#   LÓGICA:
#   if signals.yt_recent_videos_count == 0:   return 8.0   # oportunidad de contenido
#   if signals.yt_recent_videos_count > 50:   return 3.0   # posible saturación
#   base = min(signals.yt_recent_videos_count / 50 * 15, 15.0)
#   if signals.yt_affiliate_videos >= 3:      base = min(base * 1.3, 15.0)
#   return base
```

---

## PHASE 4 — Scoring y Filtros

---

### TASK 4.1 — Pesos configurables

**Archivo:** `src/scoring/weights.py`

```python
# CONTRACT: WeightConfig es el ÚNICO lugar donde se cambian los pesos
# Los pesos se cargan desde .env para poder recalibrar SIN tocar código ni redeploy
# Tras backtesting: solo editar .env y reiniciar

from dataclasses import dataclass
from src.core.config import settings

@dataclass
class WeightConfig:
    w_hotmart: float = 0.25   # 0-25 pts
    w_fb: float = 0.35        # 0-35 pts
    w_trends: float = 0.25    # 0-25 pts
    w_youtube: float = 0.15   # 0-15 pts

    def __post_init__(self):
        total = self.w_hotmart + self.w_fb + self.w_trends + self.w_youtube
        assert abs(total - 1.0) < 0.001, f"Los pesos deben sumar 1.0, suman {total}"

# Instancia activa — carga desde .env, recalibrable sin deploy
ACTIVE_WEIGHTS = WeightConfig(
    w_hotmart=settings.weight_hotmart,
    w_fb=settings.weight_fb,
    w_trends=settings.weight_trends,
    w_youtube=settings.weight_youtube,
)
```

**NOTA:** Agregar estas variables a `Settings` en `src/core/config.py`:
```python
    weight_hotmart: float = 0.25
    weight_fb: float = 0.35
    weight_trends: float = 0.25
    weight_youtube: float = 0.15
```
Y a `.env.example`:
```bash
# Pesos de scoring (recalibrar tras backtesting, deben sumar 1.0)
WEIGHT_HOTMART=0.25
WEIGHT_FB=0.35
WEIGHT_TRENDS=0.25
WEIGHT_YOUTUBE=0.15
```

---

### TASK 4.2 — Calculador de score de Hotmart

**Archivo:** `src/scoring/calculator.py` (función hotmart_sub_score)

```python
# CONTRACT de hotmart_sub_score():
#   Input:  today: ProductSnapshot, yesterday: ProductSnapshot | None
#   Output: float  (rango 0.0 a 25.0)
#
#   LÓGICA:
#   if yesterday is None: return 12.0  # producto nuevo, score neutro
#
#   delta_3d = today.temperatura - yesterday.temperatura  # aproximación 1 día
#   # Para delta real de 3 días, la DB debe tener snapshot de hace 3 días
#   # Usar get_snapshot_n_days_ago(producto_id, 3) desde db.py
#
#   if delta_3d >= 20:   return 25.0
#   if delta_3d >= 10:   return 20.0
#   if delta_3d >= 5:    return 15.0
#   if delta_3d >= 0:    return 10.0
#   if delta_3d >= -5:   return 5.0
#   return 0.0

# CONTRACT de calculate_composite_score():
#   Input:  snapshot_score: float, fb_score: float,
#           trends_score: float, yt_score: float,
#           weights: WeightConfig = ACTIVE_WEIGHTS
#   Output: float  (rango 0.0 a 100.0, redondeado a 1 decimal)
#
#   FÓRMULA (CORREGIDA — normaliza cada sub-score a 0-1 antes de ponderar):
#   total = ((snapshot_score / 25.0) * weights.w_hotmart +
#            (fb_score / 35.0)       * weights.w_fb +
#            (trends_score / 25.0)   * weights.w_trends +
#            (yt_score / 15.0)       * weights.w_youtube) * 100.0
#   return round(min(max(total, 0.0), 100.0), 1)
#
#   NOTA: esta fórmula garantiza 0-100 sin importar los pesos, siempre que sumen 1.0
#   La fórmula anterior (score * weight/max_weight) producía desbordamiento si los
#   pesos se recalibraban tras backtesting.
```

---

### TASK 4.3 — Filtro de viabilidad de canal

**Archivo:** `src/scoring/channel_filter.py`

```python
# CONTRACT de assess_channel_viability():
#   Input:  product: ProductSnapshot, signals: SignalData
#   Output: tuple[list[str], str, bool]
#          → (viable_channels, channel_risk, is_viable)
#
#   CANALES POSIBLES: "FB_ADS_COLD", "YOUTUBE_ORGANIC", "SEO_ORGANIC"
#   RISK LEVELS: "LOW" | "MEDIUM" | "HIGH"
#
#   LÓGICA (evaluar en orden, todos son independientes):
#
#   FB_ADS_COLD es viable SI:
#     - signals.fb_advertisers_count >= 2
#     - NOT signals.fb_is_producer_only
#     - signals.fb_impression_range in ["LOW", "MEDIUM"]
#
#   YOUTUBE_ORGANIC es viable SI:
#     - signals.yt_recent_videos_count < 30
#     - signals.yt_recent_videos_count > 0  (hay demanda, no saturado)
#
#   SEO_ORGANIC es viable SI:
#     - signals.trends_slope_30d > 0.1
#     - NOT signals.trends_at_peak
#     - NOT signals.trends_seasonal
#
#   channel_risk:
#     "HIGH"   si viable_channels es vacío
#     "HIGH"   si signals.fb_is_producer_only es True
#     "MEDIUM" si len(viable_channels) == 1
#     "LOW"    si len(viable_channels) >= 2
#
#   is_viable = len(viable_channels) > 0
```

---

## PHASE 5 — Filtros Duros y Alertas

---

### TASK 5.1 — Filtros duros (eliminar antes de scoring)

**Archivo:** `src/pipeline.py` (función `apply_hard_filters`)

```python
# CONTRACT de apply_hard_filters():
#   Input:  products: list[ProductSnapshot]
#   Output: list[ProductSnapshot]  (subset que pasó todos los filtros)
#
#   FILTROS (un producto se descarta si falla CUALQUIERA):
#   F1: product.comision_pct >= settings.min_commission_pct
#   F2: product.rating >= settings.min_rating
#   F3: product.num_ratings >= 10      (evitar productos sin historial)
#   F4: product.url_venta is not None and len(product.url_venta) > 0
#
#   LOGGING REQUERIDO:
#   Loguear cuántos productos eliminó cada filtro:
#   "F1 (comisión): eliminó N productos"
#   "F2 (rating): eliminó N productos"
#   etc.
```

---

### TASK 5.2 — Formateador de alertas Telegram

**Archivo:** `src/alerts/telegram.py`

```python
# CONTRACT de format_alert_message():
#   Input:  scored: ScoredProduct
#   Output: str  (mensaje en formato Markdown para Telegram)
#
#   TEMPLATE EXACTO (no modificar el formato, solo los valores):
"""
🚨 *ALERTA DE PRODUCTO* — Score: {score_total}/100

📦 *{nombre}*
💰 Comisión: {comision_pct}% | Precio: ${precio}
⭐ Rating: {rating}/5 ({num_ratings} reviews)

*Señales detectadas:*
{hotmart_emoji} Hotmart delta: {delta_emoji} {delta_valor}° en 3 días ({score_hotmart}/25)
{fb_emoji} FB Ads: {fb_advertisers} anunciantes únicos ({score_fb}/35)
{trends_emoji} Tendencia Google: pendiente {trends_slope:+.2f} ({score_trends}/25)
{yt_emoji} YouTube: {yt_videos} videos recientes ({score_youtube}/15)

*Canal recomendado:* {canales_str}
*Riesgo de competencia:* {channel_risk}

🔗 [Ver VSL]({url_venta})
"""
#   donde {hotmart_emoji} = "✅" si score_hotmart >= 15 else "⚠️" else "❌"
#   {fb_emoji}, {trends_emoji}, {yt_emoji} = misma lógica con sus umbrales proporcionales
#   {delta_emoji} = "📈" si positivo, "📉" si negativo
#   {canales_str} = ", ".join(viable_channels) o "⚠️ Ninguno identificado"

# CONTRACT de send_alert():
#   Input:  message: str
#   Output: bool  (True si enviado exitosamente)
#   - Usar requests.post a la Telegram Bot API
#   - Timeout de 10 segundos
#   - Retornar False (no lanzar excepción) si falla
#   - Loguear error si falla
```

---

## PHASE 6 — Pipeline Principal

**Archivo:** `src/pipeline.py`

```python
# Este es el único archivo que se llama desde GitHub Actions (o cron)
# Orden de ejecución EXACTO — no reordenar:
import time

async def run_daily_pipeline():
    """
    timings = {}  # Métricas de ejecución por paso

    PASO 1: Scraping
      t0 = time.monotonic()
      productos_raw = await scrape_all_categories(HOTMART_CATEGORIES)
      timings["scraping"] = time.monotonic() - t0
      Si productos_raw está vacío → loguear error crítico + return (no continuar)

    PASO 2: Validación de integridad
      productos_ayer = db.get_yesterday_snapshots()
      es_valido, motivo = validate_scrape_result(productos_raw, productos_ayer)
      Si NOT es_valido → send_alert(f"ERROR SCRAPER: {motivo}") + return

    PASO 3: Filtros duros
      productos = apply_hard_filters(productos_raw)
      Si len(productos) == 0 → loguear "0 productos pasaron filtros duros" + return

    PASO 3.5: Detectar categorías sin keyword mapeada
      unmapped = [p.categoria for p in productos if p.categoria not in KEYWORD_MAP]
      if unmapped:
          logger.warning(f"Categorías sin keyword mapeada: {set(unmapped)}")

    PASO 4: Señales externas (OPTIMIZADO — por tipo, no por producto)
      t0 = time.monotonic()

      # Extraer keywords únicas para evitar llamadas duplicadas
      unique_names = {p.nombre for p in productos}
      unique_keywords = {KEYWORD_MAP.get(p.categoria, "__default__") for p in productos}
      unique_keywords.discard(None)  # no buscar keywords de categorías sin mapear

      # Ejecutar los 3 tipos de señal EN PARALELO con asyncio.gather
      fb_results, trends_results, yt_results = await asyncio.gather(
          fetch_fb_batch(unique_names),           # dict[nombre, SignalData]
          fetch_trends_batch(unique_keywords),     # dict[keyword, SignalData]
          fetch_youtube_signals_batch(unique_keywords),  # dict[keyword, SignalData]
          return_exceptions=True  # Si una falla, las otras continúan
      )

      # Asignar resultados a cada producto; usar DEFAULT_SIGNALS si falló el tipo
      # DEFAULT fb: fb_advertisers=0, fb_is_producer_only=False, fb_impression_range="LOW"
      # DEFAULT trends: trends_slope=0.0, trends_at_peak=False, trends_seasonal=False
      # DEFAULT yt: yt_recent_videos=0, yt_affiliate_videos=0
      timings["signals"] = time.monotonic() - t0

    PASO 5: Scoring
      t0 = time.monotonic()
      Para cada producto:
        score_hotmart = hotmart_sub_score(producto, snapshot_ayer)
        score_fb = calculate_fb_score(fb_signals)
        score_trends = calculate_trends_score(trends_signals)
        score_yt = calculate_youtube_score(yt_signals)
        score_total = calculate_composite_score(...)
        viable_channels, channel_risk, is_viable = assess_channel_viability(...)
      timings["scoring"] = time.monotonic() - t0

    PASO 6: Persistencia (usa UPSERT — seguro en re-ejecuciones)
      t0 = time.monotonic()
      Para cada producto:
        prod_id = db.get_or_create_product(producto)
        snap_id = db.save_snapshot(prod_id, scored_product)  # upsert on_conflict
      timings["persistence"] = time.monotonic() - t0

    PASO 7: Alertas
      Para cada producto donde score_total >= settings.score_alert_threshold
        AND is_viable == True:
          mensaje = format_alert_message(scored_product)
          enviado = send_alert(mensaje)
          db.save_alert(prod_id, snap_id, scored_product, mensaje)

    PASO 8: Resumen de ejecución (con métricas de timing)
      timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
      send_alert(
          f"Pipeline OK: {len(productos)} productos, {len(alertas)} alertas\n"
          f"⏱ {timing_str}"
      )
    """
```

---

## PHASE 7 — Backtesting

**Archivo:** `src/backtesting/analyzer.py`

```python
# CUÁNDO EJECUTAR: manualmente cada 30 días via scripts/run_backtest.py
# PROPÓSITO: recalibrar los pesos W1-W4 en src/scoring/weights.py

# CONTRACT de run_backtest():
#   Input:  dias_atras: int = 90
#   Output: dict con las correlaciones calculadas
#
#   PROCESO:
#   1. Obtener alertas de los últimos `dias_atras` días donde resultado IS NOT NULL
#   2. Para cada alerta, extraer: score_hotmart, score_fb, score_trends, score_youtube, resultado
#   3. Calcular correlación de Pearson entre cada sub-score y (resultado == 'ganador')
#   4. Imprimir tabla:
#      Señal          | Correlación | Peso Actual | Peso Sugerido
#      score_hotmart  | 0.45        | 0.25        | 0.23
#      score_fb       | 0.72        | 0.35        | 0.37
#      ...
#   5. NO modificar weights.py automáticamente — solo sugerir, humano decide

# NOTA PARA EL OPERADOR:
# Después de ejecutar backtesting, actualizar ACTIVE_WEIGHTS en src/scoring/weights.py
# con los pesos sugeridos si la correlación lo justifica.
# Registrar el cambio como comentario con fecha: # Actualizado 2025-XX-XX tras backtest
```

---

## PHASE 8 — Despliegue con GitHub Actions (COSTO: $0)

**¿Por qué GitHub Actions en vez de VPS?**
- VPS (Hetzner CX11) cuesta ~$5 USD/mes → $60/año
- GitHub Actions: **gratis** para repos públicos, o 2,000 min/mes gratis en privados
- Pipeline de ~5 min/día = ~150 min/mes → **dentro del tier gratis**
- Sin mantenimiento de servidor, sin parches de seguridad, sin SSH

**Archivo:** `.github/workflows/pipeline.yml`

```yaml
name: Daily Hotmart Pipeline

on:
  schedule:
    # Ejecutar a las 7:00 AM UTC (2:00 AM Colombia)
    - cron: '0 7 * * *'
  workflow_dispatch:  # Permite ejecución manual desde GitHub UI

jobs:
  run-pipeline:
    runs-on: ubuntu-latest
    timeout-minutes: 15

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'  # Cachea dependencias entre ejecuciones

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          playwright install chromium

      - name: Run daily pipeline
        run: python -m src.pipeline
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
          FB_ACCESS_TOKEN: ${{ secrets.FB_ACCESS_TOKEN }}
          YT_API_KEY: ${{ secrets.YT_API_KEY }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}
          TARGET_MARKET: ${{ vars.TARGET_MARKET || 'BR' }}
          SCORE_ALERT_THRESHOLD: ${{ vars.SCORE_ALERT_THRESHOLD || '65' }}
          MIN_COMMISSION_PCT: ${{ vars.MIN_COMMISSION_PCT || '60' }}
          MIN_RATING: ${{ vars.MIN_RATING || '4.0' }}
          WEIGHT_HOTMART: ${{ vars.WEIGHT_HOTMART || '0.25' }}
          WEIGHT_FB: ${{ vars.WEIGHT_FB || '0.35' }}
          WEIGHT_TRENDS: ${{ vars.WEIGHT_TRENDS || '0.25' }}
          WEIGHT_YOUTUBE: ${{ vars.WEIGHT_YOUTUBE || '0.15' }}
```

**SETUP REQUERIDO en GitHub:**
```
1. Ir a Settings → Secrets and variables → Actions
2. Agregar SECRETS (valores sensibles, encriptados):
   - SUPABASE_URL
   - SUPABASE_SERVICE_KEY
   - FB_ACCESS_TOKEN
   - YT_API_KEY
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
3. Agregar VARIABLES (valores no sensibles, editables sin redeploy):
   - TARGET_MARKET = BR
   - SCORE_ALERT_THRESHOLD = 65
   - WEIGHT_HOTMART, WEIGHT_FB, WEIGHT_TRENDS, WEIGHT_YOUTUBE
```

**MONITOREO DE FALLOS:**
```
# Si el pipeline no corre → no hay alerta de "Pipeline OK" en Telegram a las ~2:30 AM
# Si faltan 2 días seguidos → revisar en GitHub → Actions → Daily Hotmart Pipeline → logs
# GitHub envía email automático si el workflow falla
```

**ALTERNATIVA VPS (si GitHub Actions no es suficiente):**
```bash
# Si necesitas más control o Playwright falla en GitHub Actions,
# usar Hetzner CX11 (~$5 USD/mes) con Ubuntu 22.04 LTS
# Misma configuración pero con crontab en vez de GitHub Actions
# 0 2 * * * cd /home/user/hotmart-tracker && python -m src.pipeline >> /var/log/hotmart.log 2>&1
```

---

## KEYWORD_MAP — Mapeo Categoría → Keyword de Tendencias

```python
# Definir en src/pipeline.py
# INSTRUCCIÓN: estas son las keywords del PROBLEMA, no del producto
# Si agregas nuevas categorías de Hotmart, agregar aquí también

KEYWORD_MAP = {
    "saude_emagrecimento": "perder peso rapido",
    "saude_musculacao":    "ganhar massa muscular",
    "relacionamentos":     "reconquistar ex",
    "financas":            "ganhar dinheiro online",
    "negocios":            "como abrir empresa",
    "tecnologia":          "aprender programacao",
    "idiomas":             "aprender ingles rapido",
    "espiritualidade":     "ansiedade tratamento",
    # DEFAULT para categorías no mapeadas:
    "__default__":         None  # Si None → trends_signals = DEFAULT_SIGNALS
}

# DETECCIÓN DE CATEGORÍAS NO MAPEADAS:
# El pipeline debe loguear warning si encuentra categorías no presentes en KEYWORD_MAP
# para que el operador las agregue manualmente. Ver PASO 3.5 del pipeline.
```

---

## TESTS REQUERIDOS

```bash
# Ejecutar antes de cada deploy:
pytest tests/ -v

# Tests UNITARIOS mínimos:
# tests/test_integrity.py    → 4 casos (ver TASK 2.2)
# tests/test_scoring.py      → score máximo, score mínimo, pesos suman 1,
#                               todos sub-scores 0 → total 0, todos máximos → total 100,
#                               producto nuevo sin yesterday → score_hotmart 12.0,
#                               cambiar pesos → total sigue en 0-100
# tests/test_channel_filter.py → todos los canales viables, ningún canal, solo productor
# tests/test_alerts.py       → mensaje tiene todos los campos, send_alert maneja timeout

# Tests de INTEGRACIÓN (nuevos):
# tests/test_pipeline_integration.py →
#   - Flujo completo con mocks de todas las APIs → sin errores
#   - Idempotencia: ejecutar pipeline 2 veces → no duplica datos (por upsert)
#   - Resiliencia: mock FB falla → pipeline continúa con DEFAULT_SIGNALS
#   - Resiliencia: mock Trends falla → usa caché o defaults
```

---

## SESIONES DE TRABAJO SUGERIDAS PARA CLAUDE CODE

```
Sesión 1:  PHASE 1 completa (config + DB + schema + .env con pesos)
Sesión 2:  PHASE 2 completa (scraper + integrity + stealth) — puede requerir inspección manual del DOM
Sesión 3:  PHASE 3 (signals) — facebook.py + trends.py (con caché)
Sesión 4:  PHASE 3 (signals) — youtube.py (batch) + tests de las 3 señales
Sesión 5:  PHASE 4 + 5 (scoring corregido + filtros + alertas) + tests
Sesión 6:  PHASE 6 (pipeline con paralelización) + tests de integración
Sesión 7:  PHASE 7 + 8 (backtesting + GitHub Actions)
```

---

## INVARIANTES DEL SISTEMA (nunca violar)

```
I1. Si el scraper falla → siempre notificar. Nunca fallar silenciosamente.
I2. Los datos se validan ANTES de escribir a la DB. Nunca después.
I3. Los filtros duros se aplican ANTES del scoring. El scoring es costoso (API calls).
I4. Las señales externas usan DEFAULT_SIGNALS si fallan. El pipeline no se aborta por una señal caída.
I5. El score total nunca supera 100.0 ni baja de 0.0.
I6. Un producto con channel_risk="HIGH" nunca genera alerta, sin importar el score.
I7. Los pesos en WeightConfig siempre suman exactamente 1.0 (validado en __post_init__).
I8. YouTube API: agrupar búsquedas por keyword única, NUNCA una búsqueda por producto.
I9. save_snapshot usa UPSERT — el pipeline es seguro de re-ejecutar el mismo día.
I10. pytrends siempre verifica caché antes de llamar la API.
I11. Costo total del sistema: $0/mes (Supabase free + GitHub Actions free + APIs gratuitas).
```
