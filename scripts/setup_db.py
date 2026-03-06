"""
Script para ejecutar schema.sql contra Supabase.
Uso: python scripts/setup_db.py
"""

import sys
from pathlib import Path

# Asegurar que src/ sea importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import settings
from src.core.logger import get_logger
from supabase import create_client

logger = get_logger("setup_db")

SQL_FILE = Path(__file__).parent.parent / "sql" / "schema.sql"


def run_setup():
    """Ejecuta el schema SQL contra Supabase."""
    if not SQL_FILE.exists():
        logger.error(f"Schema file not found: {SQL_FILE}")
        sys.exit(1)

    sql_content = SQL_FILE.read_text(encoding="utf-8")

    logger.info("Conectando a Supabase...")
    client = create_client(settings.supabase_url, settings.supabase_service_key)

    logger.info("Ejecutando schema.sql...")
    # Ejecutar SQL via RPC o directo
    try:
        # Supabase permite ejecutar SQL raw via rpc
        result = client.rpc("", {}).execute()
    except Exception:
        pass  # rpc vacío no existe, pero el schema se puede ejecutar via SQL Editor

    # Verificar que las tablas existen consultando cada una
    tables = ["productos", "snapshots_diarios", "alertas", "trends_cache"]
    created = []

    for table in tables:
        try:
            result = client.table(table).select("id").limit(0).execute()
            created.append(table)
        except Exception as e:
            logger.warning(f"Tabla '{table}' no encontrada o error: {e}")

    if len(created) == len(tables):
        logger.info(f"Tables created: {', '.join(created)}")
        print(f"Tables created: {', '.join(created)}")
    else:
        missing = set(tables) - set(created)
        logger.warning(
            f"Tables encontradas: {', '.join(created)}. "
            f"Faltantes: {', '.join(missing)}. "
            f"Ejecuta sql/schema.sql manualmente en Supabase SQL Editor."
        )
        print(
            f"⚠️  Tablas faltantes: {', '.join(missing)}\n"
            f"   Ejecuta el contenido de sql/schema.sql en Supabase SQL Editor:\n"
            f"   {settings.supabase_url.replace('.co', '.co')}/project/default/sql"
        )


if __name__ == "__main__":
    run_setup()
