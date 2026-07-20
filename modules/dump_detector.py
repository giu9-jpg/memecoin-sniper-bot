# modules/dump_detector.py v1.0
"""
Dump Detector
Détecte les flash crashes en temps réel sur Solana.

Signaux détectés :
  - Chute rapide (-30%+ en 5 min)
  - Volume de vente massif
  - Buy ratio très faible
  - Whales qui sortent
  - Cascade de sells

Alertes séparées des alertes momentum.
"""

import aiohttp
import asyncio
import time
from utils.logger import get_logger

logger = get_logger("dump_detector")


class DumpDetector:

    # ════════════════════════════════════════
    # SEUILS DE DÉTECTION
    # ════════════════════════════════════════

    # Chutes considérées comme "dump"
    THRESHOLDS = {
        "5m":  -30,   # -30% en 5 min = flash crash
        "1h":  -50,   # -50% en 1h = gros dump
        "6h":  -70,   # -70% en 6h = collapse
    }

    # Filtres qualité
    MIN_LIQUIDITY   = 20_000   # Ignore les tokens morts
    MIN_VOLUME_1H   = 50_000   # Doit avoir du volume actif
    MIN_TXNS_1H     = 100      # Assez de transactions

    # Signaux de dump
    LOW_BUY_RATIO   = 30       # < 30% buys = mauvais
    SELL_VOL_RATIO  = 0.70     # 70%+ de volume en vente = dump

    # Anti-doublon
    ALERT_COOLDOWN  = 3600     # 1h avant réalerte

    # Cycle scan
    SCAN_INTERVAL   = 90       # 90 secondes

    def __init__(self, alert_callback):
        self.alert_callback = alert_callback
        self.session = None
        self.running = False
        self.alerted = {}   # {mint: timestamp}
        self.tokens_scanned = 0
        self.dumps_detected = 0

    async def start(self):
        """Démarre le scan"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self.running = True
        logger.info(
            f"📉 DumpDetector démarré (scan {self.SCAN_INTERVAL}s)"
        )
        logger.info(
            f"   Seuils : 5m={self.THRESHOLDS['5m']}% | "
            f"1h={self.THRESHOLDS['1h']}% | "
            f"6h={self.THRESHOLDS['6h']}%"
        )
        asyncio.create_task(self._scan_loop())

    async def stop(self):
        """Arrêt propre"""
        self.running = False
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("📉 DumpDetector arrêté")

    async def _scan_loop(self):
        """Boucle principale"""
        while self.running:
            try:
                await self._scan_dexscreener()
                self._cleanup_old_alerts()
            except Exception as e:
                logger.error(f"DumpDetector scan error : {e}")
            await asyncio.sleep(self.SCAN_INTERVAL)

    async def _scan_dexscreener(self):
        """Scan DexScreener pour dumps"""
        endpoints = [
            "https://api.dexscreener.com/latest/dex/search?q=SOL",
            "https://api.dexscreener.com/latest/dex/search?q=raydium",
            "https://api.dexscreener.com/latest/dex/search?q=pump",
        ]

        all_pairs = []
        seen_mints = set()

        for url in endpoints:
            try:
                async with self.session.get(url) as r:
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
            except Exception as e:
                logger.debug(f"DumpDetector endpoint error : {e}")

        self.tokens_scanned += len(all_pairs)

        for pair in all_pairs:
            await self._check_dump(pair)

    async def _check_dump(self, pair: dict):
        """Vérifie si un pair est en dump"""
        try:
            mint = pair.get("baseToken", {}).get("address")
            if not mint:
                return

            # Anti-doublon
            if mint in self.alerted:
                elapsed = time.time() - self.alerted[mint]
                if elapsed < self.ALERT_COOLDOWN:
                    return

            # Extraction
            price_change = pair.get("priceChange", {}) or {}
            liquidity   = pair.get("liquidity", {}).get("usd", 0) or 0
            volume_1h   = pair.get("volume", {}).get("h1", 0) or 0
            volume_24h  = pair.get("volume", {}).get("h24", 0) or 0
            mc          = pair.get("marketCap", 0) or pair.get("fdv", 0) or 0

            change_5m  = price_change.get("m5", 0) or 0
            change_1h  = price_change.get("h1", 0) or 0
            change_6h  = price_change.get("h6", 0) or 0
            change_24h = price_change.get("h24", 0) or 0

            txns = pair.get("txns", {}) or {}
            buys_1h  = txns.get("h1", {}).get("buys", 0) if txns.get("h1") else 0
            sells_1h = txns.get("h1", {}).get("sells", 0) if txns.get("h1") else 0
            txns_1h = buys_1h + sells_1h

            buys_5m  = txns.get("m5", {}).get("buys", 0) if txns.get("m5") else 0
            sells_5m = txns.get("m5", {}).get("sells", 0) if txns.get("m5") else 0

            # Filtres qualité
            if liquidity < self.MIN_LIQUIDITY:
                return
            if volume_1h < self.MIN_VOLUME_1H:
                return
            if txns_1h < self.MIN_TXNS_1H:
                return

            # Détection dump
            triggered = None
            trigger_pct = 0

            if change_5m <= self.THRESHOLDS["5m"]:
                triggered = "5m"
                trigger_pct = change_5m
            elif change_1h <= self.THRESHOLDS["1h"]:
                triggered = "1h"
                trigger_pct = change_1h
            elif change_6h <= self.THRESHOLDS["6h"]:
                triggered = "6h"
                trigger_pct = change_6h

            if not triggered:
                return

            # Analyse buy ratio
            buy_ratio_1h = round(buys_1h / txns_1h * 100, 1) if txns_1h > 0 else 50

            # Contexte : token pumpait avant ?
            was_pumping = change_24h > 50 and (
                change_5m < -20 or change_1h < -30
            )

            # Sévérité
            severity = "CRASH"
            if trigger_pct <= -60:
                severity = "COLLAPSE"
            elif trigger_pct <= -40:
                severity = "MAJOR_DUMP"
            elif buy_ratio_1h < 20:
                severity = "PANIC_SELL"

            # Cascade de sells détectée
            cascade = (
                sells_5m > buys_5m * 3
                and sells_1h > buys_1h * 2
            )

            # Enregistrement
            self.alerted[mint] = time.time()
            self.dumps_detected += 1

            symbol = pair.get("baseToken", {}).get("symbol", "?")
            name = pair.get("baseToken", {}).get("name", "?")

            dump_data = {
                "mint":         mint,
                "symbol":       symbol,
                "name":         name,
                "trigger":      triggered,
                "trigger_pct":  trigger_pct,
                "severity":     severity,
                "change_5m":    change_5m,
                "change_1h":    change_1h,
                "change_6h":    change_6h,
                "change_24h":   change_24h,
                "liquidity":    liquidity,
                "volume_1h":    volume_1h,
                "volume_24h":   volume_24h,
                "market_cap":   mc,
                "buys_1h":      buys_1h,
                "sells_1h":     sells_1h,
                "buy_ratio_1h": buy_ratio_1h,
                "was_pumping":  was_pumping,
                "cascade":      cascade,
                "dex_url":      pair.get("url", ""),
                "source":       "dump_detector",
            }

            logger.info(
                f"📉 DUMP détecté : ${symbol} "
                f"{trigger_pct:.0f}% en {triggered} | "
                f"Severity: {severity} | "
                f"BuyRatio: {buy_ratio_1h}%"
            )

            # Callback vers main.py
            if self.alert_callback:
                await self.alert_callback(dump_data)

        except Exception as e:
            logger.error(f"Dump check error : {e}")

    def _cleanup_old_alerts(self):
        """Nettoie les vieilles alertes"""
        now = time.time()
        old = [k for k, v in self.alerted.items() if now - v > 7200]
        for k in old:
            del self.alerted[k]

    def get_stats(self) -> dict:
        return {
            "scanned":   self.tokens_scanned,
            "dumps":     self.dumps_detected,
            "alerted":   len(self.alerted),
        }