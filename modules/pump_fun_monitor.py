# modules/pump_fun_monitor.py — v2.2
# Polling DexScreener (backup du WebSocket)

import aiohttp
import asyncio
import time
from utils.logger import logger

DEXSCREENER_SEARCH = (
    "https://api.dexscreener.com/latest/dex/search?q=solana"
)
DEXSCREENER_NEW = (
    "https://api.dexscreener.com/token-profiles/latest/v1"
)


class PumpFunMonitor:

    def __init__(self):
        self.session     = None
        self.seen_tokens = set()
        logger.info("[POLLING] PumpFunMonitor initialisé")

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ── MÉTHODE PRINCIPALE ───────────────────────────────
    async def get_new_tokens(self) -> list:
        """
        Récupère les nouveaux tokens Solana via DexScreener.
        Retourne une liste de tokens non encore vus.
        """
        try:
            tokens = await self._fetch_new_tokens()
            if not tokens:
                return []

            # Filtre les tokens déjà vus
            new_tokens = []
            for token in tokens:
                address = (
                    token.get("tokenAddress")
                    or token.get("address")
                    or token.get("baseToken", {}).get("address", "")
                )
                if not address:
                    continue
                if address.startswith("0x"):
                    continue
                if address in self.seen_tokens:
                    continue

                self.seen_tokens.add(address)
                new_tokens.append(token)

            # Nettoyage mémoire
            if len(self.seen_tokens) > 5000:
                self.seen_tokens = set(
                    list(self.seen_tokens)[-2000:]
                )

            if new_tokens:
                logger.info(
                    f"[POLLING] {len(new_tokens)} nouveau(x) token(s)"
                )

            return new_tokens

        except Exception as e:
            logger.error(f"[POLLING] Erreur get_new_tokens: {e}")
            return []

    # ── FETCH DEXSCREENER ────────────────────────────────
    async def _fetch_new_tokens(self) -> list:
        """Récupère les tokens récents sur DexScreener."""
        session = await self._get_session()
        tokens  = []

        # Source 1 — Nouveaux profils de tokens
        try:
            async with session.get(
                DEXSCREENER_NEW,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if isinstance(data, list):
                        for item in data:
                            addr = item.get("tokenAddress", "")
                            if (addr
                                    and not addr.startswith("0x")
                                    and item.get("chainId") == "solana"):
                                tokens.append({
                                    "tokenAddress": addr,
                                    "symbol": item.get("symbol", "???"),
                                    "name":   item.get("name", "Unknown"),
                                })
        except Exception as e:
            logger.debug(f"[POLLING] Source 1 erreur: {e}")

        # Source 2 — Trending Solana
        try:
            url = (
                "https://api.dexscreener.com/latest/dex/tokens/"
                "So11111111111111111111111111111111111111112"
            )
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    pairs = data.get("pairs", []) or []
                    for pair in pairs[:20]:
                        if pair.get("chainId") != "solana":
                            continue
                        addr = (
                            pair.get("baseToken", {})
                                .get("address", "")
                        )
                        if addr and not addr.startswith("0x"):
                            tokens.append({
                                "tokenAddress": addr,
                                "symbol": pair.get(
                                    "baseToken", {}
                                ).get("symbol", "???"),
                                "name": pair.get(
                                    "baseToken", {}
                                ).get("name", "Unknown"),
                            })
        except Exception as e:
            logger.debug(f"[POLLING] Source 2 erreur: {e}")

        return tokens

    # ── COMPATIBILITÉ ANCIEN CODE ─────────────────────────
    def get_trending_tokens(self) -> list:
        """Compatibilité avec l'ancien code synchrone."""
        return []