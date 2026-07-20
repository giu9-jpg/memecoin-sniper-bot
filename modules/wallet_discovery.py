# modules/wallet_discovery.py v1.0
"""
Wallet Discovery
Découvre automatiquement de nouveaux alpha wallets
en analysant qui achète TÔT sur les vrais bulls run.

Comment ça marche :
  1. Pour chaque bull détecté par BullRunAnalyzer
  2. Récupère les premiers acheteurs (early buyers)
  3. Track leur historique de trading
  4. Si un wallet apparaît sur 3+ bulls avec win rate > 60%
  5. Le propose automatiquement comme candidat alpha
"""

import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone
from collections import defaultdict
from utils.logger import get_logger

logger = get_logger("wallet_discovery")


class WalletDiscovery:

    # ════════════════════════════════════════
    # CONFIGURATION
    # ════════════════════════════════════════

    # Seuils pour considérer un wallet comme candidat
    MIN_BULLS_HIT       = 3       # Doit avoir hit 3+ bulls
    MIN_WIN_RATE        = 60      # 60% de win rate min
    EARLY_BUYERS_LIMIT  = 20      # Top 20 premiers acheteurs analysés

    # Fichiers
    DATA_FILE           = "data/discovered_wallets.json"
    CANDIDATES_FILE     = "data/wallet_candidates.json"

    # Cycle de scan
    ANALYSIS_INTERVAL   = 1800    # 30 minutes
    MAX_HISTORY         = 500     # Garde 500 wallets max

    def __init__(self, bull_analyzer):
        """
        bull_analyzer : instance de BullRunAnalyzer
                        pour accéder aux bulls détectés
        """
        self.bull_analyzer = bull_analyzer
        self.session = None
        self.running = False

        # Structure : {wallet_address: {
        #   "bulls_hit": [mint1, mint2, ...],
        #   "first_seen": timestamp,
        #   "total_score": float
        # }}
        self.discovered = {}
        self.analyzed_bulls = set()  # Bulls déjà analysés

        # Stats
        self.candidates_proposed = 0

        self._load_data()

    async def start(self):
        """Démarre le module"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )
        self.running = True
        logger.info(
            f"🔍 WalletDiscovery démarré "
            f"({len(self.discovered)} wallets trackés)"
        )
        asyncio.create_task(self._analysis_loop())

    async def stop(self):
        """Arrêt propre"""
        self.running = False
        self._save_data()
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("🔍 WalletDiscovery arrêté")

    # ════════════════════════════════════════
    # BOUCLE D'ANALYSE
    # ════════════════════════════════════════

    async def _analysis_loop(self):
        """Boucle principale d'analyse"""
        while self.running:
            try:
                await self._analyze_new_bulls()
                self._save_data()
            except Exception as e:
                logger.error(f"WalletDiscovery loop error : {e}")
            await asyncio.sleep(self.ANALYSIS_INTERVAL)

    async def _analyze_new_bulls(self):
        """Analyse les nouveaux bulls détectés"""
        bulls = self.bull_analyzer.bulls

        if not bulls:
            return

        # Filtrer les bulls non analysés
        new_bulls = [
            b for b in bulls
            if b["mint"] not in self.analyzed_bulls
        ]

        if not new_bulls:
            return

        logger.info(
            f"🔍 Analyse de {len(new_bulls)} nouveaux bulls..."
        )

        for bull in new_bulls[:10]:  # Max 10 par cycle
            try:
                await self._analyze_bull(bull)
                self.analyzed_bulls.add(bull["mint"])
            except Exception as e:
                logger.debug(f"Bull analysis error : {e}")

        # Générer candidats
        candidates = self._generate_candidates()
        if candidates:
            self._save_candidates(candidates)

    async def _analyze_bull(self, bull: dict):
        """Analyse un bull spécifique pour trouver les early buyers"""
        try:
            mint = bull["mint"]

            # Récupère les early buyers via Solscan API
            early_buyers = await self._fetch_early_buyers(mint)

            if not early_buyers:
                return

            logger.debug(
                f"🔍 Bull ${bull.get('symbol', '?')} : "
                f"{len(early_buyers)} early buyers"
            )

            # Track chaque wallet
            for wallet in early_buyers:
                self._track_wallet(wallet, mint, bull)

        except Exception as e:
            logger.debug(f"Analyze bull error : {e}")

    async def _fetch_early_buyers(self, mint: str) -> list:
        """
        Récupère les premiers acheteurs d'un token.
        Utilise l'API Solscan (gratuit).
        """
        try:
            # Solscan API - transfers du token
            url = (
                f"https://public-api.solscan.io/token/transfers"
                f"?tokenAddress={mint}"
                f"&limit={self.EARLY_BUYERS_LIMIT}"
                f"&offset=0"
            )

            headers = {
                "accept": "application/json",
                "User-Agent": "Mozilla/5.0",
            }

            async with self.session.get(
                url, headers=headers
            ) as resp:
                if resp.status != 200:
                    return []

                data = await resp.json()

            # Extract unique buyer wallets
            buyers = set()
            transfers = data if isinstance(data, list) else data.get("data", [])

            for tx in transfers[:self.EARLY_BUYERS_LIMIT]:
                dst = tx.get("dst") or tx.get("destination")
                if dst and len(dst) >= 32:
                    buyers.add(dst)

            return list(buyers)

        except Exception as e:
            logger.debug(f"Fetch early buyers error : {e}")
            return []

    def _track_wallet(self, wallet: str, mint: str, bull: dict):
        """Track un wallet qui a acheté un bull"""
        if wallet not in self.discovered:
            self.discovered[wallet] = {
                "wallet":     wallet,
                "bulls_hit":  [],
                "first_seen": time.time(),
                "gains":      [],
            }

        wallet_data = self.discovered[wallet]

        if mint not in wallet_data["bulls_hit"]:
            wallet_data["bulls_hit"].append(mint)
            wallet_data["gains"].append(bull.get("change_24h", 0))

        # Limite mémoire
        if len(self.discovered) > self.MAX_HISTORY:
            # Retire les wallets avec le moins de hits
            sorted_wallets = sorted(
                self.discovered.items(),
                key=lambda x: len(x[1]["bulls_hit"])
            )
            for w, _ in sorted_wallets[:50]:
                del self.discovered[w]

    def _generate_candidates(self) -> list:
        """Génère la liste des candidats alpha wallets"""
        candidates = []

        for wallet, data in self.discovered.items():
            bulls_count = len(data["bulls_hit"])
            gains = data.get("gains", [])

            if bulls_count < self.MIN_BULLS_HIT:
                continue

            # Calcul win rate (gains > 0 = win)
            if not gains:
                continue

            wins = sum(1 for g in gains if g > 0)
            win_rate = (wins / len(gains)) * 100

            if win_rate < self.MIN_WIN_RATE:
                continue

            # Score composite
            avg_gain = sum(gains) / len(gains)
            score = (win_rate / 100) * (bulls_count / 5) * (avg_gain / 500)

            candidates.append({
                "wallet":     wallet,
                "bulls_hit":  bulls_count,
                "win_rate":   round(win_rate, 1),
                "avg_gain":   round(avg_gain, 0),
                "score":      round(score, 3),
                "first_seen": data["first_seen"],
            })

        # Tri par score décroissant
        candidates.sort(key=lambda x: x["score"], reverse=True)

        return candidates[:20]  # Top 20

    def get_top_candidates(self, limit: int = 10) -> list:
        """Retourne les meilleurs candidats"""
        return self._generate_candidates()[:limit]

    def get_stats(self) -> dict:
        """Statistiques pour /status"""
        candidates = self._generate_candidates()
        return {
            "wallets_tracked":   len(self.discovered),
            "bulls_analyzed":    len(self.analyzed_bulls),
            "candidates_ready":  len(candidates),
        }

    # ════════════════════════════════════════
    # PERSISTENCE
    # ════════════════════════════════════════

    def _load_data(self):
        """Charge l'historique"""
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.discovered = data.get("discovered", {})
                    self.analyzed_bulls = set(data.get("analyzed_bulls", []))
                    logger.info(
                        f"🔍 {len(self.discovered)} wallets chargés"
                    )
        except Exception as e:
            logger.error(f"WalletDiscovery load error : {e}")

    def _save_data(self):
        """Sauvegarde"""
        try:
            os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "discovered": self.discovered,
                    "analyzed_bulls": list(self.analyzed_bulls),
                    "saved_at": datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"WalletDiscovery save error : {e}")

    def _save_candidates(self, candidates: list):
        """Sauvegarde les candidats"""
        try:
            os.makedirs(os.path.dirname(self.CANDIDATES_FILE), exist_ok=True)
            with open(self.CANDIDATES_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "candidates": candidates,
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)

            self.candidates_proposed = len(candidates)
        except Exception as e:
            logger.error(f"WalletDiscovery candidates save : {e}")