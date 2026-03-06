"""
Script para ejecutar backtesting manualmente.
Uso: python scripts/run_backtest.py [dias_atras]
"""

import sys
from pathlib import Path

# Asegurar imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.analyzer import run_backtest


def main():
    dias = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    print(f"Ejecutando backtesting de últimos {dias} días...\n")
    result = run_backtest(dias)

    if not result:
        print("No hay suficientes datos para backtesting.")
        print("Necesitas al menos 5 alertas con resultado (ganador/perdedor) marcado.")
        sys.exit(1)


if __name__ == "__main__":
    main()
