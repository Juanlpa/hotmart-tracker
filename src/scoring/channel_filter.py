"""
Filtro de viabilidad de canal de promoción.
Evalúa qué canales de marketing son viables para cada producto.
"""

from src.core.config import ProductSnapshot, SignalData
from src.core.logger import get_logger

logger = get_logger(__name__)


def assess_channel_viability(
    product: ProductSnapshot,
    signals: SignalData,
) -> tuple[list[str], str, bool]:
    """
    CONTRACT:
      Input:  product: ProductSnapshot, signals: SignalData
      Output: tuple[list[str], str, bool]
              → (viable_channels, channel_risk, is_viable)

    CANALES POSIBLES: "FB_ADS_COLD", "YOUTUBE_ORGANIC", "SEO_ORGANIC"
    RISK LEVELS: "LOW" | "MEDIUM" | "HIGH"
    """
    viable_channels: list[str] = []

    # FB_ADS_COLD: viable si hay suficientes anunciantes y no es solo el productor
    if (
        signals.fb_advertisers_count >= 2
        and not signals.fb_is_producer_only
        and signals.fb_impression_range in ("LOW", "MEDIUM")
    ):
        viable_channels.append("FB_ADS_COLD")

    # YOUTUBE_ORGANIC: viable si no está saturado (hasta 50 videos es manejable)
    if 0 < signals.yt_recent_videos_count < 50:
        viable_channels.append("YOUTUBE_ORGANIC")

    # SEO_ORGANIC: viable si tendencia positiva y no es ruido estacional
    # NOTA: at_peak NO descalifica — pico de interés = más búsquedas = más SEO
    if (
        signals.trends_slope_30d > 0.0
        and not signals.trends_seasonal
    ):
        viable_channels.append("SEO_ORGANIC")

    # Determinar nivel de riesgo
    if not viable_channels or signals.fb_is_producer_only:
        channel_risk = "HIGH"
    elif len(viable_channels) == 1:
        channel_risk = "MEDIUM"
    else:
        channel_risk = "LOW"

    is_viable = len(viable_channels) > 0

    logger.debug(
        f"Canal assessment [{product.nombre}]: "
        f"channels={viable_channels}, risk={channel_risk}"
    )

    return viable_channels, channel_risk, is_viable
