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
    # 15+ = subida fuerte, 10-14 = estable, <10 = bajada
    if scored.score_hotmart >= 15:
        delta_emoji = "📈"
    elif scored.score_hotmart >= 10:
        delta_emoji = "➡️"
    else:
        delta_emoji = "📉"

    # Canales
    canales_str = (
        ", ".join(scored.viable_channels)
        if scored.viable_channels
        else "⚠️ Ninguno identificado"
    )

    import html
    
    # Escape user input to prevent HTML injection errors
    safe_nombre = html.escape(scored.snapshot.nombre)
    safe_url = html.escape(scored.snapshot.url_venta)
    safe_canales = html.escape(canales_str)
    safe_risk = html.escape(scored.channel_risk)

    # Categoría Visual del Producto basada en el Score Total
    if scored.score_total >= 80:
        header = "💎 <b>SÚPER WINNER DETECTADO</b> 💎"
    elif scored.score_total >= 60:
        header = "🔥 <b>PRODUCTO CON ALTO POTENCIAL</b> 🔥"
    elif scored.score_total >= 40:
        header = "📊 <b>PRODUCTO EN EL RADAR</b>"
    else:
        header = "⚠️ <b>ALERTA DE PRODUCTO</b>"

    message = (
        f"{header}\n"
        f"🏆 <b>Score Total: {scored.score_total}/100</b>\n"
        f"〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
        f"📦 <b>{safe_nombre}</b>\n\n"
        f"💰 <b>Comisión:</b> {scored.snapshot.comision_pct}%\n"
        f"💵 <b>Precio:</b> ${scored.snapshot.precio:.2f}\n"
        f"⭐ <b>Rating:</b> {scored.snapshot.rating}/5 ({scored.snapshot.num_ratings} reviews)\n"
        f"〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
        f"🎯 <b>Estrategia Recomendada:</b>\n"
        f"👉 <b>Canal ideal:</b> {safe_canales}\n"
        f"⚔️ <b>Riesgo de competencia:</b> {safe_risk}\n"
        f"〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️〰️\n"
        f"📡 <b>Análisis de Señales:</b>\n"
        f"{_emoji(scored.score_hotmart, 25)} Hotmart: {delta_emoji} {scored.snapshot.temperatura}° ({scored.score_hotmart}/25)\n"
        f"{_emoji(scored.score_fb, 35)} FB Ads: {scored.signals.fb_advertisers_count} anuncios ({scored.score_fb}/35)\n"
        f"{_emoji(scored.score_trends, 25)} Google: {scored.signals.trends_slope_30d:+.2f} ({scored.score_trends}/25)\n"
        f"{_emoji(scored.score_youtube, 15)} YouTube: {scored.signals.yt_recent_videos_count} videos ({scored.score_youtube}/15)\n"
        f"\n"
        f"🔗 <a href=\"{safe_url}\"><b>Ver Página de Ventas (VSL)</b></a>"
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
                "parse_mode": "HTML",
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
