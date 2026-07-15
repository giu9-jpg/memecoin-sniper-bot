# config/strategy.py — v5.0
# Stratégie optimisée pour 100€ de capital

# ═══════════════════════════════════════════════════
# CAPITAL & POSITION SIZING
# ═══════════════════════════════════════════════════
CAPITAL_TOTAL         = 100.0
MAX_POSITION_PCT      = 10.0
MAX_POSITION_EUR      = 10.0
MIN_POSITION_EUR      = 3.0
RESERVE_PCT           = 20.0
MAX_OPEN_POSITIONS    = 3

# ═══════════════════════════════════════════════════
# SEUILS DE DÉCISION
# ═══════════════════════════════════════════════════
SCORE_MIN_ALERT       = 6.0
SCORE_MIN_BUY         = 7.5
SCORE_STRONG_BUY      = 8.5
SCORE_ULTIMATE        = 9.5

MIN_SIGNALS_TO_BUY    = 2
MIN_SIGNALS_STRONG    = 4
MIN_SIGNALS_ULTIMATE  = 5

# ═══════════════════════════════════════════════════
# POSITION SIZING
# ═══════════════════════════════════════════════════
POSITION_SIZES = {
    "ULTIMATE":    10.0,
    "STRONG":      8.0,
    "GOOD":        6.0,
    "NORMAL":      5.0,
    "SMALL":       3.0,
    "WATCH":       0.0,
}

# ═══════════════════════════════════════════════════
# TAKE PROFITS SELON MC
# ═══════════════════════════════════════════════════
TP_STRATEGY = {
    "ULTRA_LOW": {
        "tp1_mult":    2.0,  "tp1_sell": 50,
        "tp2_mult":    5.0,  "tp2_sell": 30,
        "tp3_mult":   15.0,  "tp3_sell": 15,
        "runner":      5,
        "sl_pct":    -35,
    },
    "LOW": {
        "tp1_mult":    2.0,  "tp1_sell": 50,
        "tp2_mult":    4.0,  "tp2_sell": 30,
        "tp3_mult":    8.0,  "tp3_sell": 15,
        "runner":      5,
        "sl_pct":    -30,
    },
    "MID": {
        "tp1_mult":    1.7,  "tp1_sell": 50,
        "tp2_mult":    2.5,  "tp2_sell": 30,
        "tp3_mult":    4.0,  "tp3_sell": 20,
        "runner":      0,
        "sl_pct":    -25,
    },
    "HIGH": {
        "tp1_mult":    1.4,  "tp1_sell": 60,
        "tp2_mult":    1.8,  "tp2_sell": 30,
        "tp3_mult":    2.5,  "tp3_sell": 10,
        "runner":      0,
        "sl_pct":    -20,
    },
}

# ═══════════════════════════════════════════════════
# FILTRES DE SÉCURITÉ
# ═══════════════════════════════════════════════════
SECURITY_FILTERS = {
    "reject_if_honeypot":         True,
    "reject_if_freeze_auth":      True,
    "reject_if_no_mint_renounce": False,
    "min_liquidity_usd":          8_000,
    "max_top10_pct":              75,
    "min_holders":                20,
    "max_price_change_24h":       500,
}

# ═══════════════════════════════════════════════════
# ANTI-SPAM
# ═══════════════════════════════════════════════════
MAX_ALERTS_PER_HOUR    = 20
COOLDOWN_SAME_TOKEN    = 3600
DAILY_TRADE_LIMIT      = 5