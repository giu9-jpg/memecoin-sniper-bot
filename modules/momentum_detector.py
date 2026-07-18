# modules/momentum_detector.py v1.1
"""
Momentum Detector v1.1 — Seuils CALIBRÉS
Détecte les tokens qui pumpent en temps réel
Version plus agressive pour capter les tokens comme NEEGY (+443%)

Sources : DexScreener
Scan    : 60 secondes
"""

import aiohttp
import asyncio
import time
from utils.logger import get_logger

logger = get_logger("momentum")


class MomentumDetector:

    # ════════════════════════════════════════
    # SEUILS DE DÉTECTION v1.1 (baissés)
    # ════════════════════════════════════════
    THRESHOLDS = {
        "5m":  50,    # +50% en 5 min (avant 100)
        "1h":  100,   # +100% en 1h (avant 200)
        "6h":  200,   # +200% en 6h (avant 500)
        "24h": 300,   # +300% en 24h (avant 1000)
    }

    # Filtres sécurité minimum
    MIN_LIQUIDITY = 10_000    # $10K liquidité
    MIN_HOLDERS   = 200       # 200 holders (pas vérifié en pratique)
    MIN_VOLUME    = 100_000   # $100K volume 24h
    MIN_TXNS_1H   = 50        # 50 txns/1h (avant 100)

    # Anti-doublon
    ALERT_COOLDOWN = 3600     # 1h avant réalerte

    def __init__(self, alert_callback):
        self.alert_callback = alert_callback
        self.session        = None
        self.running        = False
        self.alerted        = {}   # {mint: timestamp}
        self.tokens_scanned = 0
        self.momentum_found = 0

    async def start(self):
        """Démarre la boucle de scan"""
        self.session = aiohttp.ClientSession()
        self.running = True
        logger.info("🔥 MomentumDetector v1.1 démarré (scan 60s)")
        logger.info(
            f"   Seuils : 5m={self.THRESHOLDS['5m']}% | "
            f"1h={self.THRESHOLDS['1h']}% | "
            f"6h={self.THRESHOLDS['6h']}% | "
            f"24h={self.THRESHOLDS['24h']}%"
        )
        asyncio.create_task(self._scan_loop())

    async def stop(self):
        """Arrête proprement"""
        self.running = False
        if self.session:
            await self.session.close()
        logger.info("🔥 MomentumDetector arrêté")

    async def _scan_loop(self):
        """Boucle principale de scan"""
        while self.running:
            try:
                await self._scan_dexscreener()
                self._cleanup_old_alerts()
            except Exception as e:
                logger.error(f"Momentum scan error : {e}")
            await asyncio.sleep(60)

    async def _scan_dexscreener(self):
        """Scan DexScreener via 3 endpoints pour maximiser la couverture"""

        # 3 endpoints pour chopper différentes catégories de tokens
        endpoints = [
            "https://api.dexscreener.com/latest/dex/search?q=SOL",
            "https://api.dexscreener.com/latest/dex/search?q=raydium",
            "https://api.dexscreener.com/latest/dex/search?q=pump",
        ]

        all_pairs = []
        seen_mints = set()

        for url in endpoints:
            try:
                async with self.session.get(url, timeout=10) as r:
                    if r.status != 200:
                        continue
                    data = await r.json()

                pairs = data.get("pairs", [])
                for p in pairs:
                    if p.get("chainId") != "solana":
                        continue
                    mint = p.get("baseToken", {}).get("address")
                    if mint and mint not in seen_mints:
                        seen_mints.add(mint)
                        all_pairs.append(p)

            except asyncio.TimeoutError:
                logger.debug(f"Momentum : timeout sur {url}")
            except Exception as e:
                logger.debug(f"Momentum endpoint error : {e}")

        self.tokens_scanned += len(all_pairs)
        logger.debug(f"🔥 Momentum : {len(all_pairs)} pairs Solana scannés")

        for pair in all_pairs:
            await self._check_momentum(pair)

    async def _check_momentum(self, pair: dict):
        """Vérifie si un pair a du momentum et déclenche une alerte"""
        try:
            mint = pair.get("baseToken", {}).get("address")
            if not mint:
                return

            # Anti-doublon
            if mint in self.alerted:
                elapsed = time.time() - self.alerted[mint]
                if elapsed < self.ALERT_COOLDOWN:
                    return

            # ════════════════════════════════════════
            # EXTRACTION DES DONNÉES
            # ════════════════════════════════════════
            price_change = pair.get("priceChange", {})
            liquidity    = pair.get("liquidity", {}).get("usd", 0)
            volume_24h   = pair.get("volume", {}).get("h24", 0)
            txns         = pair.get("txns", {})
            mc           = pair.get("marketCap", 0) or pair.get("fdv", 0)

            change_5m  = price_change.get("m5",  0) or 0
            change_1h  = price_change.get("h1",  0) or 0
            change_6h  = price_change.get("h6",  0) or 0
            change_24h = price_change.get("h24", 0) or 0

            txns_1h = 0
            if txns.get("h1"):
                txns_1h = (txns["h1"].get("buys", 0) +
                           txns["h1"].get("sells", 0))

            # ════════════════════════════════════════
            # FILTRES SÉCURITÉ MINIMUM
            # ════════════════════════════════════════
            if liquidity  < self.MIN_LIQUIDITY: return
            if volume_24h < self.MIN_VOLUME:    return
            if txns_1h    < self.MIN_TXNS_1H:   return

            # ════════════════════════════════════════
            # DÉTECTION DU MOMENTUM
            # ════════════════════════════════════════
            triggered   = None
            trigger_pct = 0

            if change_5m  >= self.THRESHOLDS["5m"]:
                triggered   = "5m"
                trigger_pct = change_5m
            elif change_1h  >= self.THRESHOLDS["1h"]:
                triggered   = "1h"
                trigger_pct = change_1h
            elif change_6h  >= self.THRESHOLDS["6h"]:
                triggered   = "6h"
                trigger_pct = change_6h
            elif change_24h >= self.THRESHOLDS["24h"]:
                triggered   = "24h"
                trigger_pct = change_24h

            if not triggered:
                return

            # ════════════════════════════════════════
            # MOMENTUM DÉTECTÉ !
            # ════════════════════════════════════════
            self.alerted[mint] = time.time()
            self.momentum_found += 1

            symbol = pair.get("baseToken", {}).get("symbol", "?")
            name   = pair.get("baseToken", {}).get("name",   "?")

            token_data = {
                "mint":        mint,
                "symbol":      symbol,
                "name":        name,
                "trigger":     triggered,
                "trigger_pct": trigger_pct,
                "change_5m":   change_5m,
                "change_1h":   change_1h,
                "change_6h":   change_6h,
                "change_24h":  change_24h,
                "liquidity":   liquidity,
                "volume_24h":  volume_24h,
                "market_cap":  mc,
                "txns_1h":     txns_1h,
                "dex_url":     pair.get("url", ""),
                "source":      "momentum",
            }

            logger.info(
                f"🔥 MOMENTUM détecté : ${symbol} "
                f"+{trigger_pct:.0f}% en {triggered} | "
                f"MC ${mc/1000:.0f}K | Liq ${liquidity/1000:.0f}K | "
                f"Vol ${volume_24h/1000:.0f}K"
            )

            # Callback vers main.py
            if self.alert_callback:
                await self.alert_callback(token_data)

        except Exception as e:
            logger.error(f"Momentum check error : {e}")

    def _cleanup_old_alerts(self):
        """Nettoie les anciennes alertes (> 2h)"""
        now = time.time()
        old = [k for k, v in self.alerted.items() if now - v > 7200]
        for k in old:
            del self.alerted[k]

    def get_stats(self):
        """Statistiques pour dashboard/commandes"""
        return {
            "scanned":  self.tokens_scanned,
            "momentum": self.momentum_found,
            "alerted":  len(self.alerted),
        }