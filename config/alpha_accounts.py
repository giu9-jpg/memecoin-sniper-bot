# config/alpha_accounts.py — v11.1 FIXED
# FIX : get_account_tier() insensible à la casse
# FIX : get_account_bonus() robuste si inconnu
# FIX : ajout get_account_info() pour debug
# FIX : backward compat préservée

"""
Alpha Twitter Accounts - v11.1
7 comptes sélectionnés par tier
"""

ALPHA_ACCOUNTS = {

    # ══════════════════════════════════════════
    # TIER 1 — INFLUENCEURS MAJEURS
    # Impact prix : +100% à +500%
    # Bonus score : +2.5
    # ══════════════════════════════════════════
    "TIER1": [
        "Ansem",
        "notthreadguy",
        "Murad_Mahmudov",
        "blknoiz06",
    ],

    # ══════════════════════════════════════════
    # TIER 2 — CALLERS RÉPUTÉS
    # Impact prix : +30% à +100%
    # Bonus score : +1.5
    # ══════════════════════════════════════════
    "TIER2": [
        "Tree_of_Alpha",
    ],

    # ══════════════════════════════════════════
    # TIER 3 — TRACKERS
    # Impact prix : +10% à +30%
    # Bonus score : +1.0
    # ══════════════════════════════════════════
    "TIER3": [
        "inversebrah",
        "lookonchain",
    ],
}

# ══════════════════════════════════════════
# BONUS PAR TIER
# ══════════════════════════════════════════
TWITTER_TIER_BONUS = {
    "TIER1": 2.5,
    "TIER2": 1.5,
    "TIER3": 1.0,
}

# ══════════════════════════════════════════
# SEUILS DE SCORE PAR TIER TWITTER
# ══════════════════════════════════════════
TWITTER_SCORE_THRESHOLDS = {
    "TIER1": 6.0,
    "TIER2": 6.5,
    "TIER3": 7.0,
}

# ══════════════════════════════════════════
# Index inversé : username → tier (insensible à la casse)
# Construit une seule fois au chargement du module
# ══════════════════════════════════════════
_USERNAME_TO_TIER: dict[str, str] = {}
for _tier, _accounts in ALPHA_ACCOUNTS.items():
    for _account in _accounts:
        _USERNAME_TO_TIER[_account.lower()] = _tier


# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

def get_account_tier(username: str) -> str | None:
    """
    Retourne le tier d'un compte Twitter.
    FIX : insensible à la casse, gère le @ initial.
    """
    if not username:
        return None
    clean = username.lstrip("@").lower().strip()
    return _USERNAME_TO_TIER.get(clean)


def get_account_bonus(username: str) -> float:
    """
    Retourne le bonus de score pour un compte Twitter.
    FIX : retourne 0.0 si inconnu au lieu de planter.
    """
    tier = get_account_tier(username)
    if tier is None:
        return 0.0
    return TWITTER_TIER_BONUS.get(tier, 0.0)


def get_account_threshold(username: str) -> float:
    """
    Retourne le seuil de score minimum pour ce compte.
    Utilisé dans main.py pour ajuster min_score.
    """
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
    """
    Retourne toutes les infos d'un compte Twitter.
    Utile pour debug et logs.
    """
    tier = get_account_tier(username)
    if tier is None:
        return {
            "known":     False,
            "username":  username,
            "tier":      None,
            "bonus":     0.0,
            "threshold": 7.5,
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


# ══════════════════════════════════════════
# BACKWARD COMPATIBILITY
# ══════════════════════════════════════════
ALPHA_CALLERS        = ALPHA_ACCOUNTS["TIER1"]
SMART_MONEY_TRACKERS = ALPHA_ACCOUNTS["TIER3"]
MEMECOIN_DEGENS      = ALPHA_ACCOUNTS["TIER2"]
ALL_ACCOUNTS         = get_all_accounts()