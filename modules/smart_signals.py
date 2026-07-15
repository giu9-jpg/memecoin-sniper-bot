# modules/smart_signals.py — v5.0
# Détection ULTRA-AVANCÉE des signaux pre-pump

import time
import aiohttp
from utils.logger import logger


# ═══════════════════════════════════════════════════════
# TRACKER — Historique des tokens dans le temps
# ═══════════════════════════════════════════════════════
class TokenTracker:
    """Suit l'évolution des tokens dans le temps."""

    def __init__(self):
        self.tokens = {}

    def update(self, address: str, data: dict):
        """Ajoute un snapshot du token."""
        now = time.time()

        if address not in self.tokens:
            self.tokens[address] = []

        self.tokens[address].append({
            "time":      now,
            "price":     data.get("price_usd", 0),
            "mc":        data.get("market_cap", 0),
            "liquidity": data.get("liquidity", 0),
            "volume":    data.get("volume_1h", 0),
            "holders":   data.get("holders", 0),
            "score":     data.get("score", 0),
        })

        # Garder seulement les 60 dernières minutes
        cutoff = now - 3600
        self.tokens[address] = [
            e for e in self.tokens[address]
            if e["time"] > cutoff
        ]

        # Limite mémoire : max 500 tokens suivis
        if len(self.tokens) > 500:
            oldest = sorted(
                self.tokens.items(),
                key=lambda x: x[1][-1]["time"]
            )[:100]
            for addr, _ in oldest:
                del self.tokens[addr]

    def get_history(self, address: str) -> list:
        """Retourne l'historique d'un token."""
        return self.tokens.get(address, [])


# ═══════════════════════════════════════════════════════
# DÉTECTEUR PRINCIPAL — 8 SMART SIGNALS
# ═══════════════════════════════════════════════════════
class SmartSignalDetector:

    def __init__(self):
        self.tracker        = TokenTracker()
        self.btc_price      = 0
        self.btc_change     = 0
        self.last_btc_fetch = 0
        self.session        = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # SIGNAL 1 — SCORE ÉVOLUTIF
    # Le score du token monte dans le temps → signal fort
    # ═══════════════════════════════════════════════════
    def detect_score_evolution(self, address: str, current_score: float):
        history = self.tracker.get_history(address)
        if len(history) < 3:
            return None

        # Score il y a 10 minutes
        ten_min_ago = time.time() - 600
        old_scores  = [
            h["score"] for h in history
            if h["time"] <= ten_min_ago
        ]
        if not old_scores:
            return None

        old_score = max(old_scores)
        diff      = current_score - old_score

        if diff >= 2.0:
            return {
                "type":     "SCORE_RISING",
                "emoji":    "📈",
                "message":  f"Score en HAUSSE : {old_score:.1f} → {current_score:.1f}",
                "priority": "HIGH",
                "bonus":    2.0,
            }
        elif diff <= -2.0:
            return {
                "type":     "SCORE_FALLING",
                "emoji":    "📉",
                "message":  f"Score en BAISSE : {old_score:.1f} → {current_score:.1f}",
                "priority": "WARNING",
                "bonus":    -1.5,
            }
        return None

    # ═══════════════════════════════════════════════════
    # SIGNAL 2 — LIQUIDITY GROWTH
    # La liquidité augmente → de l'argent entre dans le token
    # ═══════════════════════════════════════════════════
    def detect_liquidity_growth(self, address: str, current_liq: float):
        history = self.tracker.get_history(address)
        if len(history) < 3:
            return None

        # Liquidité il y a 15 minutes
        fifteen_min = time.time() - 900
        old_liqs    = [
            h["liquidity"] for h in history
            if h["time"] <= fifteen_min and h["liquidity"] > 0
        ]
        if not old_liqs:
            return None

        old_liq = min(old_liqs)
        if old_liq == 0:
            return None

        growth = ((current_liq - old_liq) / old_liq) * 100

        if growth >= 50:
            return {
                "type":     "LIQ_EXPLOSION",
                "emoji":    "💧",
                "message":  f"Liquidité EXPLOSE : +{growth:.0f}%",
                "priority": "HIGH",
                "bonus":    2.5,
            }
        elif growth >= 25:
            return {
                "type":     "LIQ_GROWING",
                "emoji":    "💧",
                "message":  f"Liquidité en hausse : +{growth:.0f}%",
                "priority": "MEDIUM",
                "bonus":    1.5,
            }
        elif growth <= -30:
            return {
                "type":     "LIQ_LEAVING",
                "emoji":    "🚨",
                "message":  f"LIQUIDITÉ PART : {growth:.0f}% ← RUG?",
                "priority": "CRITICAL",
                "bonus":    -5.0,
            }
        return None

    # ═══════════════════════════════════════════════════
    # SIGNAL 3 — HOLDER EXPLOSION
    # Les holders arrivent en masse → token qui devient viral
    # ═══════════════════════════════════════════════════
    def detect_holder_explosion(self, address: str, current_holders: int):
        history = self.tracker.get_history(address)
        if len(history) < 3:
            return None

        # Holders il y a 10 minutes
        ten_min      = time.time() - 600
        old_holders_data = [
            h["holders"] for h in history
            if h["time"] <= ten_min and h["holders"] > 0
        ]
        if not old_holders_data:
            return None

        old_holders = min(old_holders_data)
        if old_holders == 0:
            return None

        new  = current_holders - old_holders
        rate = new / 10  # holders par minute

        if rate >= 20:
            return {
                "type":     "HOLDER_VIRAL",
                "emoji":    "🔥",
                "message":  f"VIRAL : +{new} holders en 10min",
                "priority": "HIGH",
                "bonus":    3.0,
            }
        elif rate >= 10:
            return {
                "type":     "HOLDER_GROWING",
                "emoji":    "📈",
                "message":  f"Croissance holders : +{new} en 10min",
                "priority": "MEDIUM",
                "bonus":    1.5,
            }
        return None

    # ═══════════════════════════════════════════════════
    # SIGNAL 4 — SMART MONEY
    # Accumulation régulière et cohérente = argent intelligent
    # ═══════════════════════════════════════════════════
    def detect_smart_money(self, data: dict):
        txns_5m  = data.get("txns_5m", {})
        txns_1h  = data.get("txns_1h", {})

        buys_5m  = txns_5m.get("buys", 0)
        sells_5m = txns_5m.get("sells", 1)
        buys_1h  = txns_1h.get("buys", 0)
        sells_1h = txns_1h.get("sells", 1)

        ratio_5m = buys_5m / max(sells_5m, 1)
        ratio_1h = buys_1h / max(sells_1h, 1)

        total_5m = buys_5m + sells_5m
        total_1h = buys_1h + sells_1h

        # Accumulation régulière sur les deux TF + cohérence
        if (total_5m >= 30
                and total_1h >= 100
                and ratio_5m >= 2
                and ratio_1h >= 1.5
                and abs(ratio_5m - ratio_1h) < 1.5):
            return {
                "type":     "SMART_MONEY",
                "emoji":    "🧠",
                "message":  "SMART MONEY : accumulation régulière",
                "priority": "HIGH",
                "bonus":    2.5,
            }
        return None

    # ═══════════════════════════════════════════════════
    # SIGNAL 5 — COORDINATED BUYING
    # Beaucoup d'achats similaires en même temps = coordonné
    # ═══════════════════════════════════════════════════
    def detect_coordinated_buying(self, data: dict):
        txns_5m   = data.get("txns_5m", {})
        buys_5m   = txns_5m.get("buys", 0)
        volume_5m = data.get("volume_5m", 0)

        if buys_5m >= 50 and volume_5m >= 5_000:
            avg = volume_5m / buys_5m
            # Achats de taille similaire (ni trop petit ni trop gros)
            if 50 < avg < 500:
                return {
                    "type":     "COORDINATED_BUY",
                    "emoji":    "🎯",
                    "message":  f"ACHATS COORDONNÉS : {buys_5m} en 5min",
                    "priority": "HIGH",
                    "bonus":    2.5,
                }
        return None

    # ═══════════════════════════════════════════════════
    # SIGNAL 6 — STEALTH ACCUMULATION
    # Volume explose MAIS le prix ne bouge pas encore
    # = quelqu'un accumule discrètement AVANT le pump
    # ═══════════════════════════════════════════════════
    def detect_momentum_divergence(self, data: dict):
        price_change_1h = data.get("price_change_1h", 0)
        vol_accel       = data.get("vol_acceleration", 1)
        ratio_5m        = data.get("ratio_buy_5m", 1)

        if (abs(price_change_1h) < 8
                and vol_accel >= 2.5
                and ratio_5m >= 2):
            return {
                "type":     "STEALTH_ACCUMULATION",
                "emoji":    "🤫",
                "message":  f"ACCUMULATION FURTIVE : vol x{vol_accel:.1f}",
                "priority": "CRITICAL",
                "bonus":    3.5,
            }
        return None

    # ═══════════════════════════════════════════════════
    # SIGNAL 7 — BTC CORRELATION
    # BTC en hausse = bon contexte pour les memecoins
    # ═══════════════════════════════════════════════════
    async def get_btc_context(self):
        """Récupère le prix et la variation BTC."""
        now = time.time()

        # Cache 5 minutes
        if now - self.last_btc_fetch < 300:
            return self.btc_price, self.btc_change

        try:
            session = await self._get_session()
            url     = "https://api.coingecko.com/api/v3/simple/price"
            params  = {
                "ids":                 "bitcoin",
                "vs_currencies":       "usd",
                "include_24hr_change": "true",
            }
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data            = await resp.json()
                    btc             = data.get("bitcoin", {})
                    self.btc_price  = btc.get("usd", 0)
                    self.btc_change = btc.get("usd_24h_change", 0)
                    self.last_btc_fetch = now

        except Exception as e:
            logger.debug(f"[BTC] Erreur fetch: {e}")

        return self.btc_price, self.btc_change

    def get_btc_bonus(self, btc_change: float):
        """Signal basé sur la tendance BTC."""
        if btc_change >= 5:
            return {
                "type":     "BTC_BULLISH",
                "emoji":    "🚀",
                "message":  f"BTC EN HAUSSE : +{btc_change:.1f}%",
                "priority": "HIGH",
                "bonus":    1.5,
            }
        elif btc_change >= 2:
            return {
                "type":     "BTC_POSITIVE",
                "emoji":    "📈",
                "message":  f"BTC positif : +{btc_change:.1f}%",
                "priority": "LOW",
                "bonus":    0.5,
            }
        elif btc_change <= -5:
            return {
                "type":     "BTC_BEARISH",
                "emoji":    "🔴",
                "message":  f"BTC en BAISSE : {btc_change:.1f}%",
                "priority": "WARNING",
                "bonus":    -1.5,
            }
        return None

    # ═══════════════════════════════════════════════════
    # SIGNAL 8 — WHALE ENTRY
    # Gros achats détectés = baleine qui entre
    # ═══════════════════════════════════════════════════
    def detect_whale_entry(self, data: dict):
        volume_5m = data.get("volume_5m", 0)
        txns_5m   = data.get("txns_5m", {})
        buys_5m   = txns_5m.get("buys", 1)

        if buys_5m > 0 and volume_5m > 0:
            avg_buy = volume_5m / buys_5m

            if avg_buy >= 3_000:
                return {
                    "type":     "WHALE_ENTRY",
                    "emoji":    "🐋",
                    "message":  f"BALEINE : achats de ${avg_buy:,.0f}",
                    "priority": "CRITICAL",
                    "bonus":    3.0,
                }
            elif avg_buy >= 1_000:
                return {
                    "type":     "BIG_BUYER",
                    "emoji":    "💰",
                    "message":  f"Gros acheteur : ${avg_buy:,.0f}/tx",
                    "priority": "HIGH",
                    "bonus":    1.5,
                }
        return None

    # ═══════════════════════════════════════════════════
    # ANALYSE COMPLÈTE — Lance les 8 signaux
    # ═══════════════════════════════════════════════════
    async def analyze_all_signals(self, address: str, data: dict) -> dict:
        """
        Lance tous les détecteurs et retourne le résultat consolidé.
        """
        # Mise à jour de l'historique
        self.tracker.update(address, data)

        signals     = []
        total_bonus = 0.0

        # ── 7 détecteurs synchrones ──────────────────
        detectors = [
            self.detect_score_evolution(address, data.get("score", 0)),
            self.detect_liquidity_growth(address, data.get("liquidity", 0)),
            self.detect_holder_explosion(address, data.get("holders", 0)),
            self.detect_smart_money(data),
            self.detect_coordinated_buying(data),
            self.detect_momentum_divergence(data),
            self.detect_whale_entry(data),
        ]

        for signal in detectors:
            if signal is not None:
                signals.append(signal)
                total_bonus += signal.get("bonus", 0)

        # ── Signal BTC (async) ───────────────────────
        _, btc_change = await self.get_btc_context()
        btc_signal    = self.get_btc_bonus(btc_change)
        if btc_signal:
            signals.append(btc_signal)
            total_bonus += btc_signal.get("bonus", 0)

        # ── Résultat consolidé ───────────────────────
        return {
            "signals":      signals,
            "total_bonus":  round(total_bonus, 2),
            "signal_count": len(signals),
            "has_critical": any(
                s.get("priority") == "CRITICAL"
                for s in signals
            ),
        }