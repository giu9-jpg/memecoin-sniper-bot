# config/alpha_wallets.py — v10.2 FIXED
"""
Alpha Wallets - v10.2
15 wallets sélectionnés sur données réelles Cielo + GMGN
"""

ALPHA_WALLETS = {
    "TIER1": [
        "yHCxHBEaJW5tbndqC8JciSThr7U1cqLpdcsvHcx6PRe",
        "8ZN71XTdVo8yRovnGLmNgW3Tgniw6A4J3JGLvPD686FP",
        "Dzp1SrZ474xwGp6ZEP6cNKo39u9zeXe1YAuTkyZyv3t4",
        "8i5U2uNBEuTc4zskYP14zbebDg2RSwrrG8REhEnJb97K",
    ],
    "TIER1_5": [
        "HDdZcq56muM7t3g77ViJ55FiEvyoYjQbrRNxCSUsG8er",
        "6MAmqJ7aGtTReML2DezAzmRckQyFoGfKKf6gWVak7P2d",
        "DjM7Tu7whh6P3pGVBfDzwXAx2zaw51GJWrJE3PwtuN7s",
        "D8n8Dy6DWC9691mR4NroSA9TdxXBxDV6Rr639RapanS4",
        "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL",
    ],
    "TIER2": [
        "7ufmve7ZSFCzuNcKRunYrGtyb2Ka1MXzkWwf7jZhVsmL",
        "54yAKtNUBDi4VPNzcSr6qXxA86ZYKBCiHB2MgzrfMrpK",
        "4JotQn2ixNrXDncDWGHE9j74FjXiacF47vC3mXDzCEcp",
        "FnW6MLyu5UX1G4fYcmmBrPy46foBi6vm4GTWNZQkxUrF",
        "32mRYcNZJfG8gFrn9gvqusUtaWekXVAVQpkc97j5M9iT",
        "9Q18hhGJxvy16VAa8Th8Lua4WUSxnW1E1mYmqS16aPFN",
    ],
}

TIER_BONUS = {
    "TIER1":   3.5,
    "TIER1_5": 2.5,
    "TIER2":   1.5,
}

COPY_TRADING_THRESHOLDS = {
    "TIER1":   5.5,
    "TIER1_5": 6.0,
    "TIER2":   6.5,
}

MAX_CUMULATIVE_BONUS = 5.0


def get_wallet_tier(wallet_address: str):
    """Retourne le tier d'un wallet ou None."""
    for tier, wallets in ALPHA_WALLETS.items():
        if wallet_address in wallets:
            return tier
    return None


def get_wallet_bonus(wallet_addresses):
    """
    FIX v10.2 : accepte str OU list.
    Retourne toujours (bonus: float, message: str).
    """
    if isinstance(wallet_addresses, str):
        wallet_addresses = [wallet_addresses]
    elif not isinstance(wallet_addresses, (list, set, tuple)):
        return 0.0, ""

    if not wallet_addresses:
        return 0.0, ""

    tiers_found = []
    for wallet in wallet_addresses:
        tier = get_wallet_tier(wallet)
        if tier and tier not in tiers_found:
            tiers_found.append(tier)

    if not tiers_found:
        return 0.0, ""

    total_bonus = sum(TIER_BONUS.get(t, 0.0) for t in tiers_found)
    total_bonus = min(total_bonus, MAX_CUMULATIVE_BONUS)

    count = len(wallet_addresses)
    top_tier = tiers_found[0]

    if count >= 3:
        message = f"{count} alpha wallets detected ({top_tier})"
    elif count == 2:
        message = f"2 alpha wallets ({'/'.join(tiers_found)})"
    else:
        message = f"Alpha wallet detected ({top_tier})"

    return round(total_bonus, 1), message


def get_all_wallets():
    """Retourne tous les wallets toutes tiers confondus."""
    all_wallets = []
    for wallets in ALPHA_WALLETS.values():
        all_wallets.extend(wallets)
    return all_wallets


def get_copy_threshold(wallet_address: str) -> float:
    """Retourne le seuil de score minimum pour le copy trading."""
    tier = get_wallet_tier(wallet_address)
    if tier is None:
        return 7.5
    return COPY_TRADING_THRESHOLDS.get(tier, 7.5)


def get_wallet_info(wallet_address: str) -> dict:
    """Retourne toutes les infos d'un wallet."""
    tier = get_wallet_tier(wallet_address)
    if tier is None:
        return {
            "known":     False,
            "tier":      None,
            "bonus":     0.0,
            "threshold": 7.5,
        }
    return {
        "known":     True,
        "tier":      tier,
        "bonus":     TIER_BONUS.get(tier, 0.0),
        "threshold": COPY_TRADING_THRESHOLDS.get(tier, 7.5),
    }


def get_tier_wallets(tier: str) -> list:
    """Retourne les wallets d'un tier spécifique."""
    return ALPHA_WALLETS.get(tier, [])
