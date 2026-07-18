# utils/config_loader.py v1.0
"""
Chargement centralisé de la configuration depuis .env
"""

import os
from dataclasses import dataclass, field
from utils.logger import get_logger

logger = get_logger("config_loader")


@dataclass
class DashboardConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8080


@dataclass
class BotConfig:
    # Core
    telegram_token: str = ""
    telegram_chat_id: str = ""
    solana_rpc_url: str = ""
    log_level: str = "INFO"

    # Dashboard
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)

    # Scoring
    min_score: float = 7.5
    max_alerts_per_hour: int = 20


def load_config() -> BotConfig:
    """
    Charge et valide la config depuis .env
    Retourne un objet BotConfig
    """
    config = BotConfig(
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        solana_rpc_url=os.getenv("SOLANA_RPC_URL", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),

        dashboard=DashboardConfig(
            enabled=os.getenv("DASHBOARD_ENABLED", "true").lower() == "true",
            host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
            port=int(os.getenv("DASHBOARD_PORT", "8080")),
        ),

        min_score=float(os.getenv("MIN_SCORE", "7.5")),
        max_alerts_per_hour=int(os.getenv("MAX_ALERTS_PER_HOUR", "20")),
    )

    # ── Validation ──
    errors = []
    if not config.telegram_token:
        errors.append("TELEGRAM_BOT_TOKEN manquant")
    if not config.telegram_chat_id:
        errors.append("TELEGRAM_CHAT_ID manquant")
    if not config.solana_rpc_url:
        errors.append("SOLANA_RPC_URL manquant")

    if errors:
        for err in errors:
            logger.error(f"❌ {err}")
        raise ValueError(f"Config invalide: {len(errors)} erreur(s)")

    logger.info("✅ Configuration v12.0 chargée")
    logger.info(f"   Dashboard: {'ACTIVÉ' if config.dashboard.enabled else 'DÉSACTIVÉ'}")
    logger.info(f"   Score min: {config.min_score}")

    return config