# utils/config_loader.py — v1.2 Railway-safe
# Chargement centralisé et robuste de la configuration depuis .env / Railway

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from utils.logger import get_logger

load_dotenv()

logger = get_logger("config_loader")


TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "y",
    "on",
    "oui",
    "vrai",
}

FALSE_VALUES = {
    "0",
    "false",
    "no",
    "n",
    "off",
    "non",
    "faux",
}


def _clean_raw(value: Any) -> str:
    return str(value).strip().strip('"').strip("'")


def env_str(name: str, default: str = "") -> str:
    raw = os.getenv(name)

    if raw is None or str(raw).strip() == "":
        return default

    return _clean_raw(raw)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)

    if raw is None or str(raw).strip() == "":
        return default

    value = _clean_raw(raw).lower()

    if value in TRUE_VALUES:
        return True

    if value in FALSE_VALUES:
        return False

    logger.warning(
        f"⚠️ Config {name} invalide={raw!r}, fallback={default}"
    )

    return default


def env_float(
    name: str,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    raw = os.getenv(name)

    if raw is None or str(raw).strip() == "":
        value = float(default)
    else:
        try:
            # Accepte 7.5 et 7,5
            value = float(_clean_raw(raw).replace(",", "."))
        except Exception:
            logger.warning(
                f"⚠️ Config {name} invalide={raw!r}, fallback={default}"
            )
            value = float(default)

    if min_value is not None and value < min_value:
        logger.warning(
            f"⚠️ Config {name} trop bas={value}, min={min_value}"
        )
        value = min_value

    if max_value is not None and value > max_value:
        logger.warning(
            f"⚠️ Config {name} trop haut={value}, max={max_value}"
        )
        value = max_value

    return value


def env_int(
    name: str,
    default: int,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    raw = os.getenv(name)

    if raw is None or str(raw).strip() == "":
        value = int(default)
    else:
        try:
            # Accepte "10", "10.0" et "10,0"
            value = int(float(_clean_raw(raw).replace(",", ".")))
        except Exception:
            logger.warning(
                f"⚠️ Config {name} invalide={raw!r}, fallback={default}"
            )
            value = int(default)

    if min_value is not None and value < min_value:
        logger.warning(
            f"⚠️ Config {name} trop bas={value}, min={min_value}"
        )
        value = min_value

    if max_value is not None and value > max_value:
        logger.warning(
            f"⚠️ Config {name} trop haut={value}, max={max_value}"
        )
        value = max_value

    return value


def get_data_dir() -> Path:
    """
    Chemin data compatible local + Railway Volume.

    Recommandé Railway si tu ajoutes un Volume :
      DATA_DIR=/app/data

    Local Windows :
      DATA_DIR=data
    """

    return Path(env_str("DATA_DIR", "data"))


@dataclass
class DashboardConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class BotConfig:
    telegram_token: str = ""
    telegram_chat_id: str = ""
    solana_rpc_url: str = ""
    log_level: str = "INFO"

    dashboard: DashboardConfig = field(
        default_factory=DashboardConfig
    )

    min_score: float = 8.0
    max_alerts_per_hour: int = 10

    data_dir: str = "data"


def _detect_dashboard_host() -> str:
    host = env_str("DASHBOARD_HOST", "0.0.0.0")

    # Sur Railway il faut écouter publiquement.
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"):
        if host in ("127.0.0.1", "localhost"):
            logger.warning(
                "⚠️ Railway détecté : DASHBOARD_HOST forcé à 0.0.0.0"
            )
            return "0.0.0.0"

    return host


def _detect_dashboard_port() -> int:
    """
    Railway injecte PORT automatiquement pour le web service.
    En local, on utilise DASHBOARD_PORT.
    """

    railway_port = os.getenv("PORT")

    if railway_port:
        return env_int(
            "PORT",
            8080,
            min_value=1,
            max_value=65535,
        )

    return env_int(
        "DASHBOARD_PORT",
        8080,
        min_value=1,
        max_value=65535,
    )


def load_config() -> BotConfig:
    """
    Charge et valide la config.

    Important :
    - Ne crash plus sur MIN_SCORE=7,5.
    - Accepte les virgules et les points.
    - Garde le bot en alertes + paper trading uniquement.
    """

    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    config = BotConfig(
        telegram_token=env_str("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=env_str("TELEGRAM_CHAT_ID", ""),
        solana_rpc_url=env_str("SOLANA_RPC_URL", ""),
        log_level=env_str("LOG_LEVEL", "INFO").upper(),

        dashboard=DashboardConfig(
            enabled=env_bool("DASHBOARD_ENABLED", True),
            host=_detect_dashboard_host(),
            port=_detect_dashboard_port(),
        ),

        # Réglage conseillé actuel : qualité > quantité
        min_score=env_float(
            "MIN_SCORE",
            8.0,
            min_value=0.0,
            max_value=10.0,
        ),

        max_alerts_per_hour=env_int(
            "MAX_ALERTS_PER_HOUR",
            10,
            min_value=1,
            max_value=120,
        ),

        data_dir=str(data_dir),
    )

    errors: list[str] = []

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
        f"({config.dashboard.host}:{config.dashboard.port})"
    )

    logger.info(f"   Score min : {config.min_score}")
    logger.info(f"   Max alertes/h : {config.max_alerts_per_hour}")
    logger.info(f"   Data dir : {config.data_dir}")

    return config


__all__ = [
    "DashboardConfig",
    "BotConfig",
    "load_config",
    "env_str",
    "env_bool",
    "env_float",
    "env_int",
    "get_data_dir",
]