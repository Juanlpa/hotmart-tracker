"""
Tests de integración del pipeline.
Flujo completo con mocks de todas las APIs externas.
"""

import asyncio
from datetime import date
from unittest.mock import patch, MagicMock, AsyncMock
import pytest

from src.core.config import ProductSnapshot, SignalData, ScoredProduct


def _make_products(n: int = 15) -> list[ProductSnapshot]:
    """Genera N productos de test que pasan filtros duros."""
    products = []
    for i in range(n):
        products.append(
            ProductSnapshot(
                hotmart_id=f"ht_test_{i}",
                nombre=f"Producto Test {i}",
                categoria="saude-e-esportes",
                precio=197.00 + i * 10,
                moneda="BRL",
                comision_pct=70.0 + (i % 5),
                temperatura=40.0 + (i * 3.0),
                rating=4.0 + (i % 10) * 0.1,
                num_ratings=50 + i * 5,
                url_venta=f"https://hotmart.com/product/test-{i}",
                fecha=date.today(),
            )
        )
    return products


class TestApplyHardFilters:
    """Test filtros duros del pipeline."""

    def test_filters_low_commission(self):
        from src.pipeline import apply_hard_filters

        products = _make_products(15)
        # Forzar baja comisión en algunos
        products[0].comision_pct = 10.0
        products[1].comision_pct = 20.0

        result = apply_hard_filters(products)
        assert all(p.comision_pct >= 60.0 for p in result)

    def test_filters_low_rating(self):
        from src.pipeline import apply_hard_filters

        products = _make_products(15)
        products[0].rating = 2.0
        products[1].rating = 3.0

        result = apply_hard_filters(products)
        assert all(p.rating >= 4.0 for p in result)

    def test_filters_low_reviews(self):
        from src.pipeline import apply_hard_filters

        products = _make_products(15)
        products[0].num_ratings = 3
        products[1].num_ratings = 5

        result = apply_hard_filters(products)
        assert all(p.num_ratings >= 10 for p in result)

    def test_filters_empty_url(self):
        from src.pipeline import apply_hard_filters

        products = _make_products(15)
        products[0].url_venta = ""
        products[1].url_venta = ""

        result = apply_hard_filters(products)
        assert all(p.url_venta and len(p.url_venta) > 0 for p in result)

    def test_all_passing_products_remain(self):
        from src.pipeline import apply_hard_filters

        products = _make_products(15)
        result = apply_hard_filters(products)
        # All test products meet the hard filters
        assert len(result) == 15


class TestKeywordMap:
    """Verifica que el KEYWORD_MAP está configurado."""

    def test_keyword_map_has_entries(self):
        from src.pipeline import KEYWORD_MAP

        assert len(KEYWORD_MAP) > 0
        assert "__default__" in KEYWORD_MAP

    def test_known_categories_mapped(self):
        from src.pipeline import KEYWORD_MAP

        assert "saude-e-esportes" in KEYWORD_MAP
        assert "financas-e-investimentos" in KEYWORD_MAP


class TestScoringIntegration:
    """Tests de integración del sistema de scoring completo."""

    def test_full_scoring_flow(self):
        from src.scoring.calculator import hotmart_sub_score, calculate_composite_score
        from src.signals.facebook import calculate_fb_score
        from src.signals.trends import calculate_trends_score
        from src.signals.youtube import calculate_youtube_score
        from src.scoring.channel_filter import assess_channel_viability

        product = _make_products(1)[0]
        signals = SignalData(
            fb_advertisers_count=5,
            fb_is_producer_only=False,
            fb_impression_range="MEDIUM",
            trends_slope_30d=0.3,
            trends_at_peak=False,
            trends_seasonal=False,
            yt_recent_videos_count=15,
            yt_affiliate_videos=3,
        )

        s_hotmart = hotmart_sub_score(product, None)  # 12.0
        s_fb = calculate_fb_score(signals)
        s_trends = calculate_trends_score(signals)
        s_yt = calculate_youtube_score(signals)
        s_total = calculate_composite_score(s_hotmart, s_fb, s_trends, s_yt)

        assert 0 <= s_hotmart <= 25
        assert 0 <= s_fb <= 35
        assert 0 <= s_trends <= 25
        assert 0 <= s_yt <= 15
        assert 0 <= s_total <= 100

        channels, risk, viable = assess_channel_viability(product, signals)
        assert isinstance(channels, list)
        assert risk in ("LOW", "MEDIUM", "HIGH")

    def test_default_signals_produce_valid_scores(self):
        """Las señales por defecto (cuando API falla) producen scores válidos."""
        from src.scoring.calculator import calculate_composite_score
        from src.signals.facebook import calculate_fb_score
        from src.signals.trends import calculate_trends_score
        from src.signals.youtube import calculate_youtube_score

        default_signals = SignalData()  # Todos defaults
        s_fb = calculate_fb_score(default_signals)
        s_trends = calculate_trends_score(default_signals)
        s_yt = calculate_youtube_score(default_signals)
        s_total = calculate_composite_score(12.0, s_fb, s_trends, s_yt)

        assert 0 <= s_total <= 100
