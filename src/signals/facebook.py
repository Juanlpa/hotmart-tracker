"""
Facebook Ad Library API — Señal de validación de demanda publicitaria.

SETUP REQUERIDO:
1. https://developers.facebook.com → Crear app tipo "Business"
2. Agregar producto "Marketing API"
3. Generar User Access Token con permiso ads_read
4. Convertir a Long-Lived Token (válido 60 días, renovar manualmente)
"""

import asyncio
from datetime import datetime, timedelta

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.config import settings, SignalData
from src.core.logger import get_logger

logger = get_logger(__name__)

FB_AD_LIBRARY_URL = "https://graph.facebook.com/v21.0/ads_archive"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=10))
def _fetch_ads_from_fb(search_term: str, country: str) -> dict | None:
    """Llama a la FB Ad Library API."""
    params = {
        "access_token": settings.fb_access_token,
        "search_terms": search_term,
        "ad_reached_countries": country,
        "ad_active_status": "ACTIVE",
        "fields": "id,page_id,page_name,ad_creation_time,impressions",
        "limit": 100,
    }

    try:
        response = requests.get(FB_AD_LIBRARY_URL, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"FB Ad Library API error para '{search_term}': {e}")
        raise


def fetch_ad_signals(
    product_name: str,
    country: str | None = None,
) -> SignalData | None:
    """
    CONTRACT:
      Input:  product_name: str, country: str
      Output: SignalData (solo campos fb_*) | None si API falla
      - Buscar ads de los últimos 14 días
      - Contar anunciantes únicos por page_id
      - Detectar si el único anunciante es el productor
      - Mapear impression range
    """
    if country is None:
        country = settings.target_market

    try:
        data = _fetch_ads_from_fb(product_name, country)
    except Exception as e:
        logger.error(f"FB Ad Library falló para '{product_name}': {e}")
        return None

    if not data or "data" not in data:
        return SignalData(
            fb_advertisers_count=0,
            fb_is_producer_only=False,
            fb_impression_range="LOW",
        )

    ads = data["data"]
    cutoff = datetime.now() - timedelta(days=14)

    # Filtrar ads de últimos 14 días
    recent_ads = []
    for ad in ads:
        try:
            created = datetime.strptime(
                ad.get("ad_creation_time", ""), "%Y-%m-%dT%H:%M:%S%z"
            )
            if created.replace(tzinfo=None) >= cutoff:
                recent_ads.append(ad)
        except (ValueError, TypeError):
            recent_ads.append(ad)  # Incluir si no podemos parsear la fecha

    # Contar anunciantes únicos por page_id
    unique_pages = set()
    for ad in recent_ads:
        page_id = ad.get("page_id")
        if page_id:
            unique_pages.add(page_id)

    advertisers_count = len(unique_pages)

    # Detectar si es solo el productor
    is_producer_only = advertisers_count == 1

    # Mapear rango de impresiones
    total_impressions = 0
    for ad in recent_ads:
        imp = ad.get("impressions", {})
        if isinstance(imp, dict):
            lower = imp.get("lower_bound", "0")
            total_impressions += int(lower) if lower else 0
        elif isinstance(imp, str):
            try:
                total_impressions += int(imp)
            except ValueError:
                pass

    if total_impressions < 1000:
        impression_range = "LOW"
    elif total_impressions <= 10000:
        impression_range = "MEDIUM"
    else:
        impression_range = "HIGH"

    return SignalData(
        fb_advertisers_count=advertisers_count,
        fb_is_producer_only=is_producer_only,
        fb_impression_range=impression_range,
    )


def calculate_fb_score(signals: SignalData) -> float:
    """
    CONTRACT:
      Input:  signals: SignalData
      Output: float (rango 0.0 a 35.0)

    LÓGICA DE SCORING per CLAUDE.md spec.
    """
    if signals.fb_is_producer_only:
        return 0.0  # No replicable

    if signals.fb_advertisers_count == 0:
        return 5.0  # Oportunidad virgen

    if 3 <= signals.fb_advertisers_count <= 8:
        base = 35.0  # Señal óptima
    elif signals.fb_advertisers_count < 3:
        base = 15.0  # Poco movimiento
    else:  # > 8
        base = 20.0  # Posible saturación

    # Ajuste por impresiones
    if signals.fb_impression_range == "LOW":
        base *= 0.7
    elif signals.fb_impression_range == "HIGH":
        base *= 0.6
    # MEDIUM: sin cambio (base *= 1.0)

    return min(base, 35.0)


async def fetch_fb_batch(
    product_names: set[str],
) -> dict[str, SignalData]:
    """
    Fetch señales FB para múltiples productos.
    Retorna dict[nombre, SignalData].
    Usa run_in_executor para no bloquear el event loop con requests.get().
    """
    results = {}
    loop = asyncio.get_event_loop()

    for name in product_names:
        # fetch_ad_signals es sync (usa requests.get), ejecutar en thread pool
        signal = await loop.run_in_executor(None, fetch_ad_signals, name)
        if signal:
            results[name] = signal
        else:
            # Usar defaults neutros cuando la API falla (invariante I4)
            from src.core.config import DEFAULT_FB_SIGNALS
            results[name] = SignalData(**DEFAULT_FB_SIGNALS)
        # Rate limiting: esperar entre requests (non-blocking)
        await asyncio.sleep(1)

    logger.info(f"FB signals obtenidas: {len(results)}/{len(product_names)}")
    return results
