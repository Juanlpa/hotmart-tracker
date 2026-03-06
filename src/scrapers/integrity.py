"""
Validación de integridad de datos del scraper.
Verifica que los datos scrapeados son coherentes antes de escribir a la DB.
"""

from src.core.config import ProductSnapshot
from src.core.logger import get_logger

logger = get_logger(__name__)


def validate_scrape_result(
    today: list[ProductSnapshot],
    yesterday: list[ProductSnapshot] | None = None,
) -> tuple[bool, str]:
    """
    CONTRACT:
      Input:  today: list[ProductSnapshot], yesterday: list[ProductSnapshot] | None
      Output: tuple[bool, str] → (es_valido, motivo_si_falla)

    REGLAS DE VALIDACIÓN (todas deben pasar):
      R1: len(today) >= 10
      R2: Si yesterday existe → len(today) >= len(yesterday) * 0.80
      R3: Si len(today) > 1 → rango de temperaturas > 1.0
      R4: Al menos 80% de productos tienen url_venta no vacía
    """
    # R1: Mínimo 10 productos
    if len(today) < 10:
        motivo = f"Menos de 10 productos ({len(today)}) — scraper probablemente bloqueado"
        logger.error(f"Validación R1 FALLIDA: {motivo}")
        return False, motivo

    # R2: No perder más del 20% respecto a ayer
    if yesterday is not None and len(yesterday) > 0:
        threshold = len(yesterday) * 0.80
        if len(today) < threshold:
            motivo = (
                f"Solo {len(today)} productos vs {len(yesterday)} de ayer "
                f"(umbral 80% = {int(threshold)})"
            )
            logger.error(f"Validación R2 FALLIDA: {motivo}")
            return False, motivo

    # R3: Rango de temperaturas > 1.0 (detecta datos congelados)
    if len(today) > 1:
        temperaturas = [p.temperatura for p in today]
        rango = max(temperaturas) - min(temperaturas)
        if rango <= 1.0:
            motivo = (
                f"Todas las temperaturas son iguales o casi iguales "
                f"(rango={rango:.2f}) — datos congelados"
            )
            logger.error(f"Validación R3 FALLIDA: {motivo}")
            return False, motivo

    # R4: Al menos 80% con url_venta
    with_url = sum(1 for p in today if p.url_venta and len(p.url_venta) > 0)
    pct = (with_url / len(today)) * 100
    if pct < 80:
        motivo = (
            f"Solo {pct:.0f}% con url_venta ({with_url}/{len(today)}) "
            f"— posible cambio de DOM"
        )
        logger.error(f"Validación R4 FALLIDA: {motivo}")
        return False, motivo

    logger.info(
        f"Validación OK: {len(today)} productos, "
        f"rango temp={max(p.temperatura for p in today) - min(p.temperatura for p in today):.1f}, "
        f"URLs={pct:.0f}%"
    )
    return True, ""
