# modules/alpha_tracker.py — v8.1 FIXED
# FIX : last_check séparé pour scan vs copy trading
# FIX : seen_buy_events pour éviter doublons copy trading
# FIX : cleanup_old_data nettoie aussi seen_buy_events
# FIX : get_alpha_signal retourne wallets dans le résultat

import time
import os
import asyncio
import aiohttp
from utils.logger import logger
from config.alpha_wallets import (
    ALPHA_WALLETS,
    get_wallet_bonus,
    get_wallet_tier,
)

HELIUS_URL = "https://api.helius.xyz/v0"


class AlphaTracker:

    def __init__(self):
        self.session  = None
        rpc_url       = os.getenv("SOLANA_RPC_URL", "")
        self.api_key  = (
            rpc_url.split("api-key=")[-1]
            if "api-key=" in rpc_url else ""
        )

        self.token_buyers = {}   # {token_address: set(wallets)}

        # FIX : deux dicts séparés pour éviter conflits
        self.last_check_scan = {}   # wallet → ts dernier scan général
        self.last_check_copy = {}   # wallet → ts dernier check copy

        # FIX : déduplication des buy events
        self.seen_buy_events = {}   # {event_id: timestamp}

        self.scan_interval = 300    # 5 min entre scans généraux
        self.copy_interval = 180    # 3 min entre checks copy

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def get_all_wallets(self) -> list:
        all_wallets = []
        for tier_wallets in ALPHA_WALLETS.values():
            all_wallets.extend(tier_wallets)
        return all_wallets

    # ═══════════════════════════════════════════════════
    # SCAN GÉNÉRAL (toutes les 5 min)
    # ═══════════════════════════════════════════════════

    async def check_alpha_wallets(self):
        """Vérifie les dernières transactions des alpha wallets."""
        if not self.api_key:
            logger.debug("[ALPHA] Pas de clé Helius API")
            return

        wallets = self.get_all_wallets()

        for wallet in wallets:
            try:
                # FIX : utilise last_check_scan
                last = self.last_check_scan.get(wallet, 0)
                if time.time() - last < self.scan_interval:
                    continue

                await self._check_wallet_transactions(wallet)
                self.last_check_scan[wallet] = time.time()

                await asyncio.sleep(0.5)

            except Exception as e:
                logger.debug(f"[ALPHA] Erreur scan {wallet[:8]}: {e}")

    async def _check_wallet_transactions(self, wallet: str):
        """Récupère et analyse les dernières tx d'un wallet."""
        try:
            session = await self._get_session()
            url     = f"{HELIUS_URL}/addresses/{wallet}/transactions"
            params  = {
                "api-key": self.api_key,
                "limit":   10,
                "type":    "SWAP",
            }

            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    return
                txs = await resp.json()

            if not isinstance(txs, list):
                return

            cutoff = time.time() - 3600  # 1h max

            for tx in txs:
                if tx.get("timestamp", 0) < cutoff:
                    continue

                for transfer in tx.get("tokenTransfers", []):
                    if transfer.get("toUserAccount") != wallet:
                        continue

                    mint = transfer.get("mint", "")
                    if not mint or mint == (
                        "So11111111111111111111111111111111111111112"
                    ):
                        continue

                    if mint not in self.token_buyers:
                        self.token_buyers[mint] = set()
                    self.token_buyers[mint].add(wallet)

                    logger.info(
                        f"[ALPHA] 🐋 {wallet[:8]}... → {mint[:8]}..."
                    )

        except Exception as e:
            logger.debug(f"[ALPHA] Erreur tx {wallet[:8]}: {e}")

    # ═══════════════════════════════════════════════════
    # SIGNAL ALPHA POUR UN TOKEN
    # ═══════════════════════════════════════════════════

    def get_alpha_signal(self, token_address: str) -> dict:
        """
        Retourne le signal alpha pour un token.
        FIX : inclut la liste des wallets dans le résultat.
        """
        buyers = list(self.token_buyers.get(token_address, set()))

        if not buyers:
            return {
                "has_alpha":    False,
                "wallet_count": 0,
                "bonus":        0.0,
                "message":      "",
                "wallets":      [],
            }

        # FIX : get_wallet_bonus attend une liste
        bonus, message = get_wallet_bonus(buyers)

        return {
            "has_alpha":    True,
            "wallet_count": len(buyers),
            "bonus":        bonus,
            "message":      message,
            "wallets":      buyers,   # FIX : retourné pour alpha_wallet_list
        }

    # ═══════════════════════════════════════════════════
    # COPY TRADING (toutes les 3 min)
    # ═══════════════════════════════════════════════════

    async def check_new_alpha_buys(
        self, callback=None
    ) -> list:
        """
        Vérifie les nouveaux achats des alpha wallets.
        FIX : utilise last_check_copy séparé.
        FIX : déduplique via seen_buy_events.
        """
        if not self.api_key:
            return []

        new_buys = []
        wallets  = self.get_all_wallets()

        for wallet in wallets:
            try:
                # FIX : utilise last_check_copy
                last = self.last_check_copy.get(wallet, 0)
                if time.time() - last < self.copy_interval:
                    continue

                new_tokens = await self._get_recent_buys(wallet)

                for token in new_tokens:
                    tier = get_wallet_tier(wallet)

                    new_buys.append({
                        "token":     token,
                        "wallet":    wallet,
                        "tier":      tier,
                        "timestamp": time.time(),
                    })

                    # Cumul dans token_buyers
                    if token not in self.token_buyers:
                        self.token_buyers[token] = set()
                    self.token_buyers[token].add(wallet)

                    if callback:
                        try:
                            await callback(token, wallet, tier)
                        except Exception as e:
                            logger.error(f"[COPY] Callback error: {e}")

                # FIX : utilise last_check_copy
                self.last_check_copy[wallet] = time.time()
                await asyncio.sleep(0.5)

            except Exception as e:
                logger.debug(
                    f"[ALPHA] Erreur copy {wallet[:8]}: {e}"
                )

        return new_buys

    async def _get_recent_buys(self, wallet: str) -> list:
        """
        Récupère les tokens achetés dans les 15 dernières minutes.
        FIX : déduplique via seen_buy_events {wallet:sig:mint}.
        """
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
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    return []
                txs = await resp.json()

            if not isinstance(txs, list):
                return []

            cutoff     = time.time() - 900  # 15 min
            new_tokens = []

            for tx in txs:
                if tx.get("timestamp", 0) < cutoff:
                    continue

                # FIX : récupère la signature pour déduplication
                signature = tx.get("signature", "")

                for transfer in tx.get("tokenTransfers", []):
                    if transfer.get("toUserAccount") != wallet:
                        continue

                    mint = transfer.get("mint", "")
                    if not mint or mint == (
                        "So11111111111111111111111111111111111111112"
                    ):
                        continue

                    # FIX : event_id unique par (wallet, sig, mint)
                    event_id = f"{wallet}:{signature}:{mint}"

                    if event_id in self.seen_buy_events:
                        continue

                    # Marque comme vu
                    self.seen_buy_events[event_id] = time.time()

                    if mint not in new_tokens:
                        new_tokens.append(mint)
                        logger.info(
                            f"[COPY] 🆕 Nouvel achat détecté : "
                            f"{wallet[:8]}... → {mint[:8]}..."
                        )

            return new_tokens

        except Exception as e:
            logger.debug(f"[ALPHA] Erreur _get_recent_buys {wallet[:8]}: {e}")
            return []

    # ═══════════════════════════════════════════════════
    # CLEANUP MÉMOIRE
    # ═══════════════════════════════════════════════════

    def cleanup_old_data(self):
        """
        Nettoie les données en mémoire.
        FIX : nettoie aussi seen_buy_events et last_check_*.
        """
        now       = time.time()
        MAX_TOKENS = 200

        # ── token_buyers ──────────────────────────────
        if len(self.token_buyers) > MAX_TOKENS:
            items = list(self.token_buyers.items())
            self.token_buyers = dict(items[-100:])
            logger.info(
                f"[ALPHA] 🧹 token_buyers: gardé 100/{len(items)}"
            )

        # ── seen_buy_events (> 1h) ────────────────────
        old_events = [
            k for k, ts in self.seen_buy_events.items()
            if now - ts > 3600
        ]
        for k in old_events:
            del self.seen_buy_events[k]

        if old_events:
            logger.debug(
                f"[ALPHA] 🧹 seen_buy_events: "
                f"{len(old_events)} events supprimés"
            )

        # ── last_check_scan (> 2h) ────────────────────
        old_scan = [
            w for w, ts in self.last_check_scan.items()
            if now - ts > 7200
        ]
        for w in old_scan:
            del self.last_check_scan[w]

        # ── last_check_copy (> 2h) ────────────────────
        old_copy = [
            w for w, ts in self.last_check_copy.items()
            if now - ts > 7200
        ]
        for w in old_copy:
            del self.last_check_copy[w]

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()