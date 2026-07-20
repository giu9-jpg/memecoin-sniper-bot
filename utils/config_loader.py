# utils/config_loader.py — v1.0
# Chargement centralisé de la configuration depuis .env

import os
from dataclasses import dataclass, field
from utils.logger import get_logger

logger = get_logger("config_loader")


@dataclass
class DashboardConfig:
    enabled: bool = True
    host:    str  = "0.0.0.0"
    port:    int  = 8080


@dataclass
class BotConfig:
    telegram_token:      str   = ""
    telegram_chat_id:    str   = ""
    solana_rpc_url:      str   = ""
    log_level:           str   = "INFO"
    dashboard:           DashboardConfig = field(
        default_factory=DashboardConfig
    )
    min_score:           float = 7.5
    max_alerts_per_hour: int   = 20


def load_config() -> BotConfig:
    """
    Charge et valide la config depuis les variables d'environnement.
    Lève ValueError si les variables obligatoires sont manquantes.
    """
    # Railway injecte PORT automatiquement
    # On l'utilise en priorité pour le dashboard
    railway_port = os.getenv("PORT")
    dashboard_port = int(
        railway_port
        or os.getenv("DASHBOARD_PORT", "8080")
    )

    config = BotConfig(
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        solana_rpc_url=os.getenv("SOLANA_RPC_URL", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        dashboard=DashboardConfig(
            enabled=os.getenv(
                "DASHBOARD_ENABLED", "true"
            ).lower() == "true",
            host=os.getenv("DASHBOARD_HOST", "0.0.0.0"),
            port=dashboard_port,
        ),
        min_score=float(os.getenv("MIN_SCORE", "7.5")),
        max_alerts_per_hour=int(
            os.getenv("MAX_ALERTS_PER_HOUR", "20")
        ),
    )

    # Validation
    errors = []
    if not config.telegram_token:
        errors.append("TELEGRAM_BOT_TOKEN manquant")
    if not config.telegram_chat_id:
        errors.append("TELEGRAM_CHAT_ID manquant")
    if not config.solana_rpc_url:
        errors.append("SOLANA_RPC_URL manquant")

    if errors:
        for err in errors:
            logger.error(f"❌ Config : {err}")
        raise ValueError(
            f"Configuration invalide : {len(errors)} erreur(s)"
        )

    logger.info("✅ Configuration chargée")
    logger.info(
        f"   Dashboard : "
        f"{'ACTIVÉ' if config.dashboard.enabled else 'DÉSACTIVÉ'} "
        f"(port {config.dashboard.port})"
    )
    logger.info(f"   Score min : {config.min_score}")

    return config