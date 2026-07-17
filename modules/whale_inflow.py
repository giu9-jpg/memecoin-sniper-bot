# modules/whale_inflow.py — v9.0
# Détecte les gros achats (inflows) sur les tokens

import time
import os
import aiohttp
from utils.logger import logger


HELIUS_URL = "https://api.helius.xyz/v0"


class WhaleInflowTracker:

    def __init__(self):
        self.session = None
        rpc_url      = os.getenv("SOLANA_RPC_URL", "")
        self.api_key = (
            rpc_url.split("api-key=")[-1]
            if "api-key=" in rpc_url else ""
        )
        self.cache    = {}   # token → (timestamp, result)
        self.CACHE_TTL = 300  # 5 min de cache

        # Seuils en USD
        self.WHALE_MIN     = 1_000
        self.GIGA_WHALE    = 10_000

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # CHECK INFLOWS D'UN TOKEN
    # ═══════════════════════════════════════════════════

    async def check_token_inflows(
        self, token_address: str
    ) -> dict:
        """Vérifie les gros achats récents sur un token."""

        # ── Cache pour éviter spam API ────────────────
        cached = self.cache.get(token_address)
        if cached:
            ts, result = cached
            if time.time() - ts < self.CACHE_TTL:
                return result

        if not self.api_key:
            return self._empty_result()

        try:
            session = await self._get_session()
            url = f"{HELIUS_URL}/tokens/{token_address}/transactions"
            params = {
                "api-key": self.api_key,
                "limit":   50,
                "type":    "SWAP",
            }

            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return self._empty_result()
                txs = await resp.json()

            if not isinstance(txs, list):
                return self._empty_result()

            # Analyse les 30 dernières min
            cutoff = time.time() - 1800

            whales      = []
            giga_whales = []
            total_buy   = 0

            for tx in txs:
                if tx.get("timestamp", 0) < cutoff:
                    continue

                amount_usd = self._extract_buy_amount(tx, token_address)
                if not amount_usd or amount_usd < 100:
                    continue

                total_buy += amount_usd

                if amount_usd >= self.GIGA_WHALE:
                    giga_whales.append({
                        "amount":    amount_usd,
                        "timestamp": tx.get("timestamp", 0),
                    })
                elif amount_usd >= self.WHALE_MIN:
                    whales.append({
                        "amount":    amount_usd,
                        "timestamp": tx.get("timestamp", 0),
                    })

            # ── Calcul bonus ──────────────────────────
            bonus   = 0.0
            message = ""

            if len(giga_whales) >= 2:
                bonus   = 4.0
                message = f"🚨 {len(giga_whales)} GIGA WHALES !"
            elif len(giga_whales) == 1:
                bonus   = 3.0
                message = f"🐋 GIGA : ${giga_whales[0]['amount']:,.0f}"
            elif len(whales) >= 5:
                bonus   = 2.5
                message = f"🐋 {len(whales)} whales détectées"
            elif len(whales) >= 3:
                bonus   = 1.5
                message = f"🐋 {len(whales)} whales actives"
            elif len(whales) >= 1:
                bonus   = 1.0
                message = f"🐋 {len(whales)} whale(s)"

            result = {
                "has_whales":      len(whales) + len(giga_whales) > 0,
                "whale_count":     len(whales),
                "giga_count":      len(giga_whales),
                "total_buy_usd":   round(total_buy, 2),
                "bonus":           bonus,
                "message":         message,
            }

            # Cache
            self.cache[token_address] = (time.time(), result)

            return result

        except Exception as e:
            logger.debug(f"[WHALE_IN] Erreur {token_address[:8]}: {e}")
            return self._empty_result()

    def _extract_buy_amount(
        self, tx: dict, token_address: str
    ) -> float:
        """Extrait le montant USD d'un achat."""
        try:
            # Cherche les tokenTransfers du bon mint
            has_token = False
            for transfer in tx.get("tokenTransfers", []):
                if transfer.get("mint") == token_address:
                    has_token = True
                    break

            if not has_token:
                return 0

            # Somme des SOL natifs échangés (approximation)
            native_amount = sum(
                abs(nt.get("amount", 0)) / 1e9
                for nt in tx.get("nativeTransfers", [])
            )

            # 1 SOL ≈ $150 (approximation)
            return native_amount * 150

        except Exception:
            return 0

    def _empty_result(self) -> dict:
        return {
            "has_whales":    False,
            "whale_count":   0,
            "giga_count":    0,
            "total_buy_usd": 0,
            "bonus":         0,
            "message":       "",
        }

    def cleanup_cache(self):
        """Nettoie le cache."""
        now = time.time()
        old = [
            addr for addr, (t, _) in self.cache.items()
            if now - t > self.CACHE_TTL * 2
        ]
        for addr in old:
            del self.cache[addr]

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()