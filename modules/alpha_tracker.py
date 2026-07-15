# modules/alpha_tracker.py — v6.0
# Suit les transactions des alpha wallets en temps réel

import time
import os
import asyncio
import aiohttp
from utils.logger import logger
from config.alpha_wallets import ALPHA_WALLETS, get_alpha_bonus


HELIUS_URL = "https://api.helius.xyz/v0"


class AlphaTracker:

    def __init__(self):
        self.session         = None
        rpc_url = os.getenv("SOLANA_RPC_URL", "")
        self.api_key = rpc_url.split("api-key=")[-1] if "api-key=" in rpc_url else ""
        self.token_buyers    = {}   # token_address → set de wallets
        self.last_check      = {}   # wallet → timestamp dernier check
        self.check_interval  = 300  # 5 min entre checks par wallet

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def get_all_wallets(self) -> list:
        """Retourne tous les alpha wallets."""
        all_wallets = []
        for tier_wallets in ALPHA_WALLETS.values():
            all_wallets.extend(tier_wallets)
        return all_wallets

    # ═══════════════════════════════════════════════════
    # CHECK ALPHA WALLETS
    # ═══════════════════════════════════════════════════
    async def check_alpha_wallets(self):
        """Vérifie les dernières transactions des alpha wallets."""
        if not self.api_key:
            logger.debug("[ALPHA] Pas de clé Helius")
            return

        wallets = self.get_all_wallets()

        for wallet in wallets:
            try:
                # Skip si checké récemment
                last = self.last_check.get(wallet, 0)
                if time.time() - last < self.check_interval:
                    continue

                await self._check_wallet_transactions(wallet)
                self.last_check[wallet] = time.time()

                # Ne pas spammer l'API
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.debug(f"[ALPHA] Erreur {wallet[:8]}: {e}")

    async def _check_wallet_transactions(self, wallet: str):
        """Récupère les dernières tx d'un wallet."""
        try:
            session = await self._get_session()
            url = f"{HELIUS_URL}/addresses/{wallet}/transactions"
            params = {
                "api-key": self.api_key,
                "limit":   10,
                "type":    "SWAP",
            }

            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return
                txs = await resp.json()

            if not isinstance(txs, list):
                return

            # Parser les swaps récents (< 1h)
            cutoff = time.time() - 3600

            for tx in txs:
                if tx.get("timestamp", 0) < cutoff:
                    continue

                # Extraire les tokens achetés
                token_transfers = tx.get("tokenTransfers", [])
                for transfer in token_transfers:
                    to_addr = transfer.get("toUserAccount", "")
                    if to_addr != wallet:
                        continue

                    mint = transfer.get("mint", "")
                    if mint and mint != "So11111111111111111111111111111111111111112":
                        # Enregistrer que ce alpha wallet a acheté ce token
                        if mint not in self.token_buyers:
                            self.token_buyers[mint] = set()
                        self.token_buyers[mint].add(wallet)
                        logger.info(
                            f"[ALPHA] 🐋 {wallet[:8]}... a acheté {mint[:8]}..."
                        )

        except Exception as e:
            logger.debug(f"[ALPHA] Erreur tx {wallet[:8]}: {e}")

    # ═══════════════════════════════════════════════════
    # SIGNAL ALPHA POUR UN TOKEN
    # ═══════════════════════════════════════════════════
    def get_alpha_signal(self, token_address: str) -> dict:
        """Retourne le signal alpha pour un token donné."""
        buyers = list(self.token_buyers.get(token_address, set()))

        if not buyers:
            return {
                "has_alpha":     False,
                "wallet_count":  0,
                "bonus":         0,
                "message":       "",
                "wallets":       [],
            }

        bonus, message = get_alpha_bonus(buyers)

        return {
            "has_alpha":     True,
            "wallet_count":  len(buyers),
            "bonus":         bonus,
            "message":       message,
            "wallets":       buyers,
        }

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()