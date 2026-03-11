"""
Configuración central con validación estricta usando pydantic-settings.
CONTRACT: esta es la ÚNICA forma de acceder a variables de entorno.
          Todos los módulos importan `settings` desde aquí.
          NO usar os.getenv() directamente en ningún otro módulo.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings


# ─────────────────────────────────────────────
# Configuración del sistema
# ─────────────────────────────────────────────

class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_service_key: str

    # APIs externas
    fb_access_token: str
    yt_api_key: str

    # Telegram
    telegram_bot_token: str
    telegram_chat_id: str

    # Hotmart scraper
    hotmart_email: str | None = None
    hotmart_password: str | None = None
    hotmart_scraper_proxy: str | None = None

    # Pipeline
    target_market: str = "BR"
    score_alert_threshold: int = 50
    min_commission_pct: float = 40.0
    min_rating: float = 3.5
    scraper_delay_min: float = 3.0
    scraper_delay_max: float = 7.0

    # Pesos de scoring (recalibrables via .env sin tocar código)
    weight_hotmart: float = 0.25
    weight_fb: float = 0.35
    weight_trends: float = 0.25
    weight_youtube: float = 0.15

    @field_validator("score_alert_threshold")
    @classmethod
    def threshold_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("SCORE_ALERT_THRESHOLD debe estar entre 0 y 100")
        return v

    @field_validator("scraper_delay_max")
    @classmethod
    def delay_order(cls, v: float, info) -> float:
        min_val = info.data.get("scraper_delay_min", 3.0)
        if v < min_val:
            raise ValueError(
                f"SCRAPER_DELAY_MAX ({v}) debe ser >= SCRAPER_DELAY_MIN ({min_val})"
            )
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Singleton — importar `settings` en todos los módulos
settings = Settings()


# ─────────────────────────────────────────────
# Tipos compartidos — NO redefinir en otros módulos
# ─────────────────────────────────────────────

@dataclass
class ProductSnapshot:
    hotmart_id: str
    nombre: str
    categoria: str
    precio: float
    moneda: str  # ISO 4217
    comision_pct: float  # 0-100
    temperatura: float  # 0-100, métrica de Hotmart
    rating: float  # 0-5
    num_ratings: int
    url_venta: str
    fecha: date = field(default_factory=date.today)


@dataclass
class SignalData:
    fb_advertisers_count: int = 0
    fb_is_producer_only: bool = False
    fb_impression_range: str = "LOW"  # "LOW" | "MEDIUM" | "HIGH"
    trends_slope_30d: float = 0.0  # -1 a 1
    trends_at_peak: bool = False
    trends_seasonal: bool = False
    yt_recent_videos_count: int = 0
    yt_affiliate_videos: int = 0


@dataclass
class ScoredProduct:
    snapshot: ProductSnapshot
    signals: SignalData
    score_hotmart: float  # 0-25
    score_fb: float  # 0-35
    score_trends: float  # 0-25
    score_youtube: float  # 0-15
    score_total: float  # 0-100
    viable_channels: list[str] = field(default_factory=list)
    channel_risk: str = "HIGH"  # "LOW" | "MEDIUM" | "HIGH"
    alert_triggered: bool = False


# Señales por defecto cuando una API falla (invariante I4)
DEFAULT_FB_SIGNALS = {
    "fb_advertisers_count": 2,
    "fb_is_producer_only": False,
    "fb_impression_range": "MEDIUM",
}

DEFAULT_TRENDS_SIGNALS = {
    "trends_slope_30d": 0.1,
    "trends_at_peak": False,
    "trends_seasonal": False,
}

DEFAULT_YT_SIGNALS = {
    "yt_recent_videos_count": 0,
    "yt_affiliate_videos": 0,
}
