# modules/chart_screenshot.py v1.0
"""
Chart Screenshot Generator
Génère des URLs d'images de charts pour les alertes Telegram.

Sources d'images utilisées :
  1. DexScreener embed (chart intégré)
  2. GeckoTerminal API (mini charts)
  3. Fallback : simple lien vers le chart
"""

import aiohttp
from utils.logger import get_logger

logger = get_logger("chart_screenshot")


class ChartScreenshot:

    def __init__(self):
        self.session = None

    async def start(self):
        """Initialise la session HTTP"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        logger.info("📸 ChartScreenshot v1.0 : ACTIF")

    async def stop(self):
        """Ferme la session"""
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("📸 ChartScreenshot arrêté")

    async def get_chart_url(
        self,
        mint: str,
        source: str = "auto",
    ) -> str:
        """
        Retourne une URL d'image du chart pour le token.

        Args:
          mint   : adresse du token
          source : "dexscreener" | "geckoterminal" | "auto"

        Returns:
          URL de l'image du chart (ou None si échec)
        """
        try:
            # Essaie DexScreener d'abord
            if source in ("auto", "dexscreener"):
                url = await self._get_dexscreener_chart(mint)
                if url:
                    return url

            # Fallback GeckoTerminal
            if source in ("auto", "geckoterminal"):
                url = await self._get_geckoterminal_chart(mint)
                if url:
                    return url

            return None

        except Exception as e:
            logger.debug(f"Chart screenshot error : {e}")
            return None

    async def _get_dexscreener_chart(self, mint: str) -> str:
        """
        Récupère l'URL de l'image du chart depuis DexScreener.
        DexScreener génère automatiquement des OG images pour chaque token.
        """
        try:
            # DexScreener génère des OpenGraph images automatiquement
            # Format : https://dexscreener.com/solana/{pair_address}
            # OG image : https://dexscreener.com/api/og/pair/solana/{pair}

            # D'abord on récupère l'adresse du pair
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            pairs = data.get("pairs") or []
            if not pairs:
                return None

            pair_address = pairs[0].get("pairAddress")
            if not pair_address:
                return None

            # URL de l'image OpenGraph de DexScreener
            image_url = (
                f"https://dexscreener.com/api/og/pair/solana/"
                f"{pair_address}"
            )

            return image_url

        except Exception as e:
            logger.debug(f"DexScreener chart error : {e}")
            return None

    async def _get_geckoterminal_chart(self, mint: str) -> str:
        """
        Récupère l'URL de l'image du chart depuis GeckoTerminal.
        API gratuite : https://www.geckoterminal.com/
        """
        try:
            # GeckoTerminal API pour trouver le pool
            url = (
                f"https://api.geckoterminal.com/api/v2/networks/solana/"
                f"tokens/{mint}/pools"
            )
            headers = {"Accept": "application/json"}

            async with self.session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            pools = data.get("data", [])
            if not pools:
                return None

            pool_address = pools[0].get("attributes", {}).get("address")
            if not pool_address:
                return None

            # GeckoTerminal image du chart
            image_url = (
                f"https://api.geckoterminal.com/api/v2/networks/solana/"
                f"pools/{pool_address}/ohlcv/hour?limit=24"
            )

            # On retourne plutôt l'URL de la page qui a OG image
            page_url = (
                f"https://www.geckoterminal.com/solana/pools/"
                f"{pool_address}"
            )

            return page_url

        except Exception as e:
            logger.debug(f"GeckoTerminal chart error : {e}")
            return None

    async def get_chart_data_summary(self, mint: str) -> dict:
        """
        Récupère un résumé textuel du chart (fallback si pas d'image).
        Utile pour construire un mini-chart ASCII dans le message.
        """
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()

            pairs = data.get("pairs") or []
            if not pairs:
                return {}

            pair = pairs[0]
            price_change = pair.get("priceChange", {})

            return {
                "5m":  price_change.get("m5", 0),
                "1h":  price_change.get("h1", 0),
                "6h":  price_change.get("h6", 0),
                "24h": price_change.get("h24", 0),
            }

        except Exception as e:
            logger.debug(f"Chart summary error : {e}")
            return {}

    def build_ascii_chart(self, changes: dict) -> str:
        """
        Construit un mini-chart ASCII avec les variations de prix.

        Exemple :
          5m : ▁▁▁▁▁▁▁▁ +2%
          1h : ▂▂▂▂▂▂▂▂ +15%
          6h : ▄▄▄▄▄▄▄▄ +45%
         24h : ██████████ +250%
        """
        if not changes:
            return ""

        def bar(pct: float) -> str:
            """Retourne une barre ASCII selon le %"""
            abs_pct = abs(pct)
            if abs_pct < 5:
                return "▁"
            elif abs_pct < 20:
                return "▂"
            elif abs_pct < 50:
                return "▃"
            elif abs_pct < 100:
                return "▄"
            elif abs_pct < 200:
                return "▅"
            elif abs_pct < 500:
                return "▆"
            elif abs_pct < 1000:
                return "▇"
            else:
                return "█"

        lines = []
        for label in ["5m", "1h", "6h", "24h"]:
            pct = changes.get(label, 0) or 0
            b = bar(pct) * 8
            arrow = "📈" if pct >= 0 else "📉"
            lines.append(
                f"  {label:>4} {b} {arrow} {pct:+.1f}%"
            )

        return "\n".join(lines)