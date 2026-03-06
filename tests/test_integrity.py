"""
Tests unitarios para validación de integridad del scraper.
Cubre los 4 casos definidos en TASK 2.2 del CLAUDE.md.
"""

from datetime import date
import pytest
from src.core.config import ProductSnapshot
from src.scrapers.integrity import validate_scrape_result


def _make_product(
    nombre: str = "Test Product",
    temperatura: float = 50.0,
    url_venta: str = "https://hotmart.com/product/123",
    **kwargs,
) -> ProductSnapshot:
    """Factory para crear ProductSnapshot de test."""
    defaults = {
        "hotmart_id": f"ht_{hash(nombre) % 10**8}",
        "nombre": nombre,
        "categoria": "test",
        "precio": 99.90,
        "moneda": "BRL",
        "comision_pct": 70.0,
        "temperatura": temperatura,
        "rating": 4.5,
        "num_ratings": 100,
        "url_venta": url_venta,
        "fecha": date.today(),
    }
    defaults.update(kwargs)
    return ProductSnapshot(**defaults)


def _make_products(n: int, base_temp: float = 30.0, url_ratio: float = 1.0) -> list[ProductSnapshot]:
    """Genera N productos con temperaturas variadas."""
    products = []
    for i in range(n):
        url = f"https://hotmart.com/product/{i}" if (i / n) < url_ratio else ""
        products.append(
            _make_product(
                nombre=f"Product_{i}",
                temperatura=base_temp + (i * 2.0),  # Variación para pasar R3
                url_venta=url,
                hotmart_id=f"ht_{i}",
            )
        )
    return products


class TestIntegrityR1:
    """R1: len(today) >= 10"""

    def test_less_than_10_products_fails(self):
        today = _make_products(5)
        valid, motivo = validate_scrape_result(today)
        assert not valid
        assert "Menos de 10" in motivo

    def test_exactly_10_products_passes_r1(self):
        today = _make_products(10)
        valid, motivo = validate_scrape_result(today)
        assert valid


class TestIntegrityR2:
    """R2: Si yesterday existe → len(today) >= len(yesterday) * 0.80"""

    def test_50_today_vs_100_yesterday_fails(self):
        today = _make_products(50)
        yesterday = _make_products(100)
        valid, motivo = validate_scrape_result(today, yesterday)
        assert not valid
        assert "productos vs" in motivo

    def test_80_today_vs_100_yesterday_passes(self):
        today = _make_products(80)
        yesterday = _make_products(100)
        valid, motivo = validate_scrape_result(today, yesterday)
        assert valid

    def test_no_yesterday_skips_r2(self):
        today = _make_products(15)
        valid, motivo = validate_scrape_result(today, None)
        assert valid


class TestIntegrityR3:
    """R3: Rango de temperaturas > 1.0"""

    def test_all_same_temperature_fails(self):
        today = [_make_product(nombre=f"P{i}", temperatura=50.0, hotmart_id=f"ht_{i}")
                 for i in range(15)]
        valid, motivo = validate_scrape_result(today)
        assert not valid
        assert "datos congelados" in motivo

    def test_varied_temperatures_passes(self):
        today = _make_products(15)
        valid, motivo = validate_scrape_result(today)
        assert valid


class TestIntegrityR4:
    """R4: Al menos 80% de productos tienen url_venta no vacía"""

    def test_low_url_ratio_fails(self):
        today = _make_products(20, url_ratio=0.5)  # Solo 50% con URL
        valid, motivo = validate_scrape_result(today)
        assert not valid
        assert "url_venta" in motivo


class TestIntegrityValid:
    """Caso de datos completamente válidos."""

    def test_valid_data_passes(self):
        today = _make_products(25)
        yesterday = _make_products(20)
        valid, motivo = validate_scrape_result(today, yesterday)
        assert valid
        assert motivo == ""
