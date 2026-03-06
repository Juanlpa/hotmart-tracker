"""
Tests unitarios para el sistema de alertas Telegram.
"""

from datetime import date
from unittest.mock import patch, MagicMock
import pytest

from src.core.config import ProductSnapshot, SignalData, ScoredProduct
from src.alerts.telegram import format_alert_message, send_alert


def _make_scored_product() -> ScoredProduct:
    """Factory para ScoredProduct de test."""
    snapshot = ProductSnapshot(
        hotmart_id="ht_test_001",
        nombre="Método Emagrecimento Definitivo",
        categoria="saude",
        precio=197.00,
        moneda="BRL",
        comision_pct=70.0,
        temperatura=75.0,
        rating=4.7,
        num_ratings=342,
        url_venta="https://hotmart.com/product/test-001",
        fecha=date.today(),
    )
    signals = SignalData(
        fb_advertisers_count=5,
        fb_is_producer_only=False,
        fb_impression_range="MEDIUM",
        trends_slope_30d=0.45,
        trends_at_peak=False,
        trends_seasonal=False,
        yt_recent_videos_count=12,
        yt_affiliate_videos=4,
    )
    return ScoredProduct(
        snapshot=snapshot,
        signals=signals,
        score_hotmart=20.0,
        score_fb=28.0,
        score_trends=18.0,
        score_youtube=12.0,
        score_total=78.5,
        viable_channels=["FB_ADS_COLD", "YOUTUBE_ORGANIC", "SEO_ORGANIC"],
        channel_risk="LOW",
        alert_triggered=True,
    )


class TestFormatAlertMessage:
    def test_message_has_all_required_fields(self):
        scored = _make_scored_product()
        message = format_alert_message(scored)

        assert "ALERTA DE PRODUCTO" in message
        assert "78.5/100" in message
        assert "Método Emagrecimento Definitivo" in message
        assert "70.0%" in message
        assert "197.00" in message
        assert "4.7/5" in message
        assert "342 reviews" in message
        assert "5 anunciantes" in message
        assert "+0.45" in message
        assert "12 videos" in message
        assert "FB_ADS_COLD" in message
        assert "LOW" in message
        assert "Ver VSL" in message

    def test_no_channels_message(self):
        scored = _make_scored_product()
        scored.viable_channels = []
        message = format_alert_message(scored)
        assert "Ninguno identificado" in message


class TestSendAlert:
    @patch("src.alerts.telegram.requests.post")
    def test_successful_send(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        result = send_alert("Test message")
        assert result is True
        mock_post.assert_called_once()

    @patch("src.alerts.telegram.requests.post")
    def test_failed_send_returns_false(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server Error"
        mock_post.return_value = mock_response

        result = send_alert("Test message")
        assert result is False

    @patch("src.alerts.telegram.requests.post")
    def test_timeout_returns_false(self, mock_post):
        import requests
        mock_post.side_effect = requests.Timeout()

        result = send_alert("Test message")
        assert result is False

    @patch("src.alerts.telegram.requests.post")
    def test_network_error_returns_false(self, mock_post):
        import requests
        mock_post.side_effect = requests.ConnectionError()

        result = send_alert("Test message")
        assert result is False
