# modules/raydium_monitor.py v1.0
"""
Détecte les nouveaux tokens sur Raydium / Orca
via DexScreener + Birdeye APIs
Complète le pump_fun_monitor existant
"""

import asyncio
import aiohttp
import time
from utils.logger import get_logger

logger = get_logger("raydium_monitor")

DEXSCREENER_NEW = "https://api.dexscreener.com/token-profiles/latest/v1"
BIRDEYE_NEW     = "https://public-api.birdeye.so/defi/v2/tokens/new_listing"
MIN_LIQUIDITY   = 1_000   # $1K minimum


class RadyiumMonitor:

    def __init__(self):
        self.session       = None
        self.seen_tokens   = set()
        self.scan_interval = 30
        self._running      = False
        self.tokens_found  = 0

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=12)
        )
        self._running = True
        logger.info("✅ RadyiumMonitor démarré (DexScreener + Birdeye)")

    async def stop(self):
        self._running = False
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info(
            f"🛑 RadyiumMonitor arrêté "
            f"({self.tokens_found} tokens trouvés)"
        )

    async def get_new_tokens(self) -> list:
        """
        Scanne les 2 sources en parallèle.
        Retourne uniquement les nouveaux tokens pas encore vus.
        """
        results = await asyncio.gather(
            self._scan_dexscreener(),
            self._scan_birdeye(),
            return_exceptions=True
        )

        all_tokens = []
        for r in results:
            if isinstance(r, list):
                all_tokens.extend(r)

        # Dédupliquer
        new_tokens = []
        seen_now   = set()

        for token in all_tokens:
            mint = token.get("mint", "")
            if not mint:
                continue
            if mint in self.seen_tokens:
                continue
            if mint in seen_now:
                continue
            seen_now.add(mint)
            self.seen_tokens.add(mint)
            new_tokens.append(token)

        # Nettoyer le cache si trop grand
        if len(self.seen_tokens) > 5000:
            old = list(self.seen_tokens)[:2000]
            for m in old:
                self.seen_tokens.discard(m)

        if new_tokens:
            self.tokens_found += len(new_tokens)
            logger.info(
                f"🆕 {len(new_tokens)} nouveaux tokens multi-DEX "
                f"(total: {self.tokens_found})"
            )

        return new_tokens

    async def _scan_dexscreener(self) -> list:
        """
        Nouveaux tokens via DexScreener token profiles.
        API publique, pas de clé requise.
        """
        try:
            async with self.session.get(DEXSCREENER_NEW) as resp:
                if resp.status != 200:
                    return []

                items = await resp.json()
                if not isinstance(items, list):
                    return []

                results = []
                for item in items:
                    # Solana seulement
                    if item.get("chainId") != "solana":
                        continue

                    mint = item.get("tokenAddress", "")
                    if not mint or len(mint) < 20:
                        continue

                    liq = item.get("totalAmount", 0) or 0
                    if liq < MIN_LIQUIDITY:
                        continue

                    results.append({
                        "mint":        mint,
                        "name":        item.get("header", "Unknown"),
                        "symbol":      item.get("description", "?")[:10],
                        "liquidity":   liq,
                        "source":      "dexscreener_new",
                        "age_minutes": 0,
                        # Champs compatibles avec le pipeline existant
                        "address":     mint,
                    })

                logger.debug(
                    f"DexScreener: {len(results)} tokens filtrés"
                )
                return results

        except Exception as e:
            logger.debug(f"DexScreener scan error: {e}")
            return []

    async def _scan_birdeye(self) -> list:
        """
        Nouveaux tokens via Birdeye.
        API publique (limite ~1000 req/jour sans clé).
        """
        try:
            params = {
                "sort_by":   "created_at",
                "sort_type": "desc",
                "offset":    0,
                "limit":     30,
            }
            headers = {"accept": "application/json"}

            async with self.session.get(
                BIRDEYE_NEW,
                params=params,
                headers=headers
            ) as resp:
                if resp.status != 200:
                    return []

                data   = await resp.json()
                tokens = data.get("data", {}).get("items", []) or []
                results = []

                for t in tokens:
                    mint = t.get("address", "")
                    liq  = t.get("liquidity", 0) or 0

                    if not mint or liq < MIN_LIQUIDITY:
                        continue

                    created = t.get("createdAt", 0) or 0
                    age_min = 0
                    if created:
                        age_min = round(
                            (time.time() - created) / 60, 1
                        )

                    results.append({
                        "mint":        mint,
                        "name":        t.get("name", "Unknown"),
                        "symbol":      t.get("symbol", "?"),
                        "liquidity":   liq,
                        "source":      "birdeye",
                        "age_minutes": age_min,
                        # Champs compatibles avec le pipeline existant
                        "address":     mint,
                    })

                logger.debug(f"Birdeye: {len(results)} tokens filtrés")
                return results

        except Exception as e:
            logger.debug(f"Birdeye scan error: {e}")
            return []

    async def monitor_loop(self, callback) -> None:
        """
        Boucle principale.
        Appelle callback(token_data) pour chaque nouveau token.
        """
        logger.info("🔍 RadyiumMonitor boucle démarrée")

        while self._running:
            try:
                new_tokens = await self.get_new_tokens()

                for token in new_tokens:
                    try:
                        await callback(token)
                    except Exception as e:
                        logger.error(
                            f"Callback error | "
                            f"{token.get('name', '?')}: {e}"
                        )

            except asyncio.CancelledError:
                logger.info("RadyiumMonitor annulé")
                break

            except Exception as e:
                logger.error(f"Erreur boucle Raydium: {e}")

            await asyncio.sleep(self.scan_interval)