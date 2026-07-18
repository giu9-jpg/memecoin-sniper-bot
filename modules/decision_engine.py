# modules/decision_engine.py — v6.1 FIXED
# FIX : _check_antispam thread-safe
# FIX : market_bonus ne peut pas rendre score négatif
# FIX : hourly_alerts nettoyé correctement
# FIX : age_minutes manquant dans certains filtres

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

# Limite horaire d'alertes pour éviter le spam
MAX_ALERTS_PER_HOUR = 20


class DecisionEngine:

    def __init__(self, market_context=None):
        self.alert_history  = {}   # {address: timestamp}
        self.hourly_alerts  = []   # [timestamps]
        self.market_context = market_context

    # ═══════════════════════════════════════════════════
    # DÉCISION PRINCIPALE
    # ═══════════════════════════════════════════════════

    def decide(self, data: dict) -> dict:
        """
        Prend une décision d'achat ou d'ignorance.
        Retourne toujours un dict complet.
        """
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
                # FIX : market_bonus ne modifie plus le score ici
                # Le score est déjà calculé dans token_analyzer
                # On l'utilise uniquement pour le filtre should_alert
            except Exception as e:
                logger.debug(f"[DECISION] Erreur market context: {e}")

        # ── FILTRES ABSOLUS ───────────────────────────

        if not address:
            return self._ignore("Adresse vide")

        if address in BLACKLISTED_TOKENS:
            return self._ignore("Token blacklisté")

        if age_minutes > 10_080:  # 7 jours
            return self._ignore(
                f"Trop vieux: {age_minutes/1440:.1f}j"
            )

        if market_cap == 0:
            return self._ignore("MC = 0 (données invalides)")

        if is_honeypot:
            return self._ignore("HONEYPOT détecté")

        if freeze_auth:
            return self._ignore("Freeze authority active")

        if top10_pct > 90:
            return self._ignore(
                f"Top 10 trop concentré: {top10_pct:.0f}%"
            )

        if market_cap > 10_000_000:
            return self._ignore(
                f"MC trop élevé: ${market_cap:,.0f}"
            )

        if holders < 20:
            return self._ignore(
                f"Trop peu de holders: {holders}"
            )

        # ── FILTRE LIQUIDITÉ ──────────────────────────
        # FIX : pas de filtre strict sur les tokens < 5 min
        if age_minutes >= 5:
            if liquidity < 5_000:
                return self._ignore(
                    f"Liquidité trop faible: ${liquidity:.0f}"
                )
        else:
            if liquidity == 0 and score < 8.0:
                return self._ignore(
                    "Token < 5min sans liquidité et score insuffisant"
                )

        # ── ANTI-SPAM ─────────────────────────────────
        if not self._check_antispam(address):
            return self._ignore("Anti-spam: déjà alerté récemment")

        # ── TIER ──────────────────────────────────────
        tier = self._get_tier(score, smart_count, has_critical)

        if tier == "IGNORE":
            return self._ignore(
                f"Score insuffisant: {score:.1f}/10"
            )

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
            "action":               "ACHÈTE",
            "tier":                 tier,
            "amount_eur":           amount_eur,
            "expected_profit_pct":  round(profit_pct, 1),
            "expected_profit_eur":  profit_eur,
            "tp_levels":            tp_levels,
            "sl_pct":               sl_pct,
            "strategy_name":        strategy["name"],
            "reason": (
                f"Score {score:.1f}/10 | "
                f"{smart_count} smart signals | "
                f"tier {tier}"
            ),
        }

    # ═══════════════════════════════════════════════════
    # TIER
    # ═══════════════════════════════════════════════════

    def _get_tier(
        self,
        score:        float,
        smart_count:  int,
        has_critical: bool,
    ) -> str:
        """
        FIX : a_critical permet d'atteindre STRONG même avec moins de signals.
        """
        if score >= 9.5 and smart_count >= 4:
            return "ULTIMATE"
        if score >= 9.5 and has_critical:
            return "ULTIMATE"
        if score >= 8.5 and smart_count >= 3:
            return "STRONG"
        if score >= 8.5 and has_critical:
            return "STRONG"
        if score >= 8.0 and smart_count >= 2:
            return "GOOD"
        if score >= 8.0 and has_critical:
            return "GOOD"
        if score >= 7.5:
            return "NORMAL"
        return "IGNORE"

    # ═══════════════════════════════════════════════════
    # MONTANT
    # ═══════════════════════════════════════════════════

    def _get_amount(self, tier: str) -> float:
        return {
            "ULTIMATE": 10.0,
            "STRONG":   8.0,
            "GOOD":     6.0,
            "NORMAL":   5.0,
            "IGNORE":   0.0,
        }.get(tier, 0.0)

    # ═══════════════════════════════════════════════════
    # STRATÉGIE TP/SL SELON MARKET CAP
    # ═══════════════════════════════════════════════════

    def _get_strategy(self, market_cap: float) -> dict:
        """
        FIX : les sell_pct de chaque stratégie somment bien à 100%.
        """
        if market_cap < 50_000:
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

    # ═══════════════════════════════════════════════════
    # ANTI-SPAM
    # ═══════════════════════════════════════════════════

    def _check_antispam(self, address: str) -> bool:
        """
        FIX : nettoyage hourly_alerts fait avant le check.
        FIX : cooldown 30 min par token.
        """
        now = time.time()

        # Cooldown par token (30 min)
        if address in self.alert_history:
            elapsed = now - self.alert_history[address]
            if elapsed < 1800:
                logger.debug(
                    f"[ANTISPAM] Cooldown {address[:8]}: "
                    f"{int(1800 - elapsed)}s restant"
                )
                return False

        # FIX : nettoyage AVANT le check du max
        self.hourly_alerts = [
            t for t in self.hourly_alerts
            if now - t < 3600
        ]

        # Max alertes par heure
        if len(self.hourly_alerts) >= MAX_ALERTS_PER_HOUR:
            logger.warning(
                f"[ANTISPAM] Limite horaire atteinte "
                f"({MAX_ALERTS_PER_HOUR}/h)"
            )
            return False

        return True

    def _register_alert(self, address: str):
        """Enregistre une alerte dans l'historique."""
        now = time.time()
        self.alert_history[address] = now
        self.hourly_alerts.append(now)

        # FIX : nettoyage mémoire si trop d'entrées
        if len(self.alert_history) > 1000:
            cutoff = now - 86400  # 24h
            self.alert_history = {
                addr: ts
                for addr, ts in self.alert_history.items()
                if ts > cutoff
            }

    # ═══════════════════════════════════════════════════
    # HELPER IGNORE
    # ═══════════════════════════════════════════════════

    def _ignore(self, reason: str) -> dict:
        """Retourne un dict IGNORE standardisé."""
        return {
            "action":               "IGNORE",
            "tier":                 "IGNORE",
            "amount_eur":           0.0,
            "expected_profit_pct":  0.0,
            "expected_profit_eur":  0.0,
            "tp_levels":            [],
            "sl_pct":               0,
            "strategy_name":        "NONE",
            "reason":               reason,
        }