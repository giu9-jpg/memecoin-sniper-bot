# modules/whale_inflow.py — v9.2 FIXED
# FIX : URL API Helius corrigée
# FIX : estimation USD plus précise via prix SOL dynamique
# FIX : protection contre les valeurs None
# FIX : cache nettoyé correctement
# FIX : logs plus détaillés

import time
import os
import aiohttp
from utils.logger import logger

HELIUS_URL  = "https://api.helius.xyz/v0"
SOL_PRICE   = 150.0   # Prix SOL fallback si API indisponible


class WhaleInflowTracker:

    def __init__(self):
        self.session   = None
        rpc_url        = os.getenv("SOLANA_RPC_URL", "")
        self.api_key   = (
            rpc_url.split("api-key=")[-1]
            if "api-key=" in rpc_url else ""
        )
        self.cache     = {}          # {token_address: (timestamp, result)}
        self.sol_price = SOL_PRICE   # mis à jour dynamiquement
        self.CACHE_TTL = 300         # 5 min

        self.WHALE_MIN  = 1_000    # $1K minimum pour être whale
        self.GIGA_WHALE = 10_000   # $10K pour être giga whale

        if not self.api_key:
            logger.warning(
                "[WHALE_IN] ⚠️ Pas de clé Helius — inflow désactivé"
            )

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # PRIX SOL DYNAMIQUE
    # ═══════════════════════════════════════════════════

    async def _update_sol_price(self):
        """
        FIX : récupère le prix SOL réel pour une estimation USD précise.
        Fallback sur SOL_PRICE si indisponible.
        """
        try:
            session = await self._get_session()
            url     = (
                "https://api.coingecko.com/api/v3/simple/price"
                "?ids=solana&vs_currencies=usd"
            )
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data           = await resp.json()
                    self.sol_price = float(
                        data.get("solana", {}).get("usd", SOL_PRICE)
                    )
                    logger.debug(
                        f"[WHALE_IN] Prix SOL : ${self.sol_price:.2f}"
                    )
        except Exception:
            pass   # Garde le prix précédent

    # ═══════════════════════════════════════════════════
    # CHECK INFLOWS D'UN TOKEN
    # ═══════════════════════════════════════════════════

    async def check_token_inflows(
        self, token_address: str
    ) -> dict:
        """
        Vérifie les gros achats récents sur un token.
        FIX : URL API corrigée.
        FIX : estimation USD via prix SOL dynamique.
        """
        if not token_address:
            return self._empty_result()

        # ── Cache ─────────────────────────────────────
        cached = self.cache.get(token_address)
        if cached:
            ts, result = cached
            if time.time() - ts < self.CACHE_TTL:
                return result

        if not self.api_key:
            return self._empty_result()

        try:
            # Mise à jour prix SOL (si pas fait depuis 5 min)
            await self._update_sol_price()

            session = await self._get_session()

            # FIX : URL correcte Helius pour les tx d'un token
            url    = (
                f"{HELIUS_URL}/addresses/{token_address}/transactions"
            )
            params = {
                "api-key": self.api_key,
                "limit":   50,
                "type":    "SWAP",
            }

            async with session.get(
                url, params=params,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 429:
                    logger.warning("[WHALE_IN] Rate limit Helius")
                    return self._empty_result()
                if resp.status != 200:
                    logger.debug(
                        f"[WHALE_IN] Status {resp.status} "
                        f"pour {token_address[:8]}"
                    )
                    return self._empty_result()
                txs = await resp.json()

            if not isinstance(txs, list):
                return self._empty_result()

            # ── Analyse des 30 dernières minutes ──────
            cutoff      = time.time() - 1800
            whales      = []
            giga_whales = []
            total_buy   = 0.0

            for tx in txs:
                # FIX : protection timestamp None
                ts_tx = tx.get("timestamp") or 0
                if ts_tx < cutoff:
                    continue

                amount_usd = self._extract_buy_amount(
                    tx, token_address
                )
                if not amount_usd or amount_usd < 100:
                    continue

                total_buy += amount_usd

                entry = {
                    "amount":    round(amount_usd, 2),
                    "timestamp": ts_tx,
                }

                if amount_usd >= self.GIGA_WHALE:
                    giga_whales.append(entry)
                    logger.info(
                        f"[WHALE_IN] 🚨 GIGA ${amount_usd:,.0f} "
                        f"sur {token_address[:8]}"
                    )
                elif amount_usd >= self.WHALE_MIN:
                    whales.append(entry)
                    logger.info(
                        f"[WHALE_IN] 🐋 ${amount_usd:,.0f} "
                        f"sur {token_address[:8]}"
                    )

            # ── Calcul bonus ──────────────────────────
            bonus, message = self._calc_bonus(
                whales, giga_whales, total_buy
            )

            result = {
                "has_whales":    len(whales) + len(giga_whales) > 0,
                "whale_count":   len(whales),
                "giga_count":    len(giga_whales),
                "total_buy_usd": round(total_buy, 2),
                "bonus":         bonus,
                "message":       message,
            }

            # Cache le résultat
            self.cache[token_address] = (time.time(), result)
            return result

        except Exception as e:
            logger.debug(
                f"[WHALE_IN] Erreur {token_address[:8]}: {e}"
            )
            return self._empty_result()

    # ═══════════════════════════════════════════════════
    # CALCUL BONUS
    # ═══════════════════════════════════════════════════

    def _calc_bonus(
        self,
        whales:      list,
        giga_whales: list,
        total_buy:   float,
    ) -> tuple[float, str]:
        """Calcule le bonus selon les whales détectées."""
        n_giga  = len(giga_whales)
        n_whale = len(whales)

        if n_giga >= 2:
            return 4.0, f"🚨 {n_giga} GIGA WHALES !"
        elif n_giga == 1:
            amt = giga_whales[0]["amount"]
            return 3.0, f"🐋 GIGA : ${amt:,.0f}"
        elif n_whale >= 5:
            return 2.5, f"🐋 {n_whale} whales actives"
        elif n_whale >= 3:
            return 1.5, f"🐋 {n_whale} whales détectées"
        elif n_whale >= 1:
            return 1.0, f"🐋 {n_whale} whale(s)"

        return 0.0, ""

    # ═══════════════════════════════════════════════════
    # EXTRACTION MONTANT USD
    # ═══════════════════════════════════════════════════

    def _extract_buy_amount(
        self, tx: dict, token_address: str
    ) -> float:
        """
        Extrait le montant USD d'un achat.
        FIX : utilise self.sol_price dynamique.
        FIX : vérifie que le token est bien dans la tx.
        """
        try:
            # Vérifie que ce token est dans la transaction
            token_transfers = tx.get("tokenTransfers") or []
            has_token = any(
                t.get("mint") == token_address
                for t in token_transfers
            )
            if not has_token:
                return 0.0

            # SOL natif dépensé (approximation du coût)
            native_transfers = tx.get("nativeTransfers") or []
            native_sol = sum(
                abs(int(nt.get("amount", 0))) / 1e9
                for nt in native_transfers
                if nt.get("amount")
            )

            # FIX : utilise le prix SOL mis à jour
            return native_sol * self.sol_price

        except Exception as e:
            logger.debug(f"[WHALE_IN] _extract_buy_amount: {e}")
            return 0.0

    # ═══════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════

    def _empty_result(self) -> dict:
        return {
            "has_whales":    False,
            "whale_count":   0,
            "giga_count":    0,
            "total_buy_usd": 0.0,
            "bonus":         0.0,
            "message":       "",
        }

    # ═══════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════

    def cleanup_cache(self):
        """
        Nettoie le cache.
        FIX : supprime les entrées > 2x TTL.
        """
        now   = time.time()
        limit = self.CACHE_TTL * 2
        old   = [
            addr for addr, (ts, _) in self.cache.items()
            if now - ts > limit
        ]
        for addr in old:
            del self.cache[addr]

        if old:
            logger.debug(
                f"[WHALE_IN] 🧹 {len(old)} entrées supprimées"
            )

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()