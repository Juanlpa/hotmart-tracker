"""
Cliente Supabase Singleton.
CONTRACT: esta es la ÚNICA forma de acceder a Supabase en todo el proyecto.
          Todos los módulos hacen: from src.core.db import db
          Nadie instancia supabase.create_client() por su cuenta.
"""

import json
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from supabase import create_client, Client

from src.core.config import settings
from src.core.logger import get_logger

logger = get_logger(__name__)


def _init_supabase() -> Client:
    """Inicializa y retorna el cliente de Supabase."""
    client = create_client(settings.supabase_url, settings.supabase_service_key)
    logger.info("Supabase client initialized")
    return client


# Singleton — cliente único para todo el proyecto
_client: Client = _init_supabase()


class SupabaseDB:
    """Wrapper sobre el cliente de Supabase con las operaciones del pipeline."""

    def __init__(self, client: Client):
        self._client = client

    def get_or_create_product(
        self,
        hotmart_id: str,
        nombre: str,
        categoria: str | None = None,
        precio: float | None = None,
        comision_pct: float | None = None,
        url_venta: str | None = None,
    ) -> str:
        """
        Busca un producto por hotmart_id; si no existe, lo crea.
        Retorna el UUID del producto.
        """
        # Intentar buscar primero
        result = (
            self._client.table("productos")
            .select("id")
            .eq("hotmart_id", hotmart_id)
            .execute()
        )

        if result.data:
            return result.data[0]["id"]

        # Crear nuevo
        insert_data = {
            "hotmart_id": hotmart_id,
            "nombre": nombre,
            "categoria": categoria,
            "precio": precio,
            "comision_pct": comision_pct,
            "url_venta": url_venta,
        }
        # Remover None values
        insert_data = {k: v for k, v in insert_data.items() if v is not None}

        result = self._client.table("productos").insert(insert_data).execute()
        product_id = result.data[0]["id"]
        logger.info(f"Producto creado: {nombre} ({hotmart_id}) → {product_id}")
        return product_id

    def save_snapshot(self, producto_id: str, snapshot_data: dict) -> str:
        """
        Guarda un snapshot diario.
        IMPORTANTE: usa UPSERT con on_conflict="producto_id,fecha"
        para evitar errores si el pipeline se re-ejecuta el mismo día.
        Retorna el UUID del snapshot.
        """
        snapshot_data["producto_id"] = producto_id

        result = (
            self._client.table("snapshots_diarios")
            .upsert(snapshot_data, on_conflict="producto_id,fecha")
            .execute()
        )
        return result.data[0]["id"]

    def get_yesterday_snapshot(self, producto_id: str) -> Optional[dict]:
        """Obtiene el snapshot de ayer para un producto."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        result = (
            self._client.table("snapshots_diarios")
            .select("*")
            .eq("producto_id", producto_id)
            .eq("fecha", yesterday)
            .execute()
        )

        return result.data[0] if result.data else None

    def get_yesterday_snapshots(self) -> list[dict]:
        """Obtiene todos los snapshots de ayer."""
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        result = (
            self._client.table("snapshots_diarios")
            .select("*")
            .eq("fecha", yesterday)
            .execute()
        )

        return result.data or []

    def get_snapshot_n_days_ago(
        self, producto_id: str, n: int
    ) -> Optional[dict]:
        """Obtiene el snapshot de hace N días para un producto."""
        target_date = (date.today() - timedelta(days=n)).isoformat()

        result = (
            self._client.table("snapshots_diarios")
            .select("*")
            .eq("producto_id", producto_id)
            .eq("fecha", target_date)
            .execute()
        )

        return result.data[0] if result.data else None

    def save_alert(
        self,
        producto_id: str,
        snapshot_id: str,
        score_total: float,
        canales: list[str],
        mensaje_enviado: str,
    ) -> str:
        """Guarda una alerta enviada. Retorna el UUID de la alerta."""
        alert_data = {
            "producto_id": producto_id,
            "snapshot_id": snapshot_id,
            "score_total": score_total,
            "canales": canales,
            "mensaje_enviado": mensaje_enviado,
        }

        result = self._client.table("alertas").insert(alert_data).execute()
        return result.data[0]["id"]

    def get_products_for_backtest(self, dias_atras: int = 90) -> list[dict]:
        """
        Obtiene alertas con resultado no nulo de los últimos N días
        para análisis de backtesting.
        """
        since = (date.today() - timedelta(days=dias_atras)).isoformat()

        result = (
            self._client.table("alertas")
            .select("*, snapshots_diarios(*)")
            .gte("fecha_alerta", since)
            .not_.is_("resultado", "null")
            .execute()
        )

        return result.data or []

    def get_cached_trends(
        self, keyword: str, max_age_hours: int = 24
    ) -> Optional[dict]:
        """
        Busca datos cacheados de Google Trends.
        Retorna los datos si el caché tiene menos de max_age_hours horas.
        Si hay caché expirado, retorna con flag expired=True.
        """
        result = (
            self._client.table("trends_cache")
            .select("*")
            .eq("keyword", keyword)
            .eq("geo", settings.target_market)
            .order("cached_at", desc=True)
            .limit(1)
            .execute()
        )

        if not result.data:
            return None

        cached = result.data[0]
        cached_at = datetime.fromisoformat(cached["cached_at"].replace("Z", "+00:00"))
        age_hours = (datetime.now(cached_at.tzinfo) - cached_at).total_seconds() / 3600

        if age_hours <= max_age_hours:
            logger.info(f"Trends cache HIT para '{keyword}' ({age_hours:.1f}h)")
            return cached["data"]

        # Caché expirado — retornarlo marcado para uso como fallback
        logger.info(f"Trends cache EXPIRED para '{keyword}' ({age_hours:.1f}h)")
        cached["data"]["_expired"] = True
        return cached["data"]

    def save_trends_cache(self, keyword: str, data: dict) -> None:
        """
        Guarda datos de trends en caché.
        Usa UPSERT para actualizar si ya existe.
        """
        cache_data = {
            "keyword": keyword,
            "geo": settings.target_market,
            "data": data,
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

        self._client.table("trends_cache").upsert(
            cache_data, on_conflict="keyword,geo"
        ).execute()

        logger.info(f"Trends cache SAVED para '{keyword}'")


# Singleton — importar `db` en todos los módulos
db = SupabaseDB(_client)
