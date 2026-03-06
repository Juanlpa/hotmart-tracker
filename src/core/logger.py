"""
Configuración central de logging para todo el proyecto.
REGLA: Nunca usar print() para logging. Siempre importar get_logger() desde aquí.
"""

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Retorna un logger configurado con formato estándar.
    Uso: from src.core.logger import get_logger
         logger = get_logger(__name__)
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    return logger
