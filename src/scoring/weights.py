"""
Pesos configurables para el scoring compuesto.
CONTRACT: WeightConfig es el ÚNICO lugar donde se definen los pesos.
Los pesos se cargan desde .env para poder recalibrar SIN tocar código.
"""

from dataclasses import dataclass

from src.core.config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class WeightConfig:
    w_hotmart: float = 0.25   # 0-25 pts
    w_fb: float = 0.35        # 0-35 pts
    w_trends: float = 0.25    # 0-25 pts
    w_youtube: float = 0.15   # 0-15 pts

    def __post_init__(self):
        total = self.w_hotmart + self.w_fb + self.w_trends + self.w_youtube
        assert abs(total - 1.0) < 0.001, (
            f"Los pesos deben sumar 1.0, suman {total}. "
            f"Ajustar en .env: WEIGHT_HOTMART + WEIGHT_FB + WEIGHT_TRENDS + WEIGHT_YOUTUBE = 1.0"
        )


# Instancia activa — carga desde .env, recalibrable sin deploy
ACTIVE_WEIGHTS = WeightConfig(
    w_hotmart=settings.weight_hotmart,
    w_fb=settings.weight_fb,
    w_trends=settings.weight_trends,
    w_youtube=settings.weight_youtube,
)

logger.info(
    f"Pesos cargados: H={ACTIVE_WEIGHTS.w_hotmart} FB={ACTIVE_WEIGHTS.w_fb} "
    f"T={ACTIVE_WEIGHTS.w_trends} YT={ACTIVE_WEIGHTS.w_youtube}"
)
