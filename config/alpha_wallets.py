# config/alpha_wallets.py — v6.0
# Liste des "alpha wallets" - traders qui ont fait +1000% récemment

ALPHA_WALLETS = {
    # ══════════ TIER 1 — Légendes ══════════
    "TIER1": [
        "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # Ansem
        "GJRs4FwHtemZ5ZE9x3FNvJ8TMwitKTh21yxdRPqn7npE",  # 0xSun
        "6QG5X6cULLLd4CBpV3zTaJvQtN2ZdQEwFxTF8y1ub7nL",  # Cented
        "F1Kir7cf4z3uYX9dXY3AAhUKfCyGaLdRWfKtj7BdF6BE",  # Mert
        "AA6Y6iTuBjRnfnwzs2fLDbKmHVGnHwMWXQ3d4vqB4W7z",  # Frank
    ],

    # ══════════ TIER 2 — Confirmés ══════════
    "TIER2": [
        "orcACRJYTFjTeo2pV8TfYRTpmqfoYgbVi9GeANXTCc8",   # Kev
        "2FoDufWLmMDvXvxwmiG7CmA9dNXPHVeVwXQrDPu1FrKm",  # Kadenox
        "6dsFTWpBhCVJXPdnwyYzr3rF3rTn8YZGYh1i5H85pump",  # Ashley
        "8DYFhLVvHUiEmvsq3TmY7yEfHZ2XR8ZbNmy5UYZQpump",  # DingerCoins
        "4kQwbTvPGVEQY8pmzT8xNaK7QVR4dCVWnjTVL7yQaBuM",  # Waddles
    ],

    # ══════════ TIER 3 — Prometteurs ══════════
    "TIER3": [
        "F1RcTVPBBkKZQMSTWnFTHrJ8vHnKfDpBQqYVfGtiPvKf",
        "GKvpDCyDrqiWJfaEbYWzhDCwvKKfBhpDsWnCDPHnHPtb",
        "AtRKfHnLp3fCBmEyc3F5FvKfBjJ2fTZ3aVXwYzTGSPTf",
    ],
}

# Bonus par tier
TIER_BONUS = {
    "TIER1": 3.0,
    "TIER2": 2.0,
    "TIER3": 1.0,
}


def get_wallet_tier(wallet: str) -> str | None:
    for tier, wallets in ALPHA_WALLETS.items():
        if wallet in wallets:
            return tier
    return None


def get_alpha_bonus(wallets_detected: list) -> tuple[float, str]:
    """Calcule le bonus alpha selon les wallets détectés."""
    if not wallets_detected:
        return 0, ""

    total_bonus = 0
    tiers_hit   = []

    for wallet in wallets_detected:
        tier = get_wallet_tier(wallet)
        if tier:
            total_bonus += TIER_BONUS[tier]
            tiers_hit.append(tier)

    if len(tiers_hit) >= 3:
        total_bonus += 2.0
        message = f"🚨 {len(tiers_hit)} ALPHA WALLETS achètent !"
    elif len(tiers_hit) == 2:
        total_bonus += 1.0
        message = f"🐋 2 alpha wallets détectés"
    elif len(tiers_hit) == 1:
        message = f"🐋 Alpha wallet {tiers_hit[0]}"
    else:
        message = ""

    return min(total_bonus, 5.0), message  # Cap à +5