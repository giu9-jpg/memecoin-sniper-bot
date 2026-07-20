# config/alpha_accounts.py — v11.1 FIXED
"""
Alpha Twitter Accounts - v11.1
7 comptes sélectionnés par tier
"""

ALPHA_ACCOUNTS = {
    "TIER1": [
        "Ansem",
        "notthreadguy",
        "Murad_Mahmudov",
        "blknoiz06",
    ],
    "TIER2": [
        "Tree_of_Alpha",
    ],
    "TIER3": [
        "inversebrah",
        "lookonchain",
    ],
}

TWITTER_TIER_BONUS = {
    "TIER1": 2.5,
    "TIER2": 1.5,
    "TIER3": 1.0,
}

TWITTER_SCORE_THRESHOLDS = {
    "TIER1": 6.0,
    "TIER2": 6.5,
    "TIER3": 7.0,
}

# Index inversé insensible à la casse
_USERNAME_TO_TIER: dict[str, str] = {}
for _tier, _accounts in ALPHA_ACCOUNTS.items():
    for _account in _accounts:
        _USERNAME_TO_TIER[_account.lower()] = _tier


def get_account_tier(username: str) -> str | None:
    """Retourne le tier d'un compte Twitter (insensible à la casse)."""
    if not username:
        return None
    clean = username.lstrip("@").lower().strip()
    return _USERNAME_TO_TIER.get(clean)


def get_account_bonus(username: str) -> float:
    """Retourne le bonus de score pour un compte Twitter."""
    tier = get_account_tier(username)
    if tier is None:
        return 0.0
    return TWITTER_TIER_BONUS.get(tier, 0.0)


def get_account_threshold(username: str) -> float:
    """Retourne le seuil de score minimum pour ce compte."""
    tier = get_account_tier(username)
    if tier is None:
        return 7.5
    return TWITTER_SCORE_THRESHOLDS.get(tier, 7.5)


def get_all_accounts() -> list:
    """Retourne tous les comptes toutes tiers confondus."""
    all_accounts = []
    for accounts in ALPHA_ACCOUNTS.values():
        all_accounts.extend(accounts)
    return all_accounts


def get_account_info(username: str) -> dict:
    """Retourne toutes les infos d'un compte Twitter."""
    tier = get_account_tier(username)
    if tier is None:
        return {
            "known": False, "username": username,
            "tier": None, "bonus": 0.0, "threshold": 7.5,
        }
    return {
        "known":     True,
        "username":  username,
        "tier":      tier,
        "bonus":     TWITTER_TIER_BONUS.get(tier, 0.0),
        "threshold": TWITTER_SCORE_THRESHOLDS.get(tier, 7.5),
    }


def get_tier_accounts(tier: str) -> list:
    """Retourne les comptes d'un tier spécifique."""
    return ALPHA_ACCOUNTS.get(tier, [])


# Backward compatibility
ALPHA_CALLERS        = ALPHA_ACCOUNTS["TIER1"]
SMART_MONEY_TRACKERS = ALPHA_ACCOUNTS["TIER3"]
MEMECOIN_DEGENS      = ALPHA_ACCOUNTS["TIER2"]
ALL_ACCOUNTS         = get_all_accounts()