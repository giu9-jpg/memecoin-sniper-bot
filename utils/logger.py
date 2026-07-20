# utils/logger.py — v2.0
# ═══════════════════════════════════════════════
# Rotation des logs (10MB bot.log, 5MB errors.log)
# Format timestamp ISO
# Niveau DEBUG configurable via LOG_LEVEL dans .env
# get_logger() pour les modules + logger global

import logging
import os
from logging.handlers import RotatingFileHandler

os.makedirs("logs", exist_ok=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LEVEL     = getattr(logging, LOG_LEVEL, logging.INFO)


def _build_logger() -> logging.Logger:
    log = logging.getLogger("MemeSniper")
    log.setLevel(logging.DEBUG)

    if log.handlers:
        return log

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console
    console = logging.StreamHandler()
    console.setLevel(LEVEL)
    console.setFormatter(fmt)
    log.addHandler(console)

    # Fichier principal avec rotation
    file_handler = RotatingFileHandler(
        filename="logs/bot.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)

    # Fichier erreurs uniquement
    error_handler = RotatingFileHandler(
        filename="logs/errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)
    log.addHandler(error_handler)

    return log


# Instance globale
logger = _build_logger()


def get_logger(name: str = "MemeSniper") -> logging.Logger:
    """
    Retourne un logger enfant nommé.
    Utilisé par tous les modules pour avoir des logs identifiés.

    Usage:
        from utils.logger import get_logger
        logger = get_logger(__name__)
    """
    if not name or name == "MemeSniper":
        return logger
    return logger.getChild(name)