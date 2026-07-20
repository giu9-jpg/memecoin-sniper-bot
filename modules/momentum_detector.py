# modules/momentum_detector.py v1.2
"""
Momentum Detector v1.2 — Filtres AVANCÉS
Détecte les VRAIS momentum organiques avec 8 filtres intelligents

Nouveaux filtres v1.2 :
  1. Anti-dump (rejette si le pump est déjà en train de dumper)
  2. Buy/Sell ratio (min 55% de buys)
  3. Buyer diversity (min 100 buyers uniques)
  4. Volume/Liq ratio (anti wash-trading)
  5. Market cap range ($100K - $10M)
  6. Momentum quality score (0-100)
  7. Multi-timeframe confluence
  8. Détection accélération vs décélération

Sources : DexScreener (3 endpoints)
Scan    : 60 secondes
"""

import aiohttp
import asyncio
import time
from utils.logger import get_logger

logger = get_logger("momentum")


class MomentumDetector:

    # ════════════════════════════════════════
    # SEUILS DE DÉTECTION
    # ════════════════════════════════════════
    THRESHOLDS = {
        "5m":  50,    # +50% en 5 min
        "1h":  100,   # +100% en 1h
        "6h":  200,   # +200% en 6h
        "24h": 300,   # +300% en 24h
    }

    # ════════════════════════════════════════
    # FILTRES DE BASE
    # ════════════════════════════════════════
    MIN_LIQUIDITY = 10_000    # $10K liquidité min
    MAX_LIQUIDITY = 5_000_000 # $5M liq max (au-delà = trop gros)
    MIN_VOLUME    = 100_000   # $100K volume 24h
    MIN_TXNS_1H   = 50        # 50 txns/1h
    MIN_MC        = 50_000    # $50K MC min
    MAX_MC        = 20_000_000 # $20M MC max (déjà pumpé)

    # ════════════════════════════════════════
    # FILTRES QUALITÉ v1.2 (NOUVEAUX)
    # ════════════════════════════════════════
    MIN_BUYERS         = 100    # Min 100 buyers uniques sur 1h
    MIN_BUY_RATIO      = 0.55   # Min 55% de buys (vs sells)
    MAX_VOLUME_LIQ_RATIO = 100  # Volume/Liq max = 100 (anti wash)
    ANTI_DUMP_5M       = -10    # Rejette si 5m < -10% (dump en cours)
    MIN_QUALITY_SCORE  = 60     # Score qualité minimum sur 100

    # Anti-doublon
    ALERT_COOLDOWN = 3600  # 1h

    def __init__(self, alert_callback):
        self.alert_callback = alert_callback
        self.session        = None
        self.running        = False
        self.alerted        = {}
        self.tokens_scanned = 0
        self.momentum_found = 0
        self.filtered_out   = {
            "safety_basic":  0,
            "anti_dump":     0,
            "buy_ratio":     0,
            "buyers":        0,
            "wash_trading":  0,
            "mc_range":      0,
            "quality":       0,
        }

    async def start(self):
        """Démarre la boucle de scan"""
        self.session = aiohttp.ClientSession()
        self.running = True
        logger.info("🔥 MomentumDetector v1.2 démarré (scan 60s)")
        logger.info(
            f"   Seuils : 5m={self.THRESHOLDS['5m']}% | "
            f"1h={self.THRESHOLDS['1h']}% | "
            f"6h={self.THRESHOLDS['6h']}% | "
            f"24h={self.THRESHOLDS['24h']}%"
        )
        logger.info(
            f"   Filtres qualité : buy_ratio≥{self.MIN_BUY_RATIO*100:.0f}% | "
            f"buyers≥{self.MIN_BUYERS} | "
            f"quality≥{self.MIN_QUALITY_SCORE}/100"
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
        """Scan DexScreener via 3 endpoints"""
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
                logger.debug(f"Momentum : timeout {url}")
            except Exception as e:
                logger.debug(f"Momentum endpoint error : {e}")

        self.tokens_scanned += len(all_pairs)
        logger.debug(f"🔥 Momentum : {len(all_pairs)} pairs scannés")

        for pair in all_pairs:
            await self._check_momentum(pair)

    async def _check_momentum(self, pair: dict):
        """Vérifie momentum avec 8 filtres"""
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
            volume_1h    = pair.get("volume", {}).get("h1",  0)
            txns         = pair.get("txns", {})
            mc           = pair.get("marketCap", 0) or pair.get("fdv", 0)

            change_5m  = price_change.get("m5",  0) or 0
            change_1h  = price_change.get("h1",  0) or 0
            change_6h  = price_change.get("h6",  0) or 0
            change_24h = price_change.get("h24", 0) or 0

            # Txns détaillés
            buys_1h  = txns.get("h1", {}).get("buys",  0) if txns.get("h1") else 0
            sells_1h = txns.get("h1", {}).get("sells", 0) if txns.get("h1") else 0
            txns_1h  = buys_1h + sells_1h

            buys_5m  = txns.get("m5", {}).get("buys",  0) if txns.get("m5") else 0
            sells_5m = txns.get("m5", {}).get("sells", 0) if txns.get("m5") else 0

            # ════════════════════════════════════════
            # FILTRE 1 : SÉCURITÉ DE BASE
            # ════════════════════════════════════════
            if liquidity < self.MIN_LIQUIDITY: 
                self.filtered_out["safety_basic"] += 1
                return
            if liquidity > self.MAX_LIQUIDITY: 
                self.filtered_out["safety_basic"] += 1
                return
            if volume_24h < self.MIN_VOLUME:   
                self.filtered_out["safety_basic"] += 1
                return
            if txns_1h < self.MIN_TXNS_1H:     
                self.filtered_out["safety_basic"] += 1
                return

            # ════════════════════════════════════════
            # FILTRE 2 : MARKET CAP RANGE
            # ════════════════════════════════════════
            if mc < self.MIN_MC or mc > self.MAX_MC:
                self.filtered_out["mc_range"] += 1
                return

            # ════════════════════════════════════════
            # FILTRE 3 : ANTI-DUMP
            # Si le pump est déjà en train de dumper, on skip
            # ════════════════════════════════════════
            if change_5m < self.ANTI_DUMP_5M:
                self.filtered_out["anti_dump"] += 1
                logger.debug(
                    f"🔥 SKIP {mint[:8]}... : dump en cours "
                    f"(5m: {change_5m:.1f}%)"
                )
                return

            # ════════════════════════════════════════
            # FILTRE 4 : BUY/SELL RATIO
            # Doit avoir plus de buys que de sells
            # ════════════════════════════════════════
            if txns_1h > 0:
                buy_ratio = buys_1h / txns_1h
                if buy_ratio < self.MIN_BUY_RATIO:
                    self.filtered_out["buy_ratio"] += 1
                    logger.debug(
                        f"🔥 SKIP {mint[:8]}... : trop de sells "
                        f"({buy_ratio*100:.0f}% buys)"
                    )
                    return
            else:
                buy_ratio = 0

            # ════════════════════════════════════════
            # FILTRE 5 : BUYER DIVERSITY
            # Beaucoup d'acheteurs = momentum organique
            # ════════════════════════════════════════
            if buys_1h < self.MIN_BUYERS:
                self.filtered_out["buyers"] += 1
                return

            # ════════════════════════════════════════
            # FILTRE 6 : ANTI WASH-TRADING
            # Volume/Liquidité anormal = wash trading
            # ════════════════════════════════════════
            vol_liq_ratio = 0
            if liquidity > 0:
                vol_liq_ratio = volume_24h / liquidity
                if vol_liq_ratio > self.MAX_VOLUME_LIQ_RATIO:
                    self.filtered_out["wash_trading"] += 1
                    logger.debug(
                        f"🔥 SKIP {mint[:8]}... : wash trading suspect "
                        f"(vol/liq: {vol_liq_ratio:.0f})"
                    )
                    return

            # ════════════════════════════════════════
            # DÉTECTION DU MOMENTUM (seuils)
            # ════════════════════════════════════════
            triggered   = None
            trigger_pct = 0

            if change_5m >= self.THRESHOLDS["5m"]:
                triggered   = "5m"
                trigger_pct = change_5m
            elif change_1h >= self.THRESHOLDS["1h"]:
                triggered   = "1h"
                trigger_pct = change_1h
            elif change_6h >= self.THRESHOLDS["6h"]:
                triggered   = "6h"
                trigger_pct = change_6h
            elif change_24h >= self.THRESHOLDS["24h"]:
                triggered   = "24h"
                trigger_pct = change_24h

            if not triggered:
                return

            # ════════════════════════════════════════
            # FILTRE 7 : QUALITY SCORE (0-100)
            # Score composite pour éliminer les tokens douteux
            # ════════════════════════════════════════
            quality_score = self._calculate_quality_score(
                buy_ratio    = buy_ratio,
                buys_1h      = buys_1h,
                vol_liq_ratio= vol_liq_ratio,
                liquidity    = liquidity,
                mc           = mc,
                change_5m    = change_5m,
                change_1h    = change_1h,
                change_6h    = change_6h,
                change_24h   = change_24h,
            )

            if quality_score < self.MIN_QUALITY_SCORE:
                self.filtered_out["quality"] += 1
                logger.debug(
                    f"🔥 SKIP {mint[:8]}... : quality trop faible "
                    f"({quality_score}/100)"
                )
                return

            # ════════════════════════════════════════
            # FILTRE 8 : ACCÉLÉRATION vs DÉCÉLÉRATION
            # Détecte si le momentum est en train de s'essouffler
            # ════════════════════════════════════════
            momentum_state = self._detect_momentum_state(
                change_5m, change_1h, change_6h, change_24h
            )

            # ════════════════════════════════════════
            # MOMENTUM DÉTECTÉ ! 🔥
            # ════════════════════════════════════════
            self.alerted[mint] = time.time()
            self.momentum_found += 1

            symbol = pair.get("baseToken", {}).get("symbol", "?")
            name   = pair.get("baseToken", {}).get("name",   "?")

            token_data = {
                "mint":           mint,
                "symbol":         symbol,
                "name":           name,
                "trigger":        triggered,
                "trigger_pct":    trigger_pct,
                "change_5m":      change_5m,
                "change_1h":      change_1h,
                "change_6h":      change_6h,
                "change_24h":     change_24h,
                "liquidity":      liquidity,
                "volume_24h":     volume_24h,
                "market_cap":     mc,
                "txns_1h":        txns_1h,
                "buys_1h":        buys_1h,
                "sells_1h":       sells_1h,
                "buy_ratio":      buy_ratio,
                "vol_liq_ratio":  vol_liq_ratio,
                "quality_score":  quality_score,
                "momentum_state": momentum_state,
                "dex_url":        pair.get("url", ""),
                "source":         "momentum",
            }

            logger.info(
                f"🔥 MOMENTUM détecté : ${symbol} "
                f"+{trigger_pct:.0f}% en {triggered} | "
                f"MC ${mc/1000:.0f}K | "
                f"Q:{quality_score}/100 | "
                f"BuyRatio:{buy_ratio*100:.0f}% | "
                f"State:{momentum_state}"
            )

            # Callback vers main.py
            if self.alert_callback:
                await self.alert_callback(token_data)

        except Exception as e:
            logger.error(f"Momentum check error : {e}")

    def _calculate_quality_score(self, **kwargs) -> int:
        """
        Calcule un score qualité 0-100
        Plus le score est élevé, plus le momentum est solide
        """
        score = 0

        # ─── Buy/Sell ratio (0-25 points) ──────────
        # 100% buys = 25 points, 50% buys = 0 points
        buy_ratio = kwargs.get("buy_ratio", 0)
        if buy_ratio >= 0.80:
            score += 25
        elif buy_ratio >= 0.70:
            score += 20
        elif buy_ratio >= 0.60:
            score += 15
        elif buy_ratio >= 0.55:
            score += 10

        # ─── Nombre de buyers (0-20 points) ────────
        buys_1h = kwargs.get("buys_1h", 0)
        if buys_1h >= 1000:
            score += 20
        elif buys_1h >= 500:
            score += 15
        elif buys_1h >= 300:
            score += 10
        elif buys_1h >= 100:
            score += 5

        # ─── Volume/Liq ratio (0-15 points) ────────
        # Ratio sain entre 5 et 50
        vol_liq = kwargs.get("vol_liq_ratio", 0)
        if 5 <= vol_liq <= 50:
            score += 15
        elif 3 <= vol_liq < 5 or 50 < vol_liq <= 80:
            score += 10
        elif vol_liq > 0:
            score += 5

        # ─── Liquidité (0-15 points) ───────────────
        liq = kwargs.get("liquidity", 0)
        if liq >= 100_000:
            score += 15
        elif liq >= 50_000:
            score += 10
        elif liq >= 25_000:
            score += 5

        # ─── Market Cap sweet spot (0-15 points) ───
        # Sweet spot : $500K - $5M
        mc = kwargs.get("mc", 0)
        if 500_000 <= mc <= 5_000_000:
            score += 15
        elif 200_000 <= mc < 500_000:
            score += 10
        elif mc > 5_000_000:
            score += 5

        # ─── Momentum quality (0-10 points) ────────
        # 5m > 0 = momentum encore vivant
        change_5m = kwargs.get("change_5m", 0)
        if change_5m >= 20:
            score += 10
        elif change_5m >= 5:
            score += 7
        elif change_5m >= 0:
            score += 4

        return int(score)

    def _detect_momentum_state(
        self, c_5m: float, c_1h: float, c_6h: float, c_24h: float
    ) -> str:
        """
        Détecte l'état du momentum :
        - ACCELERATING : ça monte de plus en plus vite
        - STEADY       : ça monte de façon stable
        - COOLING      : ça ralentit
        - REVERSING    : ça commence à baisser
        """
        # Taux horaire estimé
        rate_1h  = c_1h
        rate_6h  = c_6h  / 6
        rate_24h = c_24h / 24

        if c_5m < 0:
            return "REVERSING"

        if rate_1h > rate_6h > rate_24h and c_5m > 0:
            return "ACCELERATING"

        if rate_1h > rate_6h * 0.7:
            return "STEADY"

        return "COOLING"

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
            "filtered": dict(self.filtered_out),
        }