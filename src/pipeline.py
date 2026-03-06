"""
Pipeline principal — orquestador del sistema.
Este es el único archivo que se llama desde GitHub Actions (o cron).

Uso: python -m src.pipeline
"""

import asyncio
import time
from datetime import date

from src.core.config import (
    settings,
    ProductSnapshot,
    SignalData,
    ScoredProduct,
    DEFAULT_FB_SIGNALS,
    DEFAULT_TRENDS_SIGNALS,
    DEFAULT_YT_SIGNALS,
)
from src.core.db import db
from src.core.logger import get_logger
from src.scrapers.hotmart import scrape_all_categories, HOTMART_CATEGORIES
from src.scrapers.integrity import validate_scrape_result
from src.signals.facebook import fetch_fb_batch, calculate_fb_score
from src.signals.trends import fetch_trends_batch, calculate_trends_score
from src.signals.youtube import fetch_youtube_signals_batch, calculate_youtube_score
from src.scoring.calculator import hotmart_sub_score, calculate_composite_score
from src.scoring.channel_filter import assess_channel_viability
from src.alerts.telegram import format_alert_message, send_alert

logger = get_logger(__name__)

# ─────────────────────────────────────────────
# Mapeo Categoría → Keyword de Tendencias
# ─────────────────────────────────────────────
KEYWORD_MAP = {
    "saude-e-esportes": "perder peso rapido",
    "saude_emagrecimento": "perder peso rapido",
    "saude_musculacao": "ganhar massa muscular",
    "relacionamentos": "reconquistar ex",
    "financas-e-investimentos": "ganhar dinheiro online",
    "financas": "ganhar dinheiro online",
    "negocios-e-carreira": "como abrir empresa",
    "negocios": "como abrir empresa",
    "tecnologia": "aprender programacao",
    "educacao": "aprender online",
    "idiomas": "aprender ingles rapido",
    "estilo-de-vida": "ansiedade tratamento",
    "espiritualidade": "ansiedade tratamento",
    "__default__": None,
}


def apply_hard_filters(products: list[ProductSnapshot]) -> list[ProductSnapshot]:
    """
    CONTRACT:
      Input:  products: list[ProductSnapshot]
      Output: list[ProductSnapshot] (subset que pasó todos los filtros)

    FILTROS (un producto se descarta si falla CUALQUIERA):
      F1: comision_pct >= settings.min_commission_pct (SKIP si comision=0 → no disponible públicamente)
      F2: rating >= settings.min_rating
      F3: num_ratings >= 10
      F4: url_venta no vacía
    """
    original_count = len(products)
    filtered = products.copy()

    # F1: Comisión mínima
    # NOTA: comision_pct=0.0 significa "dato no disponible" (no visible en marketplace público)
    # En ese caso se SALTA el filtro para no eliminar todos los productos
    products_with_commission = [p for p in filtered if p.comision_pct > 0]
    if products_with_commission:
        before = len(filtered)
        filtered = [
            p for p in filtered
            if p.comision_pct == 0 or p.comision_pct >= settings.min_commission_pct
        ]
        logger.info(f"F1 (comisión >= {settings.min_commission_pct}%): eliminó {before - len(filtered)} productos")
    else:
        logger.info(
            f"F1 (comisión): SALTADO — datos de comisión no disponibles "
            f"(requiere sesión de afiliado Hotmart)"
        )

    # F2: Rating mínimo
    before = len(filtered)
    filtered = [p for p in filtered if p.rating >= settings.min_rating]
    logger.info(f"F2 (rating >= {settings.min_rating}): eliminó {before - len(filtered)} productos")

    # F3: Mínimo de evaluaciones
    before = len(filtered)
    filtered = [p for p in filtered if p.num_ratings >= 10]
    logger.info(f"F3 (num_ratings >= 10): eliminó {before - len(filtered)} productos")

    # F4: URL de venta presente
    before = len(filtered)
    filtered = [p for p in filtered if p.url_venta and len(p.url_venta) > 0]
    logger.info(f"F4 (url_venta): eliminó {before - len(filtered)} productos")

    logger.info(
        f"Filtros duros: {len(filtered)}/{original_count} productos pasaron"
    )
    return filtered


async def run_daily_pipeline():
    """
    Orquestador principal del pipeline diario.
    Orden de ejecución EXACTO per CLAUDE.md — no reordenar.
    """
    timings = {}
    alertas_enviadas = []

    logger.info("=" * 60)
    logger.info("INICIO DEL PIPELINE DIARIO")
    logger.info("=" * 60)

    # ──────────────────────────────────────────
    # PASO 1: Scraping
    # ──────────────────────────────────────────
    t0 = time.monotonic()
    logger.info("PASO 1: Scraping de productos Hotmart...")
    productos_raw = await scrape_all_categories(HOTMART_CATEGORIES)
    timings["scraping"] = time.monotonic() - t0

    if not productos_raw:
        logger.critical("PASO 1 FALLIDO: 0 productos scrapeados. Abortando pipeline.")
        send_alert("🚨 ERROR PIPELINE: Scraper retornó 0 productos")
        return

    logger.info(f"PASO 1 OK: {len(productos_raw)} productos scrapeados en {timings['scraping']:.1f}s")

    # ──────────────────────────────────────────
    # PASO 2: Validación de integridad
    # ──────────────────────────────────────────
    logger.info("PASO 2: Validación de integridad...")
    productos_ayer = db.get_yesterday_snapshots()
    # Convertir dict a ProductSnapshot para la validación
    yesterday_snapshots = None
    if productos_ayer:
        # Solo necesitamos el count para la validación
        yesterday_snapshots = [
            ProductSnapshot(
                hotmart_id="temp",
                nombre="temp",
                categoria="temp",
                precio=0,
                moneda="BRL",
                comision_pct=0,
                temperatura=d.get("temperatura", 0),
                rating=0,
                num_ratings=0,
                url_venta=d.get("url_venta", ""),
            )
            for d in productos_ayer
        ]

    es_valido, motivo = validate_scrape_result(productos_raw, yesterday_snapshots)
    if not es_valido:
        logger.critical(f"PASO 2 FALLIDO: {motivo}")
        send_alert(f"🚨 ERROR SCRAPER: {motivo}")
        return

    logger.info("PASO 2 OK: Datos válidos")

    # ──────────────────────────────────────────
    # PASO 3: Filtros duros
    # ──────────────────────────────────────────
    logger.info("PASO 3: Aplicando filtros duros...")
    productos = apply_hard_filters(productos_raw)

    if not productos:
        logger.warning("0 productos pasaron filtros duros. Nada que procesar.")
        return

    # ──────────────────────────────────────────
    # PASO 3.5: Detectar categorías sin keyword mapeada
    # ──────────────────────────────────────────
    unmapped = [p.categoria for p in productos if p.categoria not in KEYWORD_MAP]
    if unmapped:
        logger.warning(f"Categorías sin keyword mapeada: {set(unmapped)}")

    # ──────────────────────────────────────────
    # PASO 4: Señales externas (PARALELO)
    # ──────────────────────────────────────────
    t0 = time.monotonic()
    logger.info("PASO 4: Obteniendo señales externas en paralelo...")

    unique_names = {p.nombre for p in productos}
    unique_keywords = {
        KEYWORD_MAP.get(p.categoria, KEYWORD_MAP.get("__default__"))
        for p in productos
    }
    unique_keywords.discard(None)

    fb_results, trends_results, yt_results = await asyncio.gather(
        fetch_fb_batch(unique_names),
        fetch_trends_batch(unique_keywords),
        fetch_youtube_signals_batch(unique_keywords),
        return_exceptions=True,
    )

    # Manejar excepciones en resultados paralelos
    if isinstance(fb_results, Exception):
        logger.error(f"FB batch falló: {fb_results}")
        fb_results = {}
    if isinstance(trends_results, Exception):
        logger.error(f"Trends batch falló: {trends_results}")
        trends_results = {}
    if isinstance(yt_results, Exception):
        logger.error(f"YouTube batch falló: {yt_results}")
        yt_results = {}

    timings["signals"] = time.monotonic() - t0
    logger.info(f"PASO 4 OK: Señales en {timings['signals']:.1f}s")

    # ──────────────────────────────────────────
    # PASO 5: Scoring
    # ──────────────────────────────────────────
    t0 = time.monotonic()
    logger.info("PASO 5: Calculando scores...")
    scored_products: list[ScoredProduct] = []

    for producto in productos:
        # Obtener señales (usar defaults si faltan)
        fb_signal = fb_results.get(producto.nombre, SignalData(**DEFAULT_FB_SIGNALS))
        keyword = KEYWORD_MAP.get(producto.categoria, None)
        trends_signal = (
            trends_results.get(keyword, SignalData(**DEFAULT_TRENDS_SIGNALS))
            if keyword
            else SignalData(**DEFAULT_TRENDS_SIGNALS)
        )
        yt_signal = (
            yt_results.get(keyword, SignalData(**DEFAULT_YT_SIGNALS))
            if keyword
            else SignalData(**DEFAULT_YT_SIGNALS)
        )

        # Combinar señales en un solo SignalData
        combined_signals = SignalData(
            fb_advertisers_count=fb_signal.fb_advertisers_count,
            fb_is_producer_only=fb_signal.fb_is_producer_only,
            fb_impression_range=fb_signal.fb_impression_range,
            trends_slope_30d=trends_signal.trends_slope_30d,
            trends_at_peak=trends_signal.trends_at_peak,
            trends_seasonal=trends_signal.trends_seasonal,
            yt_recent_videos_count=yt_signal.yt_recent_videos_count,
            yt_affiliate_videos=yt_signal.yt_affiliate_videos,
        )

        # Obtener snapshot de ayer para delta
        prod_id_temp = None
        try:
            prod_id_temp = db.get_or_create_product(
                hotmart_id=producto.hotmart_id,
                nombre=producto.nombre,
                categoria=producto.categoria,
                precio=producto.precio,
                comision_pct=producto.comision_pct,
                url_venta=producto.url_venta,
            )
            yesterday_snap = db.get_yesterday_snapshot(prod_id_temp)
        except Exception:
            yesterday_snap = None

        yesterday_product = None
        if yesterday_snap:
            yesterday_product = ProductSnapshot(
                hotmart_id=producto.hotmart_id,
                nombre=producto.nombre,
                categoria=producto.categoria,
                precio=yesterday_snap.get("precio_snapshot", 0),
                moneda=producto.moneda,
                comision_pct=yesterday_snap.get("comision_snapshot", 0),
                temperatura=yesterday_snap.get("temperatura", 0),
                rating=yesterday_snap.get("rating", 0),
                num_ratings=yesterday_snap.get("num_ratings", 0),
                url_venta=producto.url_venta,
            )

        # Sub-scores
        s_hotmart = hotmart_sub_score(producto, yesterday_product)
        s_fb = calculate_fb_score(combined_signals)
        s_trends = calculate_trends_score(combined_signals)
        s_yt = calculate_youtube_score(combined_signals)
        s_total = calculate_composite_score(s_hotmart, s_fb, s_trends, s_yt)

        # Viabilidad de canal
        viable_channels, channel_risk, is_viable = assess_channel_viability(
            producto, combined_signals
        )

        # Determinar si alerta
        alert_triggered = (
            s_total >= settings.score_alert_threshold
            and is_viable
            and channel_risk != "HIGH"  # I6: HIGH risk nunca genera alerta
        )

        scored = ScoredProduct(
            snapshot=producto,
            signals=combined_signals,
            score_hotmart=s_hotmart,
            score_fb=s_fb,
            score_trends=s_trends,
            score_youtube=s_yt,
            score_total=s_total,
            viable_channels=viable_channels,
            channel_risk=channel_risk,
            alert_triggered=alert_triggered,
        )
        scored_products.append(scored)

    timings["scoring"] = time.monotonic() - t0
    logger.info(f"PASO 5 OK: {len(scored_products)} productos scored en {timings['scoring']:.1f}s")

    # ──────────────────────────────────────────
    # PASO 6: Persistencia (UPSERT — seguro en re-ejecuciones)
    # ──────────────────────────────────────────
    t0 = time.monotonic()
    logger.info("PASO 6: Persistiendo en Supabase...")

    for scored in scored_products:
        try:
            prod_id = db.get_or_create_product(
                hotmart_id=scored.snapshot.hotmart_id,
                nombre=scored.snapshot.nombre,
                categoria=scored.snapshot.categoria,
                precio=scored.snapshot.precio,
                comision_pct=scored.snapshot.comision_pct,
                url_venta=scored.snapshot.url_venta,
            )

            snapshot_data = {
                "fecha": date.today().isoformat(),
                "temperatura": scored.snapshot.temperatura,
                "rating": scored.snapshot.rating,
                "num_ratings": scored.snapshot.num_ratings,
                "precio_snapshot": scored.snapshot.precio,
                "comision_snapshot": scored.snapshot.comision_pct,
                "fb_advertisers": scored.signals.fb_advertisers_count,
                "fb_producer_only": scored.signals.fb_is_producer_only,
                "fb_impression_range": scored.signals.fb_impression_range,
                "trends_slope": scored.signals.trends_slope_30d,
                "trends_at_peak": scored.signals.trends_at_peak,
                "trends_seasonal": scored.signals.trends_seasonal,
                "yt_recent_videos": scored.signals.yt_recent_videos_count,
                "yt_affiliate_videos": scored.signals.yt_affiliate_videos,
                "score_hotmart": scored.score_hotmart,
                "score_fb": scored.score_fb,
                "score_trends": scored.score_trends,
                "score_youtube": scored.score_youtube,
                "score_total": scored.score_total,
                "viable_channels": scored.viable_channels,
                "channel_risk": scored.channel_risk,
                "scraper_ok": True,
            }

            snap_id = db.save_snapshot(prod_id, snapshot_data)

            # PASO 7: Alertas
            if scored.alert_triggered:
                mensaje = format_alert_message(scored)
                enviado = send_alert(mensaje)
                if enviado:
                    db.save_alert(
                        prod_id, snap_id,
                        scored.score_total,
                        scored.viable_channels,
                        mensaje,
                    )
                    alertas_enviadas.append(scored.snapshot.nombre)

        except Exception as e:
            logger.error(f"Error procesando {scored.snapshot.nombre}: {e}")
            continue

    timings["persistence"] = time.monotonic() - t0
    logger.info(f"PASO 6-7 OK: Dato persistido, {len(alertas_enviadas)} alertas enviadas")

    # ──────────────────────────────────────────
    # PASO 8: Resumen de ejecución
    # ──────────────────────────────────────────
    timing_str = " | ".join(f"{k}: {v:.1f}s" for k, v in timings.items())
    resumen = (
        f"✅ Pipeline OK: {len(scored_products)} productos, "
        f"{len(alertas_enviadas)} alertas\n"
        f"⏱ {timing_str}"
    )
    logger.info(resumen)
    send_alert(resumen)

    logger.info("=" * 60)
    logger.info("PIPELINE DIARIO COMPLETADO")
    logger.info("=" * 60)


# Entry point para `python -m src.pipeline`
if __name__ == "__main__":
    asyncio.run(run_daily_pipeline())
