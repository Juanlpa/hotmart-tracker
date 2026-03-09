"""
Formateador y enviador de alertas Telegram.
"""

import requests
from typing import Optional

from src.core.config import settings, ScoredProduct
from src.core.logger import get_logger

logger = get_logger(__name__)

TELEGRAM_API_URL = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


def format_alert_message(scored: ScoredProduct) -> str:
    """
    CONTRACT:
      Input:  scored: ScoredProduct
      Output: str (mensaje en formato Markdown para Telegram)

    Template exacto per CLAUDE.md spec.
    """

    def _emoji(score: float, max_score: float) -> str:
        ratio = score / max_score if max_score > 0 else 0
        if ratio >= 0.6:
            return "✅"
        elif ratio >= 0.3:
            return "⚠️"
        return "❌"

    # Indicador de tendencia basado en score_hotmart
    # 12.0 = producto nuevo (neutro), >12 = tendencia positiva, <12 = negativa
    delta_emoji = "📈" if scored.score_hotmart >= 12 else "📉"

    # Canales
    canales_str = (
        ", ".join(scored.viable_channels)
        if scored.viable_channels
        else "⚠️ Ninguno identificado"
    )

    message = (
        f"🚨 *ALERTA DE PRODUCTO* — Score: {scored.score_total}/100\n"
        f"\n"
        f"📦 *{scored.snapshot.nombre}*\n"
        f"💰 Comisión: {scored.snapshot.comision_pct}% | "
        f"Precio: ${scored.snapshot.precio:.2f}\n"
        f"⭐ Rating: {scored.snapshot.rating}/5 "
        f"({scored.snapshot.num_ratings} reviews)\n"
        f"\n"
        f"*Señales detectadas:*\n"
        f"{_emoji(scored.score_hotmart, 25)} Hotmart: "
        f"{delta_emoji} temp {scored.snapshot.temperatura}° ({scored.score_hotmart}/25)\n"
        f"{_emoji(scored.score_fb, 35)} FB Ads: "
        f"{scored.signals.fb_advertisers_count} anunciantes únicos "
        f"({scored.score_fb}/35)\n"
        f"{_emoji(scored.score_trends, 25)} Tendencia Google: "
        f"pendiente {scored.signals.trends_slope_30d:+.2f} "
        f"({scored.score_trends}/25)\n"
        f"{_emoji(scored.score_youtube, 15)} YouTube: "
        f"{scored.signals.yt_recent_videos_count} videos recientes "
        f"({scored.score_youtube}/15)\n"
        f"\n"
        f"*Canal recomendado:* {canales_str}\n"
        f"*Riesgo de competencia:* {scored.channel_risk}\n"
        f"\n"
        f"🔗 [Ver VSL]({scored.snapshot.url_venta})"
    )

    return message


def send_alert(message: str) -> bool:
    """
    CONTRACT:
      Input:  message: str
      Output: bool (True si enviado exitosamente)
      - Timeout de 10 segundos
      - Retorna False (no lanza excepción) si falla
    """
    try:
        response = requests.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json={
                "chat_id": settings.telegram_chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )

        if response.status_code == 200:
            logger.info("Alerta Telegram enviada exitosamente")
            return True
        else:
            logger.error(
                f"Telegram API error: {response.status_code} — {response.text}"
            )
            return False

    except requests.Timeout:
        logger.error("Telegram API timeout (10s)")
        return False
    except requests.RequestException as e:
        logger.error(f"Telegram send error: {e}")
        return False
