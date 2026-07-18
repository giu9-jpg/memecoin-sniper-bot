# utils/logger.py — v2.0 FIXED
# FIX : rotation des logs pour éviter fichiers géants
# FIX : format timestamp ISO
# FIX : niveau DEBUG configurable via .env
# FIX : encoding UTF-8 explicite

import logging
import os
from logging.handlers import RotatingFileHandler

# Dossier logs
os.makedirs("logs", exist_ok=True)

# Niveau de log configurable
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LEVEL     = getattr(logging, LOG_LEVEL, logging.INFO)


def _build_logger() -> logging.Logger:
    log = logging.getLogger("MemeSniper")
    log.setLevel(logging.DEBUG)   # Capte tout, filtre dans les handlers

    if log.handlers:
        return log   # Déjà configuré

    # ── Format ────────────────────────────────────────
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console ───────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(LEVEL)
    console.setFormatter(fmt)
    log.addHandler(console)

    # ── Fichier avec rotation ──────────────────────────
    # FIX : RotatingFileHandler évite les fichiers de 10Go
    file_handler = RotatingFileHandler(
        filename="logs/bot.log",
        maxBytes=10 * 1024 * 1024,   # 10 MB par fichier
        backupCount=5,               # Garde 5 fichiers max
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    log.addHandler(file_handler)

    # ── Fichier erreurs uniquement ─────────────────────
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


logger = _build_logger()



# ════════════════════════════════════════
# COMPATIBILITÉ v12.0
# Ajout: fonction get_logger() pour les nouveaux modules
# ════════════════════════════════════════

def get_logger(name: str = "MemeSniper") -> logging.Logger:
    """
    Retourne un logger enfant du logger principal
    Compatible avec l'ancien logger global
    
    Usage:
        from utils.logger import get_logger
        logger = get_logger("mon_module")
    """
    if name == "MemeSniper" or not name:
        return logger
    # Créer un sous-logger qui hérite du parent
    child = logger.getChild(name)
    return child