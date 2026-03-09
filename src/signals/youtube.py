"""
YouTube Data API v3 — Señal de competencia/oportunidad en contenido.

SETUP REQUERIDO:
1. Google Cloud Console → crear proyecto
2. Habilitar "YouTube Data API v3"
3. Crear API Key

Quota: 10,000 unidades/día. Una búsqueda cuesta 100 unidades.
⚠️ OPTIMIZACIÓN: agrupar búsquedas por keyword única, no por producto.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from src.core.config import settings, SignalData
from src.core.logger import get_logger

logger = get_logger(__name__)

# Keywords de afiliados para detectar videos de reseñas
AFFILIATE_KEYWORDS = [
    "review", "reseña", "vale la pena", "funciona",
    "comprei", "resultado", "depoimento", "vale a pena",
    "análise", "opinião", "comprar", "desconto",
]


def _get_youtube_client():
    """Crea cliente de YouTube API."""
    return build("youtube", "v3", developerKey=settings.yt_api_key)


def _is_affiliate_video(title: str) -> bool:
    """Detecta si un video es probablemente una reseña de afiliado."""
    title_lower = title.lower()
    return any(kw in title_lower for kw in AFFILIATE_KEYWORDS)


def fetch_youtube_signals(
    topic: str,
    days_back: int = 14,
) -> SignalData | None:
    """
    CONTRACT:
      Input:  topic: str, days_back: int = 14
      Output: SignalData (solo campos yt_*) | None si API falla

    PROCESO:
      1. search().list con order='date', publishedAfter
      2. Contar total de resultados
      3. Filtrar por videoDuration='long' (>20 min) → posibles VSLs
      4. Marcar como "affiliate" si título contiene keywords
    """
    try:
        youtube = _get_youtube_client()
        published_after = (
            datetime.utcnow() - timedelta(days=days_back)
        ).strftime("%Y-%m-%dT00:00:00Z")

        # Búsqueda principal
        request = youtube.search().list(
            q=topic,
            type="video",
            order="date",
            publishedAfter=published_after,
            part="snippet",
            maxResults=50,
            relevanceLanguage="pt",
        )
        response = request.execute()

        total_results = response.get("pageInfo", {}).get("totalResults", 0)
        items = response.get("items", [])

        # Contar videos de afiliados
        affiliate_count = 0
        for item in items:
            title = item.get("snippet", {}).get("title", "")
            if _is_affiliate_video(title):
                affiliate_count += 1

        return SignalData(
            yt_recent_videos_count=min(total_results, 500),  # Cap para evitar outliers
            yt_affiliate_videos=affiliate_count,
        )

    except HttpError as e:
        logger.error(f"YouTube API error para '{topic}': {e}")
        return None
    except Exception as e:
        logger.error(f"YouTube fetch falló para '{topic}': {e}")
        return None


async def fetch_youtube_signals_batch(
    keywords: set[str],
    days_back: int = 14,
) -> dict[str, SignalData]:
    """
    CONTRACT:
      Input:  keywords: set[str], days_back: int = 14
      Output: dict[str, SignalData] → {keyword: SignalData(solo campos yt_*)}
      - UNA sola búsqueda por keyword única
      - Reutilizar resultado para todos los productos de la misma categoría
      - Si una keyword falla, continuar con las demás

    ⚠️ OPTIMIZACIÓN DE QUOTA:
    NO hacer una búsqueda por producto. Agrupar por KEYWORD ÚNICA.
    Ejemplo: 30 productos de 8 categorías → 8 búsquedas (800 unidades)
    """
    results = {}
    loop = asyncio.get_event_loop()

    for keyword in keywords:
        if keyword is None or keyword == "__default__":
            continue

        # fetch_youtube_signals es sync (usa googleapiclient), ejecutar en thread pool
        signal = await loop.run_in_executor(
            None, fetch_youtube_signals, keyword, days_back
        )
        if signal:
            results[keyword] = signal
        else:
            results[keyword] = SignalData(
                yt_recent_videos_count=0,
                yt_affiliate_videos=0,
            )

        # Pequeña pausa entre requests (non-blocking)
        await asyncio.sleep(0.5)

    logger.info(
        f"YouTube signals obtenidas: {len(results)}/{len(keywords)} "
        f"(~{len(results) * 100} unidades de quota usadas)"
    )
    return results


def calculate_youtube_score(signals: SignalData) -> float:
    """
    CONTRACT:
      Input:  signals: SignalData
      Output: float (rango 0.0 a 15.0)

    LÓGICA per CLAUDE.md spec.
    """
    if signals.yt_recent_videos_count == 0:
        return 8.0  # Oportunidad de contenido

    if signals.yt_recent_videos_count > 50:
        return 3.0  # Posible saturación

    base = min(signals.yt_recent_videos_count / 50 * 15, 15.0)

    if signals.yt_affiliate_videos >= 3:
        base = min(base * 1.3, 15.0)

    return round(base, 2)
