# modules/decision_engine.py — v5.2
# Moteur de décision + filtres stricts + blacklist tokens connus

import time
from utils.logger import logger


# ═══════════════════════════════════════════════════════
# TOKENS INTERDITS (jamais alerter)
# ═══════════════════════════════════════════════════════
BLACKLISTED_TOKENS = {
    # Solana natif
    "So11111111111111111111111111111111111111112",   # Wrapped SOL
    # Stablecoins
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    # Grands tokens Solana
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",  # WIF
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",   # JUP
    "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4",  # JLP
    "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey",   # MNDE
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",   # mSOL
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",  # stSOL
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",  # JitoSOL
    "PoPFrfHKzWZoUYzKZbmvJcv6TbTKJfBrEeUFsBXcRRR",   # POPCAT
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",  # PYTH
}


class DecisionEngine:

    def __init__(self):
        self.alert_history = {}
        self.hourly_alerts = []

    # ═══════════════════════════════════════════════════
    # DÉCISION PRINCIPALE
    # ═══════════════════════════════════════════════════
    def decide(self, data: dict) -> dict:
        score        = data.get("score", 0)
        smart_count  = data.get("smart_count", 0)
        has_critical = data.get("has_critical", False)
        market_cap   = data.get("market_cap", 0)
        address      = data.get("address", "")
        liquidity    = data.get("liquidity", 0)
        is_honeypot  = data.get("is_honeypot", False)
        freeze_auth  = data.get("freeze_auth", False)
        top10_pct    = data.get("top_10_holders_pct", 0)
        age_minutes  = data.get("age_minutes", 0)
        holders      = data.get("holders", 0)

        # ── FILTRE ABSOLU : tokens blacklistés ────────
        if address in BLACKLISTED_TOKENS:
            return self._ignore("Token blacklisté (SOL/USDC/BONK/etc)")

        # ── FILTRE ÂGE : trop vieux = pas un memecoin ─
        if age_minutes > 10_080:   # 7 jours
            return self._ignore(f"Trop vieux: {age_minutes/1440:.0f}j")

        # ── FILTRE COHÉRENCE : MC = 0 est louche ──────
        if market_cap == 0:
            return self._ignore("MC = 0 (données invalides)")

        # ── Filtres critiques ─────────────────────────
        if is_honeypot:
            return self._ignore("HONEYPOT détecté")
        if freeze_auth:
            return self._ignore("Freeze authority active")
        if top10_pct > 90:
            return self._ignore(f"Top 10 concentré: {top10_pct}%")
        if market_cap > 10_000_000:
            return self._ignore(f"MC trop élevé: ${market_cap:,.0f}")

        # ── Filtre holders minimum ────────────────────
        if holders < 20:
            return self._ignore(f"Trop peu de holders: {holders}")

        # ── Filtres liquidité ─────────────────────────
        if age_minutes >= 5:
            if liquidity < 5_000:
                return self._ignore(f"Liquidité faible: ${liquidity:.0f}")
        else:
            if liquidity == 0 and score < 8.0:
                return self._ignore(f"Token trop jeune sans liquidité")

        # ── Anti-spam ─────────────────────────────────
        if not self._check_antispam(address):
            return self._ignore("Anti-spam: déjà alerté récemment")

        # ── Tier (SEUILS STRICTS) ─────────────────────
        tier = self._get_tier(score, smart_count, has_critical)

        # ── Stratégie selon MC ────────────────────────
        strategy = self._get_strategy(market_cap)

        # ── Montant ───────────────────────────────────
        amount_eur = self._get_amount(tier)

        # ── Take Profits ──────────────────────────────
        tp_levels = strategy["tp_levels"]
        sl_pct    = strategy["sl_pct"]

        # ── Profit espéré ─────────────────────────────
        if tp_levels:
            weighted_return = sum(
                tp["multiplier"] * tp["sell_pct"] / 100
                for tp in tp_levels
            )
            profit_pct = (weighted_return - 1) * 100
            profit_eur = amount_eur * weighted_return - amount_eur
        else:
            profit_pct = 0
            profit_eur = 0

        # ── Action ───────────────────────────────────
        if tier in ["ULTIMATE", "STRONG", "GOOD", "NORMAL"]:
            action = "ACHÈTE"
        else:
            action = "IGNORE"

        if action != "IGNORE":
            self._register_alert(address)

        return {
            "action":               action,
            "tier":                 tier,
            "amount_eur":           amount_eur,
            "expected_profit_pct":  round(profit_pct, 1),
            "expected_profit_eur":  round(profit_eur, 2),
            "tp_levels":            tp_levels,
            "sl_pct":               sl_pct,
            "strategy_name":        strategy["name"],
            "reason":               f"Score {score}/10 | {smart_count} smart signals",
        }

    # ═══════════════════════════════════════════════════
    # TIERS — VERSION STRICTE (v5.2)
    # ═══════════════════════════════════════════════════
    def _get_tier(self, score, smart_count, has_critical) -> str:
        if score >= 9.5 and smart_count >= 4:
            return "ULTIMATE"
        elif score >= 8.5 and smart_count >= 3:
            return "STRONG"
        elif score >= 8.0 and smart_count >= 2:
            return "GOOD"
        elif score >= 7.5:
            return "NORMAL"
        return "IGNORE"

    def _get_amount(self, tier) -> float:
        return {
            "ULTIMATE": 10.0,
            "STRONG":   8.0,
            "GOOD":     6.0,
            "NORMAL":   5.0,
            "IGNORE":   0.0,
        }.get(tier, 0.0)

    # ═══════════════════════════════════════════════════
    # STRATÉGIES SELON MARKET CAP
    # ═══════════════════════════════════════════════════
    def _get_strategy(self, market_cap: float) -> dict:
        if market_cap < 50_000:
            return {
                "name": "ULTRA_LOW",
                "tp_levels": [
                    {"multiplier": 2,  "sell_pct": 50},
                    {"multiplier": 5,  "sell_pct": 30},
                    {"multiplier": 15, "sell_pct": 15},
                    {"multiplier": 50, "sell_pct": 5},
                ],
                "sl_pct": -35,
            }
        elif market_cap < 200_000:
            return {
                "name": "LOW",
                "tp_levels": [
                    {"multiplier": 2, "sell_pct": 50},
                    {"multiplier": 4, "sell_pct": 30},
                    {"multiplier": 8, "sell_pct": 15},
                    {"multiplier": 20,"sell_pct": 5},
                ],
                "sl_pct": -30,
            }
        elif market_cap < 1_000_000:
            return {
                "name": "MID",
                "tp_levels": [
                    {"multiplier": 1.7, "sell_pct": 50},
                    {"multiplier": 2.5, "sell_pct": 30},
                    {"multiplier": 4,   "sell_pct": 20},
                ],
                "sl_pct": -25,
            }
        else:
            return {
                "name": "HIGH",
                "tp_levels": [
                    {"multiplier": 1.4, "sell_pct": 60},
                    {"multiplier": 1.8, "sell_pct": 30},
                    {"multiplier": 2.5, "sell_pct": 10},
                ],
                "sl_pct": -20,
            }

    # ═══════════════════════════════════════════════════
    # ANTI-SPAM
    # ═══════════════════════════════════════════════════
    def _check_antispam(self, address: str) -> bool:
        now = time.time()
        if address in self.alert_history:
            if now - self.alert_history[address] < 1800:
                return False
        self.hourly_alerts = [
            t for t in self.hourly_alerts if now - t < 3600
        ]
        if len(self.hourly_alerts) >= 20:
            return False
        return True

    def _register_alert(self, address: str):
        now = time.time()
        self.alert_history[address] = now
        self.hourly_alerts.append(now)

    def _ignore(self, reason: str) -> dict:
        return {
            "action":              "IGNORE",
            "tier":                "IGNORE",
            "amount_eur":          0,
            "expected_profit_pct": 0,
            "expected_profit_eur": 0,
            "tp_levels":           [],
            "sl_pct":              0,
            "strategy_name":       "NONE",
            "reason":              reason,
        }