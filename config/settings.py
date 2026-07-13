# config/settings.py — v3.0
import os
from dataclasses import dataclass


@dataclass
class Settings:
    # Alertes
    MIN_SCORE:              float = 5.0
    MIN_LIQUIDITY:          float = 10_000.0
    MIN_VOLUME_24H:         float = 25_000.0
    # Filtres
    MAX_AGE_DAYS:           int   = 30
    MAX_PRICE_CHANGE:       float = 2000.0
    # Scan
    POLLING_INTERVAL:       int   = 30
    WHALE_CHECK_EVERY:      int   = 60
    HEALTH_CHECK_EVERY:     int   = 300
    # Trading
    MAX_POSITIONS:          int   = 5
    DEFAULT_BUY_USD:        float = 10.0
    TP1_PERCENT:            float = 100.0
    TP2_PERCENT:            float = 400.0
    SL_PERCENT:             float = -30.0
    SLIPPAGE:               float = 10.0
    ANTI_MEV:               bool  = True
    # Rate limiting
    MAX_ALERTS_PER_MINUTE:  int   = 10
    ALERT_COOLDOWN_SEC:     int   = 3600
    # WebSocket
    WS_HEARTBEAT:           int   = 30
    WS_MAX_RECONNECTS:      int   = 10


# Instance globale
settings = Settings()

# Compatibilité ancien code
SCAN_INTERVAL_SECONDS = settings.POLLING_INTERVAL
MIN_LIQUIDITY         = settings.MIN_LIQUIDITY
SCORE_MIN_ALERT       = settings.MIN_SCORE
SCORE_BUY             = 7.0