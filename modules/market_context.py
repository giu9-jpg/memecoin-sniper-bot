# modules/market_context.py — v6.0
# Analyse le contexte macro (BTC + SOL) pour filtrer les alertes

import time
import aiohttp
from utils.logger import logger


class MarketContext:

    def __init__(self):
        self.session         = None
        self.btc_price       = 0
        self.btc_change_1h   = 0
        self.btc_change_24h  = 0
        self.sol_price       = 0
        self.sol_change_1h   = 0
        self.sol_change_24h  = 0
        self.fear_greed      = 50    # neutre par défaut
        self.last_fetch      = 0
        self.cache_duration  = 180   # 3 minutes de cache

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # FETCH DONNÉES MARCHÉ
    # ═══════════════════════════════════════════════════
    async def fetch_market_data(self):
        """Récupère BTC, SOL et Fear & Greed Index."""
        now = time.time()
        if now - self.last_fetch < self.cache_duration:
            return

        try:
            await self._fetch_btc_sol()
            await self._fetch_fear_greed()
            self.last_fetch = now
        except Exception as e:
            logger.debug(f"[MARKET] Erreur fetch: {e}")

    async def _fetch_btc_sol(self):
        """Récupère les prix et variations BTC + SOL."""
        try:
            session = await self._get_session()
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids":                 "bitcoin,solana",
                "vs_currencies":       "usd",
                "include_24hr_change": "true",
            }
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    btc = data.get("bitcoin", {})
                    self.btc_price      = btc.get("usd", 0)
                    self.btc_change_24h = btc.get("usd_24h_change", 0)

                    sol = data.get("solana", {})
                    self.sol_price      = sol.get("usd", 0)
                    self.sol_change_24h = sol.get("usd_24h_change", 0)

                    # Approximation 1h à partir du 24h
                    self.btc_change_1h = self.btc_change_24h / 24
                    self.sol_change_1h = self.sol_change_24h / 24

        except Exception as e:
            logger.debug(f"[MARKET] Erreur BTC/SOL: {e}")

    async def _fetch_fear_greed(self):
        """Fear & Greed Index (0-100)."""
        try:
            session = await self._get_session()
            url = "https://api.alternative.me/fng/"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    value = data.get("data", [{}])[0].get("value", 50)
                    self.fear_greed = int(value)
        except Exception as e:
            logger.debug(f"[MARKET] Erreur FG: {e}")

    # ═══════════════════════════════════════════════════
    # ANALYSE DU CONTEXTE
    # ═══════════════════════════════════════════════════
    def get_market_signal(self) -> dict:
        """
        Retourne le signal marché global.
        Utilisé pour bloquer/autoriser les alertes memecoins.
        """
        # ── Régime de marché ──────────────────────────
        regime = self._get_regime()

        # ── Décision globale ──────────────────────────
        should_alert = True
        reason       = "Contexte favorable"
        bonus        = 0.0

        # BULLISH — pousser les alertes
        if self.btc_change_24h >= 5 and self.sol_change_24h >= 5:
            bonus = 1.0
            reason = "🚀 BTC + SOL en forte hausse"

        elif self.btc_change_24h >= 2 and self.sol_change_24h >= 2:
            bonus = 0.5
            reason = "📈 Marché haussier"

        # NEUTRE — laisser passer
        elif abs(self.btc_change_24h) < 2 and abs(self.sol_change_24h) < 3:
            bonus = 0.0
            reason = "😐 Marché stable"

        # BEARISH LÉGER — filtrer plus strict
        elif self.btc_change_24h < -2 or self.sol_change_24h < -3:
            bonus = -1.0
            reason = f"⚠️ BTC {self.btc_change_24h:+.1f}% | SOL {self.sol_change_24h:+.1f}%"

        # BEARISH FORT — BLOQUER
        if self.btc_change_24h < -5 or self.sol_change_24h < -7:
            should_alert = False
            reason = f"🔴 CRASH BTC {self.btc_change_24h:+.1f}% / SOL {self.sol_change_24h:+.1f}%"

        # Fear & Greed extrême
        if self.fear_greed < 20:
            should_alert = False
            reason = f"😱 Extreme Fear ({self.fear_greed}) → pas de trades"

        return {
            "should_alert":     should_alert,
            "reason":           reason,
            "bonus":            bonus,
            "regime":           regime,
            "btc_change_24h":   round(self.btc_change_24h, 2),
            "sol_change_24h":   round(self.sol_change_24h, 2),
            "fear_greed":       self.fear_greed,
        }

    def _get_regime(self) -> str:
        """Régime de marché actuel."""
        if self.btc_change_24h >= 3 and self.sol_change_24h >= 3:
            return "BULLISH"
        elif self.btc_change_24h <= -3 or self.sol_change_24h <= -5:
            return "BEARISH"
        else:
            return "NEUTRAL"

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()