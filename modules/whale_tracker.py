# modules/whale_tracker.py — v2.5 FIXED
# FIX : close() ajouté
# FIX : protection si HELIUS_API_KEY vide
# FIX : signal_cache nettoyé périodiquement

import os
import asyncio
import aiohttp
import time
from config.whales import get_active_wallets, get_whale_by_address
from utils.logger  import logger

HELIUS_RPC_URL = os.getenv("SOLANA_RPC_URL", "")
HELIUS_API_KEY = (
    HELIUS_RPC_URL.split("api-key=")[-1]
    if "api-key=" in HELIUS_RPC_URL else ""
)
HELIUS_API_URL = "https://api.helius.xyz/v0"
MIN_TRADE_USD  = 100
CACHE_DURATION = 300   # 5 min


class WhaleTracker:

    def __init__(self):
        self.session         = None
        self.last_signatures = {}
        self.signal_cache    = {}
        self.active_wallets  = get_active_wallets()
        self._last_cleanup   = time.time()

        logger.info(
            f"[WHALE] {len(self.active_wallets)} baleines chargées"
        )

        if not HELIUS_API_KEY:
            logger.warning(
                "[WHALE] ⚠️ Pas de clé Helius — tracker désactivé"
            )

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # CHECK PRINCIPAL
    # ═══════════════════════════════════════════════════

    async def check_whales(self) -> list:
        """
        Vérifie toutes les baleines en parallèle.
        FIX : retourne [] si pas de clé API.
        """
        if not HELIUS_API_KEY:
            return []

        # FIX : nettoyage périodique du cache (toutes les 30 min)
        if time.time() - self._last_cleanup > 1800:
            self._cleanup_cache()
            self._last_cleanup = time.time()

        signals = []
        tasks   = [
            self._check_single_whale(wallet)
            for wallet in self.active_wallets
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, list):
                signals.extend(r)
            elif isinstance(r, Exception):
                logger.debug(f"[WHALE] Exception gather: {r}")

        if signals:
            logger.info(f"[WHALE] {len(signals)} signal(s) détecté(s)")

        return signals

    async def _check_single_whale(self, wallet: str) -> list:
        """Vérifie un seul wallet."""
        try:
            txs     = await self._get_transactions(wallet)
            signals = []

            for tx in txs:
                sig = self._parse_tx(tx, wallet)
                if not sig:
                    continue

                cache_key = f"{wallet}_{sig['token_address']}"
                if cache_key in self.signal_cache:
                    if (
                        time.time() - self.signal_cache[cache_key]
                        < CACHE_DURATION
                    ):
                        continue

                self.signal_cache[cache_key] = time.time()
                signals.append(sig)

            return signals

        except Exception as e:
            logger.debug(f"[WHALE] Erreur {wallet[:8]}: {e}")
            return []

    async def _get_transactions(self, wallet: str) -> list:
        """Récupère les dernières transactions d'un wallet."""
        if not HELIUS_API_KEY:
            return []
        try:
            session = await self._get_session()
            url     = f"{HELIUS_API_URL}/addresses/{wallet}/transactions"
            params  = {
                "api-key": HELIUS_API_KEY,
                "limit":   10,
                "type":    "SWAP",
            }
            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return []
                txs = await resp.json()

                if txs and isinstance(txs, list):
                    self.last_signatures[wallet] = txs[0].get(
                        "signature", ""
                    )

                return txs if isinstance(txs, list) else []

        except Exception as e:
            logger.debug(f"[WHALE] API {wallet[:8]}: {e}")
            return []

    def _parse_tx(self, tx: dict, whale_address: str) -> dict | None:
        """Parse une transaction et retourne un signal ou None."""
        try:
            if tx.get("type") not in ("SWAP", "TOKEN_MINT"):
                return None

            source = tx.get("source", "").upper()
            if source not in (
                "PUMP_FUN", "RAYDIUM", "JUPITER", "ORCA"
            ):
                return None

            # Montant USD approximatif
            amount_usd = sum(
                t.get("amount", 0) / 1e9 * 200
                for t in tx.get("nativeTransfers", [])
                if t.get("fromUserAccount") == whale_address
            )

            if amount_usd < MIN_TRADE_USD:
                return None

            # Token acheté/vendu
            token_address = ""
            token_symbol  = "???"
            action        = "buy"

            STABLES = {
                "So11111111111111111111111111111111111111112",
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            }

            for t in tx.get("tokenTransfers", []):
                mint = t.get("mint", "")
                if not mint or mint in STABLES:
                    continue
                if t.get("toUserAccount") == whale_address:
                    token_address = mint
                    token_symbol  = t.get("tokenSymbol", "???")
                if t.get("fromUserAccount") == whale_address:
                    action = "sell"

            if not token_address or token_address.startswith("0x"):
                return None

            whale_info = get_whale_by_address(whale_address) or {}

            return {
                "whale_address": whale_address,
                "whale_label":   whale_info.get(
                    "label", f"{whale_address[:8]}..."
                ),
                "whale_tier":    whale_info.get("tier", 3),
                "token_address": token_address,
                "token_symbol":  token_symbol,
                "action":        action,
                "amount_usd":    round(amount_usd, 2),
                "timestamp":     tx.get("timestamp", int(time.time())),
            }

        except Exception as e:
            logger.debug(f"[WHALE] Parse error: {e}")
            return None

    # ═══════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════

    def _cleanup_cache(self):
        """FIX : nettoie le signal_cache pour éviter croissance infinie."""
        now     = time.time()
        old     = [
            k for k, ts in self.signal_cache.items()
            if now - ts > CACHE_DURATION * 2
        ]
        for k in old:
            del self.signal_cache[k]

        if old:
            logger.debug(
                f"[WHALE] 🧹 {len(old)} entrées cache supprimées"
            )

    # FIX : close() manquant dans l'original
    async def close(self):
        """Ferme la session HTTP."""
        if self.session and not self.session.closed:
            await self.session.close()

    # Compatibilité ancien code
    def check_whale_activity(self, contract: str) -> dict:
        return {
            "is_smart_money_signal": False,
            "whale_count":           0,
            "whale_names":           [],
            "whales":                [],
            "score_bonus":           0,
        }