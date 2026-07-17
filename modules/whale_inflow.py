# modules/whale_inflow.py — v8.0
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
        self.whale_buys = {}   # token → liste de gros achats

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
        if not self.api_key:
            return self._empty_result()

        try:
            session = await self._get_session()
            url     = (
                f"{HELIUS_URL}/tokens/{token_address}/transactions"
            )
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

                # Extrait le montant USD
                amount_usd = self._extract_buy_amount(tx, token_address)
                if not amount_usd:
                    continue

                total_buy += amount_usd

                if amount_usd >= self.GIGA_WHALE:
                    giga_whales.append({
                        "amount":    amount_usd,
                        "timestamp": tx.get("timestamp", 0),
                        "wallet":    tx.get("feePayer", "unknown"),
                    })
                elif amount_usd >= self.WHALE_MIN:
                    whales.append({
                        "amount":    amount_usd,
                        "timestamp": tx.get("timestamp", 0),
                        "wallet":    tx.get("feePayer", "unknown"),
                    })

            # Calcul score bonus
            bonus = 0.0
            message = ""

            if len(giga_whales) >= 2:
                bonus = 4.0
                message = f"🚨 {len(giga_whales)} GIGA WHALES achètent !"
            elif len(giga_whales) == 1:
                bonus = 3.0
                message = f"🐋 GIGA WHALE : ${giga_whales[0]['amount']:,.0f}"
            elif len(whales) >= 5:
                bonus = 2.5
                message = f"🐋 {len(whales)} whales détectées"
            elif len(whales) >= 3:
                bonus = 1.5
                message = f"🐋 {len(whales)} whales actives"
            elif len(whales) >= 1:
                bonus = 1.0
                message = f"🐋 {len(whales)} whale(s)"

            return {
                "has_whales":      len(whales) + len(giga_whales) > 0,
                "whale_count":     len(whales),
                "giga_count":      len(giga_whales),
                "total_buy_usd":   round(total_buy, 2),
                "bonus":           bonus,
                "message":         message,
            }

        except Exception as e:
            logger.debug(f"[WHALE_IN] Erreur {token_address[:8]}: {e}")
            return self._empty_result()

    def _extract_buy_amount(
        self, tx: dict, token_address: str
    ) -> float:
        """Extrait le montant USD d'un achat."""
        try:
            # Cherche dans nativeTransfers ou tokenTransfers
            for transfer in tx.get("tokenTransfers", []):
                if transfer.get("mint") == token_address:
                    # Estimation en USD via prix approximatif
                    # Note : Helius ne fournit pas toujours le prix USD
                    # → on utilise le montant SOL comme proxy
                    amount = float(transfer.get("tokenAmount", 0))
                    if amount > 0:
                        # Approximation grossière
                        # 1 SOL ≈ $150
                        native_amount = sum(
                            abs(nt.get("amount", 0)) / 1e9
                            for nt in tx.get("nativeTransfers", [])
                        )
                        return native_amount * 150

            return 0
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

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()