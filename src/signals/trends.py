"""
Google Trends via pytrends — Señal de tendencia de demanda.

NOTA: pytrends usa la API no oficial de Google Trends.
Rate limit real: ~5 requests/minuto. Respetar con time.sleep(12) entre calls.
IMPORTANTE: pytrends es INESTABLE. Se rompe con frecuencia.

CACHÉ OBLIGATORIO: se guarda en Supabase (tabla trends_cache).
"""

import asyncio
import time
from typing import Optional

import numpy as np
from pytrends.request import TrendReq
from tenacity import retry, stop_after_attempt, wait_fixed

from src.core.config import settings, SignalData
from src.core.db import db
from src.core.logger import get_logger

logger = get_logger(__name__)


def _create_pytrends() -> TrendReq:
    """Crea instancia de pytrends con configuración."""
    return TrendReq(hl="pt-BR", tz=180, timeout=(10, 30))


@retry(stop=stop_after_attempt(2), wait=wait_fixed(60))
def _fetch_from_pytrends(keyword: str, geo: str) -> dict:
    """
    Llama a pytrends y procesa los datos.
    Si falla, tenacity reintenta después de 60s.
    """
    pytrends = _create_pytrends()
    pytrends.build_payload([keyword], cat=0, timeframe="today 12-m", geo=geo)

    interest = pytrends.interest_over_time()

    if interest.empty:
        return {
            "slope_30d": 0.0,
            "at_peak": False,
            "seasonal": False,
            "values": [],
        }

    # Obtener valores de interés (excluyendo la columna isPartial)
    if keyword in interest.columns:
        values = interest[keyword].tolist()
    else:
        values = interest.iloc[:, 0].tolist()

    # Calcular pendiente de los últimos 30 días (~4 semanas de datos semanales)
    recent = values[-4:] if len(values) >= 4 else values
    if len(recent) >= 2:
        x = np.arange(len(recent))
        slope = np.polyfit(x, recent, 1)[0]
        # Normalizar a -1.0..1.0
        max_abs = max(abs(slope), 1.0)
        normalized_slope = slope / max_abs
        normalized_slope = max(-1.0, min(1.0, normalized_slope))
    else:
        normalized_slope = 0.0

    # Detectar pico histórico: valor actual >= percentil 90
    current_value = values[-1] if values else 0
    p90 = np.percentile(values, 90) if values else 100
    at_peak = current_value >= p90

    # Detectar estacionalidad: comparar con misma semana del año anterior
    seasonal = False
    if len(values) >= 52:
        current_week_value = values[-1]
        same_week_last_year = values[-52]
        if same_week_last_year > 0:
            diff_pct = abs(current_week_value - same_week_last_year) / same_week_last_year
            seasonal = diff_pct < 0.15  # < 15% diferencia = estacional

    return {
        "slope_30d": round(normalized_slope, 4),
        "at_peak": at_peak,
        "seasonal": seasonal,
        "values": values[-12:],  # Solo últimos 12 para caché (no guardar todo)
    }


def fetch_trend_signals(
    keyword: str,
    geo: str | None = None,
) -> SignalData | None:
    """
    CONTRACT:
      Input:  keyword: str (el PROBLEMA, no el nombre del producto)
              geo: str = settings.target_market
      Output: SignalData (solo campos trends_*) | None si API falla

    PROCESO:
      0. Verificar caché en DB (< 24h) → si existe, retornar sin llamar API
      1. Fetch timeframe='today 12-m'
      2. Calcular pendiente lineal de últimos 30 días
      3. Normalizar pendiente a -1.0..1.0
      4. Detectar pico histórico
      5. Detectar estacionalidad
      6. Guardar en caché
    """
    if geo is None:
        geo = settings.target_market

    # PASO 0: Verificar caché
    cached = db.get_cached_trends(keyword)
    if cached and not cached.get("_expired"):
        logger.info(f"Usando caché de trends para '{keyword}'")
        return SignalData(
            trends_slope_30d=cached.get("slope_30d", 0.0),
            trends_at_peak=cached.get("at_peak", False),
            trends_seasonal=cached.get("seasonal", False),
        )

    # PASO 1-5: Fetch y procesar
    try:
        # Rate limiting: 12 segundos entre calls
        time.sleep(12)
        data = _fetch_from_pytrends(keyword, geo)

        # PASO 6: Guardar en caché
        db.save_trends_cache(keyword, data)

        return SignalData(
            trends_slope_30d=data["slope_30d"],
            trends_at_peak=data["at_peak"],
            trends_seasonal=data["seasonal"],
        )

    except Exception as e:
        logger.error(f"pytrends falló para '{keyword}': {e}")

        # Si hay caché expirado, usarlo como fallback
        if cached:
            logger.warning(f"Usando caché expirado como fallback para '{keyword}'")
            return SignalData(
                trends_slope_30d=cached.get("slope_30d", 0.0),
                trends_at_peak=cached.get("at_peak", False),
                trends_seasonal=cached.get("seasonal", False),
            )

        # Sin caché — retornar None (pipeline usará DEFAULT_SIGNALS)
        return None


def calculate_trends_score(signals: SignalData) -> float:
    """
    CONTRACT:
      Input:  signals: SignalData
      Output: float (rango 0.0 a 25.0)

    LÓGICA per CLAUDE.md spec.
    """
    if signals.trends_at_peak and signals.trends_seasonal:
        return 5.0  # Ruido estacional

    if signals.trends_at_peak and not signals.trends_seasonal:
        return 15.0  # Pico real de interés

    # Normalizar slope (-1..1) → (0..25)
    base = (signals.trends_slope_30d + 1) / 2 * 25.0

    if signals.trends_seasonal:
        base *= 0.6  # Penalizar estacionalidad

    return round(min(max(base, 0.0), 25.0), 2)


async def fetch_trends_batch(
    keywords: set[str],
) -> dict[str, SignalData]:
    """
    Fetch señales de trends para múltiples keywords.
    Retorna dict[keyword, SignalData].
    Usa run_in_executor para no bloquear el event loop con time.sleep/pytrends.
    """
    results = {}
    loop = asyncio.get_event_loop()

    for keyword in keywords:
        if keyword is None or keyword == "__default__":
            continue

        # fetch_trend_signals es sync (usa time.sleep + pytrends), ejecutar en thread pool
        signal = await loop.run_in_executor(None, fetch_trend_signals, keyword)
        if signal:
            results[keyword] = signal
        else:
            results[keyword] = SignalData(
                trends_slope_30d=0.0,
                trends_at_peak=False,
                trends_seasonal=False,
            )

    logger.info(f"Trends signals obtenidas: {len(results)}/{len(keywords)}")
    return results
