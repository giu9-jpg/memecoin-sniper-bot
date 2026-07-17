# modules/alpha_tracker.py — v8.0
# Suit les transactions des alpha wallets en temps réel
# + Copy Trading Alert (v8.0)

import time
import os
import asyncio
import aiohttp
from utils.logger import logger
from config.alpha_wallets import ALPHA_WALLETS, get_alpha_bonus, get_wallet_tier


HELIUS_URL = "https://api.helius.xyz/v0"


class AlphaTracker:

    def __init__(self):
        self.session         = None
        rpc_url = os.getenv("SOLANA_RPC_URL", "")
        self.api_key = (
            rpc_url.split("api-key=")[-1]
            if "api-key=" in rpc_url else ""
        )
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
    # CHECK ALPHA WALLETS (existant)
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

    # ═══════════════════════════════════════════════════
    # 🚀 COPY TRADING ALERT (v8.0)
    # ═══════════════════════════════════════════════════
    async def check_new_alpha_buys(self, callback=None) -> list:
        """
        Vérifie les nouveaux achats des alpha wallets.
        Retourne les tokens fraichement achetés.
        Appelle callback(token_address, wallet, tier) si fourni.
        """
        if not self.api_key:
            return []

        new_buys = []
        wallets  = self.get_all_wallets()

        for wallet in wallets:
            try:
                # Skip si checké récemment (< 3 min)
                last = self.last_check.get(wallet, 0)
                if time.time() - last < 180:
                    continue

                # Nouveau check
                new_tokens = await self._get_recent_buys(wallet)

                for token in new_tokens:
                    tier = get_wallet_tier(wallet)

                    new_buys.append({
                        "token":     token,
                        "wallet":    wallet,
                        "tier":      tier,
                        "timestamp": time.time(),
                    })

                    # Enregistre aussi dans token_buyers pour cumul
                    if token not in self.token_buyers:
                        self.token_buyers[token] = set()
                    self.token_buyers[token].add(wallet)

                    # Callback si fourni
                    if callback:
                        try:
                            await callback(token, wallet, tier)
                        except Exception as e:
                            logger.error(f"[COPY] Callback error: {e}")

                self.last_check[wallet] = time.time()

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.debug(f"[ALPHA] Erreur buys {wallet[:8]}: {e}")

        return new_buys

    async def _get_recent_buys(self, wallet: str) -> list:
        """Récupère les tokens achetés dans les 15 dernières minutes."""
        try:
            session = await self._get_session()
            url     = f"{HELIUS_URL}/addresses/{wallet}/transactions"
            params  = {
                "api-key": self.api_key,
                "limit":   5,
                "type":    "SWAP",
            }

            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return []
                txs = await resp.json()

            if not isinstance(txs, list):
                return []

            # Cutoff 15 min
            cutoff     = time.time() - 900
            new_tokens = []

            for tx in txs:
                if tx.get("timestamp", 0) < cutoff:
                    continue

                for transfer in tx.get("tokenTransfers", []):
                    if transfer.get("toUserAccount") == wallet:
                        mint = transfer.get("mint", "")
                        if (mint
                                and mint not in new_tokens
                                and mint != "So11111111111111111111111111111111111111112"):
                            new_tokens.append(mint)

            return new_tokens

        except Exception:
            return []

    # ═══════════════════════════════════════════════════
    # CLEANUP MÉMOIRE
    # ═══════════════════════════════════════════════════
    def cleanup_old_data(self):
        """Nettoie les tokens de plus de 6h en mémoire."""
        # Limite : max 200 tokens en mémoire
        MAX_TOKENS = 200

        if len(self.token_buyers) > MAX_TOKENS:
            # Garde seulement les 100 plus récents
            items = list(self.token_buyers.items())
            self.token_buyers = dict(items[-100:])
            logger.info(
                f"[ALPHA] 🧹 Nettoyage : gardé 100/{len(items)} tokens"
            )

        # Nettoie aussi les last_check trop vieux
        now = time.time()
        old_wallets = [
            w for w, t in self.last_check.items()
            if now - t > 3600  # +1h
        ]
        for w in old_wallets:
            del self.last_check[w]

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()