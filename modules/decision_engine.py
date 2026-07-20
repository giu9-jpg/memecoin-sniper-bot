# modules/decision_engine.py — v6.2 FIXED
# ═══════════════════════════════════════════════
# FIX v6.2 :
# - MC = 0 accepté si token < 10 min (bonding curve)
# - Holders < 20 accepté si token < 15 min
# - Liquidité 0 tolérée si token < 10 min (Pump.fun)
# - Tier NORMAL abaissé à 7.0 pour plus d'alertes
# - Tier NORMAL sans smart_count requis
# - Logs détaillés pour debug
# FIX AUDIT :
# - buttons sérialisés correctement dans _send_telegram (via alert_sender)
# - _ignore() retourne dict complet et cohérent

import time
import json
from utils.logger import logger


BLACKLISTED_TOKENS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4",
    "MNDEFzGvMt87ueuHvVU9VcTqsAP5b3fTGPsHuuPA5ey",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn",
    "PoPFrfHKzWZoUYzKZbmvJcv6TbTKJfBrEeUFsBXcRRR",
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
}

MAX_ALERTS_PER_HOUR = 20


class DecisionEngine:

    def __init__(self, market_context=None):
        self.alert_history  = {}
        self.hourly_alerts  = []
        self.market_context = market_context

    def decide(self, data: dict) -> dict:
        score        = float(data.get("score", 0))
        smart_count  = int(data.get("smart_count", 0))
        has_critical = bool(data.get("has_critical", False))
        market_cap   = float(data.get("market_cap", 0))
        address      = data.get("address", "")
        liquidity    = float(data.get("liquidity", 0))
        is_honeypot  = bool(data.get("is_honeypot", False))
        freeze_auth  = bool(data.get("freeze_auth", False))
        top10_pct    = float(data.get("top_10_holders_pct", 0))
        age_minutes  = float(data.get("age_minutes", 0))
        holders      = int(data.get("holders", 0))

        # ── FILTRE MARKET CONTEXT ─────────────────────
        if self.market_context:
            try:
                market_signal = self.market_context.get_market_signal()
                if not market_signal.get("should_alert", True):
                    return self._ignore(
                        f"MARCHÉ: {market_signal.get('reason', 'défavorable')}"
                    )
            except Exception as e:
                logger.debug(f"[DECISION] Market context error: {e}")

        # ── FILTRES ABSOLUS ───────────────────────────
        if not address:
            return self._ignore("Adresse vide")

        if address in BLACKLISTED_TOKENS:
            return self._ignore("Token blacklisté")

        if age_minutes > 10_080:
            return self._ignore(f"Trop vieux: {age_minutes/1440:.1f}j")

        if is_honeypot:
            return self._ignore("HONEYPOT détecté")

        if freeze_auth:
            return self._ignore("Freeze authority active")

        if top10_pct > 90:
            return self._ignore(f"Top 10 trop concentré: {top10_pct:.0f}%")

        if market_cap > 10_000_000:
            return self._ignore(f"MC trop élevé: ${market_cap:,.0f}")

        # ── FILTRE MC = 0 (tolérant pour nouveaux tokens) ──
        if market_cap == 0 and age_minutes > 10:
            return self._ignore(
                f"MC = 0 après {age_minutes:.0f}min (données invalides)"
            )

        # ── FILTRE HOLDERS (tolérant si jeune) ─────────
        if holders < 20 and age_minutes > 15:
            return self._ignore(
                f"Trop peu de holders: {holders} (age: {age_minutes:.0f}min)"
            )

        # ── FILTRE LIQUIDITÉ (tolérant si jeune) ────────
        if age_minutes >= 10:
            if liquidity < 3_000:
                return self._ignore(
                    f"Liquidité trop faible: ${liquidity:.0f} (age: {age_minutes:.0f}min)"
                )

        # ── ANTI-SPAM ─────────────────────────────────
        if not self._check_antispam(address):
            return self._ignore("Anti-spam: déjà alerté récemment")

        # ── TIER ──────────────────────────────────────
        tier = self._get_tier(score, smart_count, has_critical)

        if tier == "IGNORE":
            return self._ignore(f"Score insuffisant: {score:.1f}/10")

        # ── STRATÉGIE ─────────────────────────────────
        strategy   = self._get_strategy(market_cap)
        amount_eur = self._get_amount(tier)
        tp_levels  = strategy["tp_levels"]
        sl_pct     = strategy["sl_pct"]

        # ── CALCUL PROFIT ESPÉRÉ ──────────────────────
        if tp_levels and amount_eur > 0:
            weighted_return = sum(
                tp["multiplier"] * (tp["sell_pct"] / 100)
                for tp in tp_levels
            )
            profit_pct = (weighted_return - 1) * 100
            profit_eur = round(amount_eur * weighted_return - amount_eur, 2)
        else:
            profit_pct = 0.0
            profit_eur = 0.0

        # ── ENREGISTREMENT ────────────────────────────
        self._register_alert(address)

        return {
            "action":              "ACHÈTE",
            "tier":                tier,
            "amount_eur":          amount_eur,
            "expected_profit_pct": round(profit_pct, 1),
            "expected_profit_eur": profit_eur,
            "tp_levels":           tp_levels,
            "sl_pct":              sl_pct,
            "strategy_name":       strategy["name"],
            "reason": (
                f"Score {score:.1f}/10 | "
                f"{smart_count} smart signals | "
                f"tier {tier}"
            ),
        }

    # ═══════════════════════════════════════════════════
    # TIER v6.2
    # ═══════════════════════════════════════════════════

    def _get_tier(
        self,
        score:       float,
        smart_count: int,
        has_critical: bool,
    ) -> str:
        if score >= 9.5 and (smart_count >= 3 or has_critical):
            return "ULTIMATE"
        if score >= 8.5:
            return "STRONG"
        if score >= 7.5:
            return "GOOD"
        if score >= 7.0:
            return "NORMAL"
        return "IGNORE"

    def _get_amount(self, tier: str) -> float:
        return {
            "ULTIMATE": 10.0,
            "STRONG":    8.0,
            "GOOD":      6.0,
            "NORMAL":    5.0,
            "IGNORE":    0.0,
        }.get(tier, 0.0)

    def _get_strategy(self, market_cap: float) -> dict:
        if market_cap < 50_000 or market_cap == 0:
            return {
                "name": "ULTRA_LOW",
                "tp_levels": [
                    {"multiplier": 2,  "sell_pct": 50},
                    {"multiplier": 5,  "sell_pct": 25},
                    {"multiplier": 15, "sell_pct": 15},
                    {"multiplier": 50, "sell_pct": 10},
                ],
                "sl_pct": -35,
            }
        elif market_cap < 200_000:
            return {
                "name": "LOW",
                "tp_levels": [
                    {"multiplier": 2,  "sell_pct": 50},
                    {"multiplier": 4,  "sell_pct": 25},
                    {"multiplier": 8,  "sell_pct": 15},
                    {"multiplier": 20, "sell_pct": 10},
                ],
                "sl_pct": -30,
            }
        elif market_cap < 1_000_000:
            return {
                "name": "MID",
                "tp_levels": [
                    {"multiplier": 1.7, "sell_pct": 50},
                    {"multiplier": 2.5, "sell_pct": 30},
                    {"multiplier": 4.0, "sell_pct": 20},
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

    def _check_antispam(self, address: str) -> bool:
        now = time.time()

        if address in self.alert_history:
            elapsed = now - self.alert_history[address]
            if elapsed < 1800:
                return False

        self.hourly_alerts = [
            t for t in self.hourly_alerts
            if now - t < 3600
        ]

        if len(self.hourly_alerts) >= MAX_ALERTS_PER_HOUR:
            logger.warning(
                f"[ANTISPAM] Limite horaire atteinte "
                f"({MAX_ALERTS_PER_HOUR}/h)"
            )
            return False

        return True

    def _register_alert(self, address: str):
        now = time.time()
        self.alert_history[address] = now
        self.hourly_alerts.append(now)

        if len(self.alert_history) > 1000:
            cutoff = now - 86400
            self.alert_history = {
                addr: ts
                for addr, ts in self.alert_history.items()
                if ts > cutoff
            }

    def _ignore(self, reason: str) -> dict:
        return {
            "action":              "IGNORE",
            "tier":                "IGNORE",
            "amount_eur":          0.0,
            "expected_profit_pct": 0.0,
            "expected_profit_eur": 0.0,
            "tp_levels":           [],
            "sl_pct":              0,
            "strategy_name":       "NONE",
            "reason":              reason,
        }