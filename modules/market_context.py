# modules/market_context.py — v4.0 FIXED
# FIX : close() ajouté
# FIX : valeurs par défaut si API indisponible
# FIX : fear & greed index via API alternative
# FIX : get_market_signal() ne crashe plus sans données

import aiohttp
import time
from utils.logger import logger


# Seuils pour les régimes de marché
BTC_BULLISH_THRESHOLD  =  3.0   # BTC +3% en 24h → BULLISH
BTC_BEARISH_THRESHOLD  = -5.0   # BTC -5% en 24h → BEARISH
SOL_BULLISH_THRESHOLD  =  5.0
SOL_BEARISH_THRESHOLD  = -8.0
FG_BULLISH_THRESHOLD   = 60     # Fear & Greed > 60 → Greed
FG_BEARISH_THRESHOLD   = 30     # Fear & Greed < 30 → Fear


class MarketContext:

    def __init__(self):
        self.session        = None
        self.last_update    = 0
        self.update_interval = 180   # 3 min

        # Données marché avec valeurs par défaut sûres
        self.btc_change_24h = 0.0
        self.sol_change_24h = 0.0
        self.fear_greed     = 50     # Neutre par défaut
        self.regime         = "NEUTRAL"
        self.should_alert   = True
        self.last_error     = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # FETCH DONNÉES MARCHÉ
    # ═══════════════════════════════════════════════════

    async def fetch_market_data(self):
        """
        Récupère BTC, SOL et Fear & Greed.
        FIX : ne crashe pas si une API est indisponible.
        """
        try:
            await self._fetch_prices()
        except Exception as e:
            logger.warning(f"[MARKET] Erreur prix : {e}")

        try:
            await self._fetch_fear_greed()
        except Exception as e:
            logger.warning(f"[MARKET] Erreur F&G : {e}")

        self.last_update = time.time()
        self._update_regime()

    async def _fetch_prices(self):
        """Récupère BTC et SOL via CoinGecko."""
        try:
            session = await self._get_session()
            url     = (
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=bitcoin,solana"
                "&vs_currencies=usd"
                "&include_24hr_change=true"
            )
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 429:
                    logger.warning("[MARKET] CoinGecko rate limit")
                    return
                if resp.status != 200:
                    logger.warning(
                        f"[MARKET] CoinGecko status {resp.status}"
                    )
                    return

                data = await resp.json()

                self.btc_change_24h = float(
                    data.get("bitcoin", {})
                        .get("usd_24h_change", 0) or 0
                )
                self.sol_change_24h = float(
                    data.get("solana", {})
                        .get("usd_24h_change", 0) or 0
                )

        except Exception as e:
            logger.debug(f"[MARKET] _fetch_prices: {e}")

    async def _fetch_fear_greed(self):
        """Récupère le Fear & Greed Index."""
        try:
            session = await self._get_session()
            url     = "https://api.alternative.me/fng/?limit=1"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                fg_value = (
                    data.get("data", [{}])[0]
                        .get("value", "50")
                )
                self.fear_greed = int(fg_value)

        except Exception as e:
            logger.debug(f"[MARKET] _fetch_fear_greed: {e}")

    # ═══════════════════════════════════════════════════
    # RÉGIME DE MARCHÉ
    # ═══════════════════════════════════════════════════

    def _update_regime(self):
        """
        Calcule le régime de marché.
        FIX : logique claire et documentée.
        """
        btc = self.btc_change_24h
        sol = self.sol_change_24h
        fg  = self.fear_greed

        bullish_score = 0
        bearish_score = 0

        # BTC
        if btc >= BTC_BULLISH_THRESHOLD:
            bullish_score += 2
        elif btc <= BTC_BEARISH_THRESHOLD:
            bearish_score += 2

        # SOL
        if sol >= SOL_BULLISH_THRESHOLD:
            bullish_score += 2
        elif sol <= SOL_BEARISH_THRESHOLD:
            bearish_score += 2

        # Fear & Greed
        if fg >= FG_BULLISH_THRESHOLD:
            bullish_score += 1
        elif fg <= FG_BEARISH_THRESHOLD:
            bearish_score += 1

        # Décision
        if bullish_score >= 3:
            self.regime      = "BULLISH"
            self.should_alert = True
        elif bearish_score >= 4:
            # Très bearish : on réduit les alertes
            self.regime       = "BEARISH"
            self.should_alert = False
        elif bearish_score >= 2:
            self.regime       = "BEARISH"
            self.should_alert = True   # On alerte quand même
        else:
            self.regime       = "NEUTRAL"
            self.should_alert = True

        logger.debug(
            f"[MARKET] Régime: {self.regime} | "
            f"Bullish:{bullish_score} Bearish:{bearish_score}"
        )

    # ═══════════════════════════════════════════════════
    # SIGNAL PUBLIC
    # ═══════════════════════════════════════════════════

    def get_market_signal(self) -> dict:
        """
        Retourne le signal marché complet.
        FIX : toujours retourner un dict valide.
        FIX : bonus selon régime.
        """
        # Bonus/malus de score selon le régime
        bonus_map = {
            "BULLISH": 0.5,
            "NEUTRAL": 0.0,
            "BEARISH": -1.0,
        }
        bonus = bonus_map.get(self.regime, 0.0)

        # Raison si on n'alerte pas
        reason = ""
        if not self.should_alert:
            reason = (
                f"Marché trop bearish "
                f"(BTC {self.btc_change_24h:+.1f}% | "
                f"FG {self.fear_greed})"
            )

        return {
            "regime":          self.regime,
            "should_alert":    self.should_alert,
            "btc_change_24h":  self.btc_change_24h,
            "sol_change_24h":  self.sol_change_24h,
            "fear_greed":      self.fear_greed,
            "bonus":           bonus,
            "reason":          reason,
            "last_update":     self.last_update,
        }

    def is_stale(self) -> bool:
        """Retourne True si les données ont plus de 10 min."""
        return time.time() - self.last_update > 600

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()