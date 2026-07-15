# config/alpha_wallets.py — v7.0
# Top 20 alpha wallets vérifiés sur GMGN + Cielo Finance
# Dernière mise à jour : Juillet 2025

ALPHA_WALLETS = {

    # ══════════════════════════════════════════════════
    # 🥇 TIER 1 — ÉLITE (8 wallets)
    # Confirmés multi-plateformes ou top rank
    # Win Rate > 70% | PnL > $100k
    # ══════════════════════════════════════════════════
    "TIER1": [
        # ── Confirmés GMGN + Cielo (les meilleurs) ──
        "hnu69n6P5CgYXCtUKii9wgamqtDeTVHY3TVJ6HKt7wC",
        "gtfoTELAeEZHUgHetA6umfsCETiBMzJCN4tB2sqCgFL",

        # ── Top GMGN Tier 1 ─────────────────────────
        "C3pnJjni74HSJSE8xRjG1fcY5h5VpN4gSHXgYwnXmD83",
        "7UaUSBDNwiQtbPrDi8piH1wKvmgymUBmkY8zkAk9jQwR",
        "Hd5wMoiypHWRQmkus5SHu6ECH27fXVqkhg3d5rGhvLAL",

        # ── Top Cielo Tier 1 ────────────────────────
        "yHCxHBEaJW5tbndqC8JciSThr7U1cqLpdcsvHcx6PRe",
        "8ZN71XTdVo8yRovnGLmNgW3Tgniw6A4J3JGLvPD686FP",

        # ── Nouveau GMGN #1 ─────────────────────────
        "9R6fxLZVnjuPyeX4ns6UnhwkKh9XNpUaHuJSUSyxjGQT",
    ],

    # ══════════════════════════════════════════════════
    # 🥈 TIER 2 — CONFIRMÉS (7 wallets)
    # Très bons traders, une seule plateforme
    # Win Rate > 60% | PnL > $50k
    # ══════════════════════════════════════════════════
    "TIER2": [
        # ── GMGN Tier 1.5 ────────────────────────────
        "CAmNcBJ82xr1tzXrwZ6tZKwEFs26TG8kT6dJeR1bxjW9",

        # ── Cielo solides ────────────────────────────
        "7qNbdfpsVdDGmkzfhQJE1ByVqjzAuf9d2Gaoh388sZtL",
        "8i5U2uNBEuTc4zskYP14zbebDg2RSwrrG8REhEnJb97K",
        "6qudAN2kV8mtCcYJxb5QQ6Vr15itdHHdeVbYm99NKMhy",

        # ── Nouveaux GMGN ────────────────────────────
        "9VL5LaHxAj9irfBDDhikzFRB4qZLu8Xfce3w19rNnNYZ",
        "2zbM47wNKDfkwYD7d7iaVApaPwof8DSTZJau9UHxuqXv",
        "FMZ44hADrhZ5AzKKqT7y2sWuZ6f55UZVqnjaqWDbWSja",
    ],

    # ══════════════════════════════════════════════════
    # 🥉 TIER 3 — PROMETTEURS (5 wallets)
    # Bons wallets à surveiller
    # Win Rate > 50% | PnL positif
    # ══════════════════════════════════════════════════
    "TIER3": [
        # ── Nouveaux GMGN ────────────────────────────
        "2fNPNJKE3ny6b5Vo1wdfa7J7KqYNjeyBM3PbGGSJ398r",
        "6QyMtDxcXzTtB8VngkrjMv4pbtG1Gj1XxTuKnyDh3MoS",
        "5cJuSDxWQzzPUNzBMTisjRJyxz5xLQV6oBfkUiP3HapT",

        # ── Cielo ────────────────────────────────────
        "FnW6MLyu5UX1G4fYcmmBrPy46foBi6vm4GTWNZQkxUrF",
        "7ufmve7ZSFCzuNcKRunYrGtyb2Ka1MXzkWwf7jZhVsmL",
    ],
}


# ══════════════════════════════════════════════════════
# BONUS PAR TIER
# ══════════════════════════════════════════════════════
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

    return min(total_bonus, 5.0), message