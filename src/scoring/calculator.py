"""
Calculador de score compuesto 0-100.
Combina sub-scores de Hotmart, Facebook, Google Trends y YouTube.
"""

from typing import Optional

from src.core.config import ProductSnapshot
from src.core.logger import get_logger
from src.scoring.weights import WeightConfig, ACTIVE_WEIGHTS

logger = get_logger(__name__)


def hotmart_sub_score(
    today: ProductSnapshot,
    yesterday: Optional[ProductSnapshot] = None,
) -> float:
    """
    CONTRACT:
      Input:  today: ProductSnapshot, yesterday: ProductSnapshot | None
      Output: float (rango 0.0 a 25.0)

    LÓGICA per CLAUDE.md:
      Si no hay yesterday → 12.0 (producto nuevo, score neutro)
      Delta = today.temperatura - yesterday.temperatura
      >=20 → 25.0, >=10 → 20.0, >=5 → 15.0,
      >=0 → 10.0, >=-5 → 5.0, else → 0.0
    """
    if yesterday is None:
        return 12.0  # Producto nuevo, score neutro

    delta = today.temperatura - yesterday.temperatura

    if delta >= 20:
        return 25.0
    if delta >= 10:
        return 20.0
    if delta >= 5:
        return 15.0
    if delta >= 0:
        return 10.0
    if delta >= -5:
        return 5.0
    return 0.0


def calculate_composite_score(
    snapshot_score: float,
    fb_score: float,
    trends_score: float,
    yt_score: float,
    weights: WeightConfig = ACTIVE_WEIGHTS,
) -> float:
    """
    CONTRACT:
      Input:  sub-scores + weights
      Output: float (rango 0.0 a 100.0, redondeado a 1 decimal)

    FÓRMULA (CORREGIDA — normaliza cada sub-score a 0-1 antes de ponderar):
      total = ((snapshot_score / 25.0) * w_hotmart +
               (fb_score / 35.0)       * w_fb +
               (trends_score / 25.0)   * w_trends +
               (yt_score / 15.0)       * w_youtube) * 100.0

    Garantiza 0-100 sin importar los pesos, siempre que sumen 1.0
    """
    total = (
        (snapshot_score / 25.0) * weights.w_hotmart
        + (fb_score / 35.0) * weights.w_fb
        + (trends_score / 25.0) * weights.w_trends
        + (yt_score / 15.0) * weights.w_youtube
    ) * 100.0

    return round(min(max(total, 0.0), 100.0), 1)
