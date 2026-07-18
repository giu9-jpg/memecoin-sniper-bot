"""
Alpha Wallets - v10.0
15 wallets sélectionnés sur données réelles Cielo + GMGN
Dernière analyse : Juillet 2025
"""

ALPHA_WALLETS = {

    # ══════════════════════════════════════════
    # TIER 1 — LES DIEUX
    # Win Rate > 94% | Ratio Sell/Buy > 1.5x
    # Bonus : +3.5 | Seuil copy : 5.5
    # ══════════════════════════════════════════
    "TIER1": [
        # 94.64% WR | 5073 trades | Sell/Buy 1.91x | Max profit $197K
        "yHCxHBEaJW5tbndqC8JciSThr7U1cqLpdcsvHcx6PRe",
        # 97.36% WR | 4631 trades | Sell/Buy 1.89x | Max DD -$700
        "8ZN71XTdVo8yRovnGLmNgW3Tgniw6A4J3JGLvPD686FP",
        # 100% WR | 277 trades | Sell/Buy 3.10x | Triple ses mises
        "Dzp1SrZ474xwGp6ZEP6cNKo39u9zeXe1YAuTkyZyv3t4",
        # 96.53% WR | 1844 trades | Portfolio $28K | Max profit $13K
        "8i5U2uNBEuTc4zskYP14zbebDg2RSwrrG8REhEnJb97K",
    ],

    # ══════════════════════════════════════════
    # TIER 1.5 — L'ÉLITE
    # Win Rate > 88% | Ratio Sell/Buy > 1.5x
    # Bonus : +2.5 | Seuil copy : 6.0
    # ══════════════════════════════════════════
    "TIER1_5": [
        # 100% WR | 2325 trades | Sell/Buy 2.12x
        "HDdZcq56muM7t3g77ViJ55FiEvyoYjQbrRNxCSUsG8er",
        # 97.47% WR | 204 trades | Sell/Buy 1.90x
        "6MAmqJ7aGtTReML2DezAzmRckQyFoGfKKf6gWVak7P2d",
        # 95.29% WR | 461 trades | Portfolio $165K
        "DjM7Tu7whh6P3pGVBfDzwXAx2zaw51GJWrJE3PwtuN7s",
        # 88.73% WR | 573 trades | Sell/Buy 2.38x
        "D8n8Dy6DWC9691mR4NroSA9TdxXBxDV6Rr639RapanS4",
        # 78.11% WR | +$78K en 30j | Volume $1.5M
        "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL",
    ],

    # ══════════════════════════════════════════
    # TIER 2 — CONFIRMÉS
    # Win Rate > 80% | Profitables
    # Bonus : +1.5 | Seuil copy : 6.5
    # ══════════════════════════════════════════
    "TIER2": [
        # 90.48% WR | 531 trades | Portfolio $41.6K
        "7ufmve7ZSFCzuNcKRunYrGtyb2Ka1MXzkWwf7jZhVsmL",
        # 98.48% WR | 373 trades | Ultra safe
        "54yAKtNUBDi4VPNzcSr6qXxA86ZYKBCiHB2MgzrfMrpK",
        # 92.73% WR | 147 trades | Portfolio $22.8K
        "4JotQn2ixNrXDncDWGHE9j74FjXiacF47vC3mXDzCEcp",
        # 87.23% WR | 438 trades | +$64K PnL
        "FnW6MLyu5UX1G4fYcmmBrPy46foBi6vm4GTWNZQkxUrF",
        # 100% WR | 104 trades | Portfolio $48.5K
        "32mRYcNZJfG8gFrn9gvqusUtaWekXVAVQpkc97j5M9iT",
        # 100% WR | 313 trades | Sell/Buy 1.78x
        "9Q18hhGJxvy16VAa8Th8Lua4WUSxnW1E1mYmqS16aPFN",
    ],
}

# ══════════════════════════════════════════
# BONUS PAR TIER
# ══════════════════════════════════════════
TIER_BONUS = {
    "TIER1":   3.5,
    "TIER1_5": 2.5,
    "TIER2":   1.5,
}

# ══════════════════════════════════════════
# SEUILS COPY TRADING
# ══════════════════════════════════════════
COPY_TRADING_THRESHOLDS = {
    "TIER1":   5.5,
    "TIER1_5": 6.0,
    "TIER2":   6.5,
}

# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════
def get_wallet_tier(wallet_address: str):
    for tier, wallets in ALPHA_WALLETS.items():
        if wallet_address in wallets:
            return tier
    return None

def get_wallet_bonus(wallet_address: str) -> float:
    tier = get_wallet_tier(wallet_address)
    return TIER_BONUS.get(tier, 0.0) if tier else 0.0

def get_all_wallets() -> list:
    all_wallets = []
    for wallets in ALPHA_WALLETS.values():
        all_wallets.extend(wallets)
    return all_wallets

def get_copy_threshold(wallet_address: str) -> float:
    tier = get_wallet_tier(wallet_address)
    return COPY_TRADING_THRESHOLDS.get(tier, 7.5) if tier else 7.5