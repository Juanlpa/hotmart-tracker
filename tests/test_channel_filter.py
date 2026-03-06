"""
Tests unitarios para el filtro de viabilidad de canal.
"""

from datetime import date
import pytest

from src.core.config import ProductSnapshot, SignalData
from src.scoring.channel_filter import assess_channel_viability


def _make_product(**kwargs) -> ProductSnapshot:
    defaults = {
        "hotmart_id": "ht_test",
        "nombre": "Test Product",
        "categoria": "test",
        "precio": 99.90,
        "moneda": "BRL",
        "comision_pct": 70.0,
        "temperatura": 60.0,
        "rating": 4.5,
        "num_ratings": 100,
        "url_venta": "https://hotmart.com/test",
        "fecha": date.today(),
    }
    defaults.update(kwargs)
    return ProductSnapshot(**defaults)


class TestChannelViability:
    def test_all_channels_viable(self):
        """Todas las condiciones se cumplen → 3 canales, riesgo LOW"""
        product = _make_product()
        signals = SignalData(
            fb_advertisers_count=5,
            fb_is_producer_only=False,
            fb_impression_range="MEDIUM",
            trends_slope_30d=0.5,
            trends_at_peak=False,
            trends_seasonal=False,
            yt_recent_videos_count=10,
            yt_affiliate_videos=2,
        )
        channels, risk, viable = assess_channel_viability(product, signals)
        assert "FB_ADS_COLD" in channels
        assert "YOUTUBE_ORGANIC" in channels
        assert "SEO_ORGANIC" in channels
        assert risk == "LOW"
        assert viable is True

    def test_no_channels_viable(self):
        """Ninguna condición se cumple → 0 canales, riesgo HIGH"""
        product = _make_product()
        signals = SignalData(
            fb_advertisers_count=0,
            fb_is_producer_only=True,
            fb_impression_range="HIGH",
            trends_slope_30d=-0.5,
            trends_at_peak=True,
            trends_seasonal=True,
            yt_recent_videos_count=0,
            yt_affiliate_videos=0,
        )
        channels, risk, viable = assess_channel_viability(product, signals)
        assert len(channels) == 0
        assert risk == "HIGH"
        assert viable is False

    def test_producer_only_is_high_risk(self):
        """Solo el productor anuncia → siempre HIGH risk"""
        product = _make_product()
        signals = SignalData(
            fb_advertisers_count=1,
            fb_is_producer_only=True,
            fb_impression_range="LOW",
            trends_slope_30d=0.5,
            trends_at_peak=False,
            trends_seasonal=False,
            yt_recent_videos_count=10,
            yt_affiliate_videos=2,
        )
        channels, risk, viable = assess_channel_viability(product, signals)
        assert "FB_ADS_COLD" not in channels
        assert risk == "HIGH"

    def test_single_channel_medium_risk(self):
        """Solo 1 canal viable → riesgo MEDIUM"""
        product = _make_product()
        signals = SignalData(
            fb_advertisers_count=5,
            fb_is_producer_only=False,
            fb_impression_range="MEDIUM",
            trends_slope_30d=-0.5,
            trends_at_peak=True,
            trends_seasonal=True,
            yt_recent_videos_count=0,
            yt_affiliate_videos=0,
        )
        channels, risk, viable = assess_channel_viability(product, signals)
        assert len(channels) == 1
        assert risk == "MEDIUM"

    def test_youtube_saturated_not_viable(self):
        """50+ videos → YouTube no viable"""
        product = _make_product()
        signals = SignalData(
            fb_advertisers_count=0,
            fb_is_producer_only=False,
            fb_impression_range="HIGH",
            yt_recent_videos_count=50,
            yt_affiliate_videos=10,
        )
        channels, _, _ = assess_channel_viability(product, signals)
        assert "YOUTUBE_ORGANIC" not in channels
