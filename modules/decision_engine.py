# modules/decision_engine.py — v6.4 HIGH CONVICTION
# ═══════════════════════════════════════════════
# v6.4 :
# + Vérifie safety_score avant de donner un tier
# + ULTIMATE impossible sans safety ≥ 7.0
# + ULTIMATE impossible si liq $0
# + Exige au moins 1 catalyst de conviction
# + NORMAL très rare
# ═══════════════════════════════════════════════

import time
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

MAX_ALERTS_PER_HOUR = 15  # réduit de 20 à 15


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

        # Récupère le safety score depuis les données
        safety       = data.get("safety", {}) or {}
        safety_score = float(safety.get("score", 0) or 0)

        # Catalysts de conviction
        alpha_count = int(data.get("alpha_wallets", 0) or 0)
        has_twitter = bool(data.get("twitter_signal"))
        whale_data  = data.get("whale_inflow", {}) or {}
        has_whale   = bool(whale_data.get("has_whales", False))

        # ── FILTRE MARKET CONTEXT ─────────────────
        if self.market_context:
            try:
                market_signal = self.market_context.get_market_signal()
                if not market_signal.get("should_alert", True):
                    return self._ignore(
                        f"MARCHÉ: {market_signal.get('reason', 'défavorable')}"
                    )
            except Exception as e:
                logger.debug(f"[DECISION] Market context error: {e}")

        # ── FILTRES ABSOLUS ───────────────────────
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

        if top10_pct > 85:
            return self._ignore(f"Top 10 trop concentré: {top10_pct:.0f}%")

        if market_cap > 10_000_000:
            return self._ignore(f"MC trop élevé: ${market_cap:,.0f}")

        # v6.4 : safety minimum
        if safety_score < 5.5:
            return self._ignore(
                f"Safety insuffisant: {safety_score:.1f}/10 < 5.5"
            )

        # v6.4 : liquidité minimum
        if liquidity == 0 and age_minutes > 8:
            return self._ignore(
                f"Liquidité $0 après {age_minutes:.0f}min"
            )

        if liquidity < 3_000 and age_minutes > 10:
            return self._ignore(
                f"Liquidité trop faible: ${liquidity:.0f}"
            )

        # Anti-spam
        if not self._check_antispam(address):
            return self._ignore("Anti-spam: déjà alerté récemment")

        # ── CONVICTION CHECK ──────────────────────
        conviction_count = 0
        conviction_reasons = []

        if alpha_count >= 1:
            conviction_count += 2
            conviction_reasons.append(f"{alpha_count} alpha wallet(s)")
        if has_twitter:
            conviction_count += 1
            conviction_reasons.append("signal Twitter")
        if has_whale:
            conviction_count += 1
            conviction_reasons.append("whale inflow")
        if has_critical:
            conviction_count += 1
            conviction_reasons.append("signal critique")
        if smart_count >= 3:
            conviction_count += 1
            conviction_reasons.append(f"{smart_count} smart signals")

        # ── TIER v6.4 ─────────────────────────────
        tier = self._get_tier(
            score, safety_score, smart_count, has_critical,
            conviction_count, alpha_count, liquidity, age_minutes
        )

        if tier == "IGNORE":
            return self._ignore(
                f"Score/safety/conviction insuffisants: "
                f"score={score:.1f} safety={safety_score:.1f} "
                f"conv={conviction_count}"
            )

        strategy   = self._get_strategy(market_cap)
        amount_eur = self._get_amount(tier)
        tp_levels  = strategy["tp_levels"]
        sl_pct     = strategy["sl_pct"]

        if tp_levels and amount_eur > 0:
            weighted_return = sum(
                tp["multiplier"] * (tp["sell_pct"] / 100)
                for tp in tp_levels
            )
            profit_pct = (weighted_return - 1) * 100
            profit_eur = round(
                amount_eur * weighted_return - amount_eur, 2
            )
        else:
            profit_pct = 0.0
            profit_eur = 0.0

        self._register_alert(address)

        conv_text = (
            ", ".join(conviction_reasons)
            if conviction_reasons else "aucun"
        )

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
                f"Safety {safety_score:.1f}/10 | "
                f"Conv {conviction_count}: {conv_text}"
            ),
            "conviction_count":   conviction_count,
            "conviction_reasons": conviction_reasons,
        }

    def _get_tier(
        self,
        score: float,
        safety_score: float,
        smart_count: int,
        has_critical: bool,
        conviction_count: int,
        alpha_count: int,
        liquidity: float,
        age_minutes: float,
    ) -> str:
        """
        v6.4 : Tiers basés sur score + safety + conviction
        """
        # ULTIMATE : score élevé + safety correct + liq visible + conviction
        if (
            score >= 8.5
            and safety_score >= 7.0
            and liquidity >= 8_000
            and conviction_count >= 1
        ):
            return "ULTIMATE"

        # STRONG : bon score + safety ok + conviction
        if (
            score >= 7.8
            and safety_score >= 6.5
            and (conviction_count >= 1 or smart_count >= 3)
            and liquidity >= 5_000
        ):
            return "STRONG"

        # GOOD : score correct + safety ok
        if (
            score >= 7.2
            and safety_score >= 6.0
            and (conviction_count >= 1 or smart_count >= 2)
            and liquidity >= 3_000
        ):
            return "GOOD"

        # NORMAL : très rare maintenant
        if (
            score >= 7.0
            and safety_score >= 6.0
            and conviction_count >= 1
            and liquidity >= 3_000
        ):
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
                f"[ANTISPAM] Limite horaire atteinte ({MAX_ALERTS_PER_HOUR}/h)"
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
            "conviction_count":    0,
            "conviction_reasons":  [],
        }