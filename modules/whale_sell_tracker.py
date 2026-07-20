# modules/whale_sell_tracker.py v1.0
"""
Whale Sell Tracker
Surveille les ventes massives des alpha wallets et whales.

Détecte :
  - Alpha wallets qui vendent (dump avant les autres)
  - Whales avec position > $10K qui sortent
  - Ventes en cascade sur un token

Sources :
  - Alpha wallets (config/alpha_wallets.py)
  - Solscan API pour les transactions
  - DexScreener pour le prix contextuel
"""

import aiohttp
import asyncio
import time
from utils.logger import get_logger

logger = get_logger("whale_sell")


class WhaleSellTracker:

    # ════════════════════════════════════════
    # CONFIGURATION
    # ════════════════════════════════════════

    # Seuils de détection
    MIN_SELL_USD           = 5_000    # Vente > $5K = whale
    MIN_ALPHA_SELL_USD     = 1_000    # Alpha wallet: dès $1K
    GIGA_SELL_USD          = 25_000   # $25K+ = giga sell

    # Cascade detection
    CASCADE_MIN_SELLS      = 3        # 3+ ventes rapprochées
    CASCADE_WINDOW_MIN     = 10       # dans 10 minutes

    # Anti-doublon
    ALERT_COOLDOWN         = 1800     # 30 min par token

    # Cycle scan
    SCAN_INTERVAL          = 120      # 2 minutes

    def __init__(self, alert_callback, alpha_wallets: list = None):
        """
        alert_callback : fonction async pour envoyer l'alerte
        alpha_wallets  : liste des adresses alpha à surveiller
        """
        self.alert_callback = alert_callback
        self.alpha_wallets  = alpha_wallets or []
        self.session        = None
        self.running        = False

        # Suivi des positions alpha
        # {wallet: {token: {amount_hold, entry_price, timestamp}}}
        self.alpha_holdings = {}

        # Alertes récentes
        self.alerted = {}  # {mint: timestamp}

        # Historique ventes récentes par token (cascade)
        # {token: [{wallet, amount, timestamp}]}
        self.recent_sells = {}

        # Stats
        self.whales_tracked   = 0
        self.sells_detected   = 0
        self.alpha_sells      = 0
        self.giga_sells       = 0
        self.cascades_found   = 0

    async def start(self):
        """Démarre le tracker"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )
        self.running = True
        logger.info(
            f"🐋 WhaleSellTracker démarré "
            f"({len(self.alpha_wallets)} alpha wallets)"
        )
        asyncio.create_task(self._scan_loop())

    async def stop(self):
        """Arrêt propre"""
        self.running = False
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("🐋 WhaleSellTracker arrêté")

    # ════════════════════════════════════════
    # BOUCLE PRINCIPALE
    # ════════════════════════════════════════

    async def _scan_loop(self):
        """Boucle de surveillance des alpha wallets"""
        while self.running:
            try:
                await self._check_alpha_wallets()
                self._cleanup_old_data()
            except Exception as e:
                logger.error(f"WhaleSellTracker error : {e}")
            await asyncio.sleep(self.SCAN_INTERVAL)

    async def _check_alpha_wallets(self):
        """Vérifie les transactions récentes de tous les alpha wallets"""
        if not self.alpha_wallets:
            return

        # Limite pour ne pas surcharger l'API
        wallets_to_check = self.alpha_wallets[:15]

        tasks = [
            self._check_wallet_sells(wallet)
            for wallet in wallets_to_check
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_wallet_sells(self, wallet: str):
        """Vérifie les ventes d'un wallet spécifique"""
        try:
            # Récupère les dernières transactions Solscan
            url = (
                f"https://public-api.solscan.io/account/splTransfers"
                f"?account={wallet}&limit=10&offset=0"
            )

            headers = {
                "accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            }

            async with self.session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return

                data = await resp.json()

            transfers = data if isinstance(data, list) else data.get("data", [])

            # Filtre : transferts SORTANTS (le wallet est source)
            for tx in transfers[:20]:
                src = tx.get("src") or tx.get("source")
                if src != wallet:
                    continue

                amount = tx.get("amount", 0) or 0
                token_mint = tx.get("tokenAddress") or tx.get("mint")

                if not token_mint or amount <= 0:
                    continue

                # Estimer valeur USD
                amount_usd = await self._estimate_usd_value(
                    token_mint, amount
                )

                if amount_usd < self.MIN_ALPHA_SELL_USD:
                    continue

                # Anti-doublon par token
                cooldown_key = f"{wallet}_{token_mint}"
                if cooldown_key in self.alerted:
                    if time.time() - self.alerted[cooldown_key] < 3600:
                        continue

                # ═══ VENTE DÉTECTÉE ═══
                await self._process_sell(
                    wallet=wallet,
                    mint=token_mint,
                    amount_usd=amount_usd,
                    is_alpha=True,
                )

                self.alerted[cooldown_key] = time.time()

        except asyncio.TimeoutError:
            logger.debug(f"Timeout wallet {wallet[:8]}...")
        except Exception as e:
            logger.debug(f"Wallet check error : {e}")

    async def _estimate_usd_value(
        self, mint: str, amount: float
    ) -> float:
        """Estime la valeur USD d'un token vendu"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return 0
                data = await resp.json()

            pairs = data.get("pairs") or []
            if not pairs:
                return 0

            price_usd = float(pairs[0].get("priceUsd", 0) or 0)
            return amount * price_usd

        except Exception:
            return 0

    async def _process_sell(
        self,
        wallet: str,
        mint: str,
        amount_usd: float,
        is_alpha: bool = False,
    ):
        """Traite une vente détectée"""
        try:
            # Récupère données actuelles du token
            token_data = await self._fetch_token_context(mint)
            if not token_data:
                return

            symbol = token_data.get("symbol", "?")

            # Cascade detection
            if mint not in self.recent_sells:
                self.recent_sells[mint] = []

            self.recent_sells[mint].append({
                "wallet":     wallet,
                "amount_usd": amount_usd,
                "timestamp":  time.time(),
                "is_alpha":   is_alpha,
            })

            # Nettoie l'historique > 10 min
            cutoff = time.time() - (self.CASCADE_WINDOW_MIN * 60)
            self.recent_sells[mint] = [
                s for s in self.recent_sells[mint]
                if s["timestamp"] > cutoff
            ]

            # Détection cascade
            cascade = len(self.recent_sells[mint]) >= self.CASCADE_MIN_SELLS
            if cascade:
                self.cascades_found += 1

            # Sévérité
            if amount_usd >= self.GIGA_SELL_USD:
                severity = "GIGA_SELL"
                self.giga_sells += 1
            elif is_alpha:
                severity = "ALPHA_SELL"
                self.alpha_sells += 1
            elif amount_usd >= self.MIN_SELL_USD:
                severity = "WHALE_SELL"
            else:
                return  # Trop petit

            self.sells_detected += 1

            # Construction du signal
            sell_data = {
                "wallet":           wallet,
                "wallet_short":     f"{wallet[:8]}...{wallet[-4:]}",
                "mint":             mint,
                "symbol":           symbol,
                "amount_usd":       amount_usd,
                "severity":         severity,
                "is_alpha":         is_alpha,
                "cascade":          cascade,
                "cascade_count":    len(self.recent_sells[mint]),
                "price":            token_data.get("price", 0),
                "market_cap":       token_data.get("market_cap", 0),
                "liquidity":        token_data.get("liquidity", 0),
                "change_5m":        token_data.get("change_5m", 0),
                "change_1h":        token_data.get("change_1h", 0),
                "buy_ratio":        token_data.get("buy_ratio", 0),
                "timestamp":        time.time(),
            }

            logger.info(
                f"🐋 SELL détecté : ${symbol} | "
                f"{severity} | ${amount_usd:,.0f} | "
                f"Wallet: {wallet[:8]}..."
            )

            # Callback vers main.py
            if self.alert_callback:
                await self.alert_callback(sell_data)

        except Exception as e:
            logger.error(f"Process sell error : {e}")

    async def _fetch_token_context(self, mint: str) -> dict:
        """Récupère le contexte actuel du token"""
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            pairs = data.get("pairs") or []
            if not pairs:
                return None

            pair = pairs[0]
            base = pair.get("baseToken", {})
            price_change = pair.get("priceChange", {})
            txns = pair.get("txns", {})

            buys_1h = txns.get("h1", {}).get("buys", 0) if txns.get("h1") else 0
            sells_1h = txns.get("h1", {}).get("sells", 0) if txns.get("h1") else 0
            txns_1h = buys_1h + sells_1h
            buy_ratio = round(buys_1h / txns_1h * 100, 1) if txns_1h > 0 else 50

            return {
                "symbol":     base.get("symbol", "?"),
                "name":       base.get("name", "?"),
                "price":      float(pair.get("priceUsd", 0) or 0),
                "market_cap": pair.get("marketCap", 0) or pair.get("fdv", 0) or 0,
                "liquidity":  pair.get("liquidity", {}).get("usd", 0) or 0,
                "change_5m":  price_change.get("m5", 0) or 0,
                "change_1h":  price_change.get("h1", 0) or 0,
                "buy_ratio":  buy_ratio,
            }
        except Exception:
            return None

    def _cleanup_old_data(self):
        """Nettoie les vieilles données"""
        now = time.time()
        cutoff_alerted = now - 7200  # 2h
        cutoff_sells = now - 3600    # 1h

        # Nettoie alerted
        old = [
            k for k, v in self.alerted.items()
            if v < cutoff_alerted
        ]
        for k in old:
            del self.alerted[k]

        # Nettoie recent_sells
        for mint in list(self.recent_sells.keys()):
            self.recent_sells[mint] = [
                s for s in self.recent_sells[mint]
                if s["timestamp"] > cutoff_sells
            ]
            if not self.recent_sells[mint]:
                del self.recent_sells[mint]

    def get_stats(self) -> dict:
        return {
            "alpha_wallets":     len(self.alpha_wallets),
            "sells_detected":    self.sells_detected,
            "alpha_sells":       self.alpha_sells,
            "giga_sells":        self.giga_sells,
            "cascades_found":    self.cascades_found,
            "recent_sells":      len(self.recent_sells),
        }