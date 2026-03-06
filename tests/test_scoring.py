"""
Tests unitarios para el sistema de scoring.
"""

from datetime import date
import pytest

from src.core.config import ProductSnapshot, SignalData
from src.scoring.calculator import hotmart_sub_score, calculate_composite_score
from src.scoring.weights import WeightConfig


def _make_snapshot(temperatura: float = 50.0, **kwargs) -> ProductSnapshot:
    defaults = {
        "hotmart_id": "ht_test",
        "nombre": "Test",
        "categoria": "test",
        "precio": 99.90,
        "moneda": "BRL",
        "comision_pct": 70.0,
        "temperatura": temperatura,
        "rating": 4.5,
        "num_ratings": 100,
        "url_venta": "https://hotmart.com/test",
        "fecha": date.today(),
    }
    defaults.update(kwargs)
    return ProductSnapshot(**defaults)


class TestHotmartSubScore:
    def test_new_product_returns_12(self):
        """Producto nuevo sin yesterday → 12.0"""
        today = _make_snapshot(temperatura=60.0)
        assert hotmart_sub_score(today, None) == 12.0

    def test_delta_20_or_more(self):
        today = _make_snapshot(temperatura=80.0)
        yesterday = _make_snapshot(temperatura=55.0)
        assert hotmart_sub_score(today, yesterday) == 25.0

    def test_delta_10(self):
        today = _make_snapshot(temperatura=65.0)
        yesterday = _make_snapshot(temperatura=55.0)
        assert hotmart_sub_score(today, yesterday) == 20.0

    def test_delta_5(self):
        today = _make_snapshot(temperatura=60.0)
        yesterday = _make_snapshot(temperatura=55.0)
        assert hotmart_sub_score(today, yesterday) == 15.0

    def test_delta_0(self):
        today = _make_snapshot(temperatura=55.0)
        yesterday = _make_snapshot(temperatura=55.0)
        assert hotmart_sub_score(today, yesterday) == 10.0

    def test_delta_negative_small(self):
        today = _make_snapshot(temperatura=52.0)
        yesterday = _make_snapshot(temperatura=55.0)
        assert hotmart_sub_score(today, yesterday) == 5.0

    def test_delta_very_negative(self):
        today = _make_snapshot(temperatura=40.0)
        yesterday = _make_snapshot(temperatura=55.0)
        assert hotmart_sub_score(today, yesterday) == 0.0


class TestCompositeScore:
    def test_all_zeros_return_zero(self):
        """Todos los sub-scores en 0 → total 0"""
        assert calculate_composite_score(0, 0, 0, 0) == 0.0

    def test_all_max_return_100(self):
        """Todos los sub-scores al máximo → total 100"""
        score = calculate_composite_score(25.0, 35.0, 25.0, 15.0)
        assert score == 100.0

    def test_range_0_to_100(self):
        """Score siempre entre 0 y 100"""
        for h in [0, 12.5, 25]:
            for fb in [0, 17.5, 35]:
                for t in [0, 12.5, 25]:
                    for yt in [0, 7.5, 15]:
                        score = calculate_composite_score(h, fb, t, yt)
                        assert 0 <= score <= 100, f"Score fuera de rango: {score}"

    def test_weights_sum_to_one(self):
        """Los pesos activos siempre suman 1.0"""
        weights = WeightConfig()
        total = weights.w_hotmart + weights.w_fb + weights.w_trends + weights.w_youtube
        assert abs(total - 1.0) < 0.001

    def test_custom_weights(self):
        """Cambiar pesos mantiene score en 0-100"""
        custom = WeightConfig(w_hotmart=0.5, w_fb=0.2, w_trends=0.2, w_youtube=0.1)
        score = calculate_composite_score(25.0, 35.0, 25.0, 15.0, custom)
        assert score == 100.0

    def test_invalid_weights_raises(self):
        """Pesos que no suman 1.0 → AssertionError"""
        with pytest.raises(AssertionError):
            WeightConfig(w_hotmart=0.5, w_fb=0.5, w_trends=0.5, w_youtube=0.5)
