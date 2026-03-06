"""
Backtesting —Correlación señales → resultados.
CUÁNDO EJECUTAR: manualmente cada 30 días via scripts/run_backtest.py
PROPÓSITO: recalibrar los pesos W1-W4 basándose en resultados reales.
"""

from datetime import date, timedelta

import numpy as np

from src.core.db import db
from src.core.logger import get_logger
from src.scoring.weights import ACTIVE_WEIGHTS

logger = get_logger(__name__)


def run_backtest(dias_atras: int = 90) -> dict:
    """
    CONTRACT:
      Input:  dias_atras: int = 90
      Output: dict con las correlaciones calculadas

    PROCESO:
      1. Obtener alertas con resultado IS NOT NULL
      2. Calcular correlación de Pearson entre sub-scores y resultado
      3. Imprimir tabla con pesos actuales vs sugeridos
      4. NO modificar weights.py automáticamente
    """
    logger.info(f"Iniciando backtesting de últimos {dias_atras} días...")

    # 1. Obtener datos
    data = db.get_products_for_backtest(dias_atras)

    if not data:
        logger.warning("No hay alertas con resultado para backtesting.")
        return {}

    logger.info(f"Analizando {len(data)} alertas con resultado")

    # 2. Extraer scores y resultados
    scores = {
        "score_hotmart": [],
        "score_fb": [],
        "score_trends": [],
        "score_youtube": [],
    }
    outcomes = []  # 1 = ganador, 0 = perdedor/no_promovido

    for alerta in data:
        snapshot = alerta.get("snapshots_diarios", {})
        if not snapshot:
            continue

        for key in scores:
            scores[key].append(float(snapshot.get(key, 0)))

        resultado = alerta.get("resultado", "no_promovido")
        outcomes.append(1.0 if resultado == "ganador" else 0.0)

    if len(outcomes) < 5:
        logger.warning(f"Solo {len(outcomes)} datos — insuficiente para correlación significativa.")
        return {}

    # 3. Calcular correlaciones
    outcomes_arr = np.array(outcomes)
    correlations = {}

    for key, values in scores.items():
        values_arr = np.array(values)
        if np.std(values_arr) == 0 or np.std(outcomes_arr) == 0:
            correlations[key] = 0.0
        else:
            corr = np.corrcoef(values_arr, outcomes_arr)[0, 1]
            correlations[key] = round(float(corr), 4) if not np.isnan(corr) else 0.0

    # 4. Calcular pesos sugeridos (normalizados)
    abs_corrs = {k: max(abs(v), 0.01) for k, v in correlations.items()}
    total_corr = sum(abs_corrs.values())
    suggested = {k: round(v / total_corr, 4) for k, v in abs_corrs.items()}

    # Mapeo a pesos
    current_weights = {
        "score_hotmart": ACTIVE_WEIGHTS.w_hotmart,
        "score_fb": ACTIVE_WEIGHTS.w_fb,
        "score_trends": ACTIVE_WEIGHTS.w_trends,
        "score_youtube": ACTIVE_WEIGHTS.w_youtube,
    }

    # Imprimir tabla
    print("\n" + "=" * 70)
    print("RESULTADO DE BACKTESTING")
    print("=" * 70)
    print(f"{'Señal':<20} {'Correlación':>12} {'Peso Actual':>12} {'Peso Sugerido':>14}")
    print("-" * 70)

    for key in scores:
        print(
            f"{key:<20} {correlations[key]:>12.4f} "
            f"{current_weights[key]:>12.4f} "
            f"{suggested[key]:>14.4f}"
        )

    print("-" * 70)
    print(f"{'TOTAL':<20} {'':>12} {sum(current_weights.values()):>12.4f} {sum(suggested.values()):>14.4f}")
    print("=" * 70)
    print("\n⚠️  NO se modifican los pesos automáticamente.")
    print("   Si la correlación lo justifica, actualizar .env manualmente:")
    print(f"   WEIGHT_HOTMART={suggested['score_hotmart']}")
    print(f"   WEIGHT_FB={suggested['score_fb']}")
    print(f"   WEIGHT_TRENDS={suggested['score_trends']}")
    print(f"   WEIGHT_YOUTUBE={suggested['score_youtube']}")
    print()

    result = {
        "correlations": correlations,
        "current_weights": current_weights,
        "suggested_weights": suggested,
        "sample_size": len(outcomes),
        "win_rate": sum(outcomes) / len(outcomes) if outcomes else 0,
    }

    logger.info(f"Backtesting completado: {len(outcomes)} muestras, win_rate={result['win_rate']:.2%}")
    return result
