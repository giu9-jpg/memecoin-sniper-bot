# modules/bull_run_analyzer.py v1.0
"""
Bull Run Analyzer
Scanne les tokens Solana en continu et enregistre
tous ceux qui ont fait un vrai bull run (+500% ou plus).

Analyse les patterns communs :
  - Heure de la journée
  - Jour de la semaine
  - Market cap au démarrage
  - Liquidité au démarrage
  - Buy/sell ratio
  - Volume dans la première heure
  - Vitesse du pump

Génère des suggestions d'optimisation automatiques.
"""

import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone
from collections import Counter
from utils.logger import get_logger

logger = get_logger("bull_analyzer")


class BullRunAnalyzer:

    # ════════════════════════════════════════
    # SEUILS DE DÉTECTION D'UN VRAI BULL RUN
    # ════════════════════════════════════════
    MIN_BULL_PCT_24H = 500     # +500% en 24h = vrai bull
    MIN_LIQUIDITY    = 5_000   # $5K min pour être crédible
    MIN_VOLUME_24H   = 100_000 # $100K min pour être un vrai bull

    # Cycle de scan
    SCAN_INTERVAL    = 300     # 5 minutes
    DATA_FILE        = "data/bulls_history.json"
    MAX_HISTORY      = 1000    # Garde les 1000 derniers bulls

    def __init__(self):
        self.session = None
        self.running = False
        self.bulls = []       # Historique en mémoire
        self.seen_bulls = set()

        # Stats runtime
        self.tokens_scanned = 0
        self.bulls_detected = 0
        self.last_scan = 0

        self._load_data()

    async def start(self):
        """Démarre l'analyzer en tâche de fond"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )
        self.running = True
        logger.info(
            f"🎯 BullRunAnalyzer démarré "
            f"(seuil: +{self.MIN_BULL_PCT_24H}% en 24h)"
        )
        logger.info(
            f"   Historique chargé : {len(self.bulls)} bulls"
        )
        asyncio.create_task(self._scan_loop())

    async def stop(self):
        """Arrêt propre"""
        self.running = False
        self._save_data()
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("🎯 BullRunAnalyzer arrêté")

    # ════════════════════════════════════════
    # BOUCLE PRINCIPALE
    # ════════════════════════════════════════

    async def _scan_loop(self):
        """Scan périodique des tokens Solana"""
        while self.running:
            try:
                await self._scan_dexscreener()
                self.last_scan = time.time()

                # Sauvegarde toutes les 15 min
                if len(self.bulls) % 5 == 0 and self.bulls:
                    self._save_data()

            except Exception as e:
                logger.error(f"BullAnalyzer scan error : {e}")

            await asyncio.sleep(self.SCAN_INTERVAL)

    async def _scan_dexscreener(self):
        """Scan multiple endpoints DexScreener"""
        endpoints = [
            "https://api.dexscreener.com/latest/dex/search?q=SOL",
            "https://api.dexscreener.com/latest/dex/search?q=raydium",
            "https://api.dexscreener.com/latest/dex/search?q=pump",
            "https://api.dexscreener.com/latest/dex/search?q=WSOL",
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
                logger.debug(f"BullAnalyzer endpoint error : {e}")

        self.tokens_scanned += len(all_pairs)

        for pair in all_pairs:
            await self._analyze_pair(pair)

    async def _analyze_pair(self, pair: dict):
        """Analyse un pair pour détecter un bull run"""
        try:
            base = pair.get("baseToken", {})
            mint = base.get("address")
            if not mint:
                return

            # Déjà vu
            if mint in self.seen_bulls:
                return

            # Extraction données
            price_change = pair.get("priceChange", {}) or {}
            change_24h = price_change.get("h24", 0) or 0

            # Filtre : vrai bull run
            if change_24h < self.MIN_BULL_PCT_24H:
                return

            liquidity  = pair.get("liquidity", {}).get("usd", 0) or 0
            volume_24h = pair.get("volume", {}).get("h24", 0) or 0

            if liquidity < self.MIN_LIQUIDITY:
                return
            if volume_24h < self.MIN_VOLUME_24H:
                return

            # Données complètes
            volume_1h  = pair.get("volume", {}).get("h1", 0) or 0
            volume_6h  = pair.get("volume", {}).get("h6", 0) or 0
            mc         = pair.get("marketCap", 0) or pair.get("fdv", 0) or 0

            txns = pair.get("txns", {}) or {}
            buys_1h  = txns.get("h1", {}).get("buys", 0) if txns.get("h1") else 0
            sells_1h = txns.get("h1", {}).get("sells", 0) if txns.get("h1") else 0
            txns_1h  = buys_1h + sells_1h
            buy_ratio = round(buys_1h / txns_1h * 100, 1) if txns_1h > 0 else 0

            buys_24h  = txns.get("h24", {}).get("buys", 0) if txns.get("h24") else 0
            sells_24h = txns.get("h24", {}).get("sells", 0) if txns.get("h24") else 0

            # Estimation MC au démarrage
            change_ratio = 1 + (change_24h / 100)
            mc_start = mc / change_ratio if change_ratio > 0 else mc

            # Timestamp
            now = datetime.now(timezone.utc)
            created_ts = pair.get("pairCreatedAt", 0)
            if created_ts:
                created_dt = datetime.fromtimestamp(
                    created_ts / 1000, tz=timezone.utc
                )
                age_hours = (now - created_dt).total_seconds() / 3600
            else:
                created_dt = now
                age_hours = 0

            # Enregistrement
            bull = {
                "mint":         mint,
                "symbol":       base.get("symbol", "?"),
                "name":         base.get("name",   "?"),
                "detected_at":  now.isoformat(),
                "hour_utc":     now.hour,
                "day_of_week":  now.strftime("%A"),
                "age_hours":    round(age_hours, 1),
                "change_24h":   round(change_24h, 0),
                "change_6h":    round(price_change.get("h6", 0) or 0, 0),
                "change_1h":    round(price_change.get("h1", 0) or 0, 0),
                "liquidity":    round(liquidity, 0),
                "volume_24h":   round(volume_24h, 0),
                "volume_1h":    round(volume_1h,  0),
                "volume_6h":    round(volume_6h,  0),
                "market_cap":   round(mc, 0),
                "mc_estimated_start": round(mc_start, 0),
                "buys_1h":      buys_1h,
                "sells_1h":     sells_1h,
                "txns_1h":      txns_1h,
                "buy_ratio_1h": buy_ratio,
                "buys_24h":     buys_24h,
                "sells_24h":    sells_24h,
                "dex_url":      pair.get("url", ""),
            }

            self.bulls.append(bull)
            self.seen_bulls.add(mint)
            self.bulls_detected += 1

            # Garde max en mémoire
            if len(self.bulls) > self.MAX_HISTORY:
                self.bulls = self.bulls[-self.MAX_HISTORY:]

            logger.info(
                f"🎯 BULL détecté : ${bull['symbol']} "
                f"+{change_24h:.0f}% | "
                f"MC ${mc/1000:.0f}K | "
                f"Age {age_hours:.1f}h | "
                f"BuyRatio {buy_ratio}%"
            )

        except Exception as e:
            logger.error(f"BullAnalyzer analyze error : {e}")

    # ════════════════════════════════════════
    # PERSISTENCE
    # ════════════════════════════════════════

    def _load_data(self):
        """Charge l'historique depuis le fichier"""
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.bulls = data.get("bulls", [])
                    self.seen_bulls = set(b["mint"] for b in self.bulls)
                    logger.info(
                        f"🎯 {len(self.bulls)} bulls chargés depuis "
                        f"{self.DATA_FILE}"
                    )
        except Exception as e:
            logger.error(f"BullAnalyzer load error : {e}")
            self.bulls = []
            self.seen_bulls = set()

    def _save_data(self):
        """Sauvegarde l'historique"""
        try:
            os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "bulls": self.bulls,
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"BullAnalyzer save error : {e}")

    # ════════════════════════════════════════
    # ANALYSES ET STATISTIQUES
    # ════════════════════════════════════════

    def get_stats(self, days: int = 7) -> dict:
        """Retourne les statistiques des bulls des N derniers jours"""
        if not self.bulls:
            return {"total": 0, "message": "Pas encore de bulls détectés"}

        # Filtre par période
        cutoff = time.time() - (days * 86400)
        recent = []
        for b in self.bulls:
            try:
                dt = datetime.fromisoformat(b["detected_at"])
                if dt.timestamp() >= cutoff:
                    recent.append(b)
            except Exception:
                continue

        if not recent:
            return {
                "total": 0,
                "message": f"Pas de bulls dans les derniers {days}j"
            }

        # Analyses
        hours     = Counter(b["hour_utc"] for b in recent)
        days_wk   = Counter(b["day_of_week"] for b in recent)

        # MC buckets
        mc_buckets = Counter()
        for b in recent:
            mc = b.get("market_cap", 0)
            if mc < 100_000:
                mc_buckets["<$100K"] += 1
            elif mc < 500_000:
                mc_buckets["$100K-$500K"] += 1
            elif mc < 1_000_000:
                mc_buckets["$500K-$1M"] += 1
            elif mc < 5_000_000:
                mc_buckets["$1M-$5M"] += 1
            else:
                mc_buckets[">$5M"] += 1

        # Liquidité buckets
        liq_buckets = Counter()
        for b in recent:
            liq = b.get("liquidity", 0)
            if liq < 20_000:
                liq_buckets["<$20K"] += 1
            elif liq < 50_000:
                liq_buckets["$20K-$50K"] += 1
            elif liq < 100_000:
                liq_buckets["$50K-$100K"] += 1
            elif liq < 500_000:
                liq_buckets["$100K-$500K"] += 1
            else:
                liq_buckets[">$500K"] += 1

        # Buy ratio buckets
        br_buckets = Counter()
        for b in recent:
            br = b.get("buy_ratio_1h", 0)
            if br < 50:
                br_buckets["<50%"] += 1
            elif br < 60:
                br_buckets["50-60%"] += 1
            elif br < 70:
                br_buckets["60-70%"] += 1
            elif br < 80:
                br_buckets["70-80%"] += 1
            else:
                br_buckets[">80%"] += 1

        # Moyennes
        avg_liq  = sum(b["liquidity"]  for b in recent) / len(recent)
        avg_mc   = sum(b["market_cap"] for b in recent) / len(recent)
        avg_vol  = sum(b["volume_24h"] for b in recent) / len(recent)
        avg_gain = sum(b["change_24h"] for b in recent) / len(recent)

        return {
            "total":       len(recent),
            "days":        days,
            "hours":       hours.most_common(5),
            "days_week":   days_wk.most_common(3),
            "mc_buckets":  mc_buckets.most_common(),
            "liq_buckets": liq_buckets.most_common(),
            "br_buckets":  br_buckets.most_common(),
            "avg_liq":     round(avg_liq, 0),
            "avg_mc":      round(avg_mc, 0),
            "avg_vol":     round(avg_vol, 0),
            "avg_gain":    round(avg_gain, 0),
            "top_5":       sorted(
                recent,
                key=lambda x: x["change_24h"],
                reverse=True
            )[:5],
        }

    def get_recommendations(self) -> list:
        """Génère des recommandations d'optimisation"""
        stats = self.get_stats(days=7)
        recos = []

        if stats["total"] < 10:
            recos.append(
                f"⏳ Pas assez de données ({stats['total']} bulls). "
                f"Attends au moins 3 jours."
            )
            return recos

        # Reco 1 : heures
        if stats.get("hours"):
            top_hour, top_count = stats["hours"][0]
            pct = round(top_count / stats["total"] * 100)
            recos.append(
                f"⏰ Meilleure heure : {top_hour}h UTC "
                f"({pct}% des bulls)"
            )

        # Reco 2 : MC sweet spot
        if stats.get("mc_buckets"):
            top_mc, top_count = stats["mc_buckets"][0]
            pct = round(top_count / stats["total"] * 100)
            recos.append(
                f"💰 MC optimal : {top_mc} "
                f"({pct}% des bulls)"
            )

        # Reco 3 : liquidité
        if stats.get("liq_buckets"):
            top_liq, top_count = stats["liq_buckets"][0]
            pct = round(top_count / stats["total"] * 100)
            recos.append(
                f"💧 Liquidité sweet spot : {top_liq} "
                f"({pct}% des bulls)"
            )

        # Reco 4 : buy ratio
        if stats.get("br_buckets"):
            top_br, top_count = stats["br_buckets"][0]
            pct = round(top_count / stats["total"] * 100)
            recos.append(
                f"🟢 Buy Ratio typique : {top_br} "
                f"({pct}% des bulls)"
            )

        # Reco 5 : jour
        if stats.get("days_week"):
            top_day, top_count = stats["days_week"][0]
            pct = round(top_count / stats["total"] * 100)
            recos.append(
                f"📅 Meilleur jour : {top_day} ({pct}%)"
            )

        return recos