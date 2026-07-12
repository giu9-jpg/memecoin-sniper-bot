"""
Paramètres généraux du bot
Modifie ces valeurs pour ajuster le comportement
"""

# ==========================================
# SEUILS DE DÉTECTION
# ==========================================
MIN_LIQUIDITY = 10000        # Réduit à 10 000$ (plus early)
MIN_VOLUME_24H = 25000       # Réduit à 25 000$
MAX_BUY_TAX = 15             # Tax d'achat max (%)
MAX_SELL_TAX = 15            # Tax de vente max (%)
MIN_MENTIONS = 2             # Mentions minimum réduit
MENTION_WINDOW_MINUTES = 5   # Fenêtre de temps

# ==========================================
# SCORE — SEUILS D'ALERTE
# ==========================================
SCORE_BUY = 7                # 🟢 ACHÈTE si >= 7
SCORE_WATCH = 4              # 🟡 SURVEILLE si >= 4
SCORE_MIN_ALERT = 5          # Seuil minimum pour alerter

# ==========================================
# RÈGLES D'INVESTISSEMENT
# ==========================================
MIN_INVEST = 10              # Investissement min ($)
MAX_INVEST = 50              # Investissement max ($)
MAX_CONCURRENT_POSITIONS = 5 # Nombre max de tokens

# ==========================================
# RÈGLES DE VENTE
# ==========================================
TAKE_PROFIT_X2 = 2.0         # Vendre 50% à x2
TAKE_PROFIT_X5 = 5.0         # Vendre 30% à x5
STOP_LOSS_PERCENT = 0.30     # Stop loss à -30%

# ==========================================
# TRADING
# ==========================================
SLIPPAGE_PERCENT = 10        # Slippage 10%
GAS_MODE = "turbo"           # Mode Gas rapide
ANTI_MEV = True              # Protection MEV

# ==========================================
# SCAN
# ==========================================
SCAN_INTERVAL_SECONDS = 30   # Scanner toutes les 30s

# ==========================================
# BALEINES CONNUES (Smart Money Solana)
# ==========================================
KNOWN_WHALE_WALLETS = [
    {
        "address": "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM",
        "name": "Whale Alpha #1",
        "win_rate": "85%",
        "specialty": "Early memecoins"
    },
    {
        "address": "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
        "name": "Whale Alpha #2",
        "win_rate": "78%",
        "specialty": "Pump.fun gems"
    },
    {
        "address": "GVV4oMNEsN9QqKGRFQazWAjMDMXFEFKpBPnUkHCKqJ7T",
        "name": "Smart Money #1",
        "win_rate": "72%",
        "specialty": "DeFi + Meme"
    },
    {
        "address": "7YttLkHDoNj9wyDur5pM1ejNaAvT9X4eqaYcHQqg9GFo",
        "name": "Smart Money #2",
        "win_rate": "80%",
        "specialty": "Solana ecosystem"
    },
    {
        "address": "CuieVDEDtLo7FypDRBax3YNRTY3v33pFNsFCKPxdFLVX",
        "name": "Degen Whale #1",
        "win_rate": "65%",
        "specialty": "High risk memecoins"
    },
]