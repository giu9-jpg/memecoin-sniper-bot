# modules/simulator.py v1.0
"""
Trade Simulator (Paper Trading)
Simule automatiquement chaque alerte comme si tu avais acheté.
Calcule les résultats quand le sell signal arrive.

Utilité :
  - Tester la rentabilité du bot SANS risquer d'argent
  - Voir la performance réelle sur X jours
  - Nourrir le ML sans vrai trading
"""

import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("simulator")


class Simulator:

    DATA_FILE = "data/simulations.json"

    # Montant simulé par trade
    SIMULATED_AMOUNT_EUR = 10.0

    # Check périodique des positions ouvertes
    CHECK_INTERVAL = 120  # 2 minutes

    def __init__(self, ml_scorer=None):
        self.ml_scorer = ml_scorer
        self.session = None
        self.running = False

        # Positions simulées ouvertes : {mint: {...}}
        self.open_positions = {}

        # Historique complet
        self.simulations_history = []

        # Stats
        self.total_simulated = 0
        self.total_closed = 0
        self.total_pnl_eur = 0

        self._load_data()

    async def start(self):
        """Démarre le module"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self.running = True
        logger.info(
            f"🎮 Simulator démarré "
            f"({len(self.open_positions)} pos ouvertes | "
            f"{len(self.simulations_history)} historique)"
        )
        asyncio.create_task(self._check_loop())

    async def stop(self):
        """Arrêt propre"""
        self.running = False
        self._save_data()
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("🎮 Simulator arrêté")

    # ════════════════════════════════════════
    # SIMULER UN ACHAT
    # ════════════════════════════════════════

    async def simulate_buy(
        self,
        mint: str,
        symbol: str,
        alert_data: dict = None,
    ) -> dict:
        """
        Simule un achat automatique quand une alerte est envoyée.
        """
        try:
            # Anti-doublon
            if mint in self.open_positions:
                return {"success": False, "message": "Déjà en position"}

            # Récupère prix actuel
            data = await self._fetch_price(mint)
            if not data or data.get("price", 0) == 0:
                return {"success": False, "message": "Prix indisponible"}

            entry_price = data["price"]

            simulation = {
                "id":            f"sim_{int(time.time())}_{mint[:8]}",
                "mint":          mint,
                "symbol":        symbol,
                "amount_eur":    self.SIMULATED_AMOUNT_EUR,
                "entry_price":   entry_price,
                "entry_mc":      data.get("market_cap", 0),
                "entry_time":    time.time(),
                "entry_date":    datetime.now(timezone.utc).isoformat(),
                "max_gain_pct":  0,
                "current_pnl":   0,
                "closed":        False,
                "alert_score":   alert_data.get("score", 0) if alert_data else 0,
                "alert_tier":    alert_data.get("tier", "?") if alert_data else "?",
            }

            self.open_positions[mint] = simulation
            self.total_simulated += 1
            self._save_data()

            logger.info(
                f"🎮 Simu OPEN : ${symbol} @ ${entry_price:.8f} "
                f"({self.SIMULATED_AMOUNT_EUR}€)"
            )

            return {
                "success":     True,
                "simulation":  simulation,
            }

        except Exception as e:
            logger.error(f"Simulate buy error : {e}")
            return {"success": False, "message": str(e)}

    # ════════════════════════════════════════
    # SIMULER UNE VENTE
    # ════════════════════════════════════════

    async def simulate_sell(
        self,
        mint: str,
        reason: str = "sell_signal",
    ) -> dict:
        """
        Simule une vente automatique quand un sell signal arrive.
        """
        try:
            if mint not in self.open_positions:
                return {"success": False, "message": "Pas de position"}

            pos = self.open_positions[mint]

            # Récupère prix actuel
            data = await self._fetch_price(mint)
            if not data or data.get("price", 0) == 0:
                return {"success": False, "message": "Prix indisponible"}

            exit_price = data["price"]
            entry_price = pos["entry_price"]

            # Calcul PnL
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
            pnl_eur = pos["amount_eur"] * (pnl_pct / 100)
            final_eur = pos["amount_eur"] + pnl_eur

            # Update simulation
            pos["exit_price"]  = exit_price
            pos["exit_time"]   = time.time()
            pos["exit_date"]   = datetime.now(timezone.utc).isoformat()
            pos["pnl_pct"]     = round(pnl_pct, 2)
            pos["pnl_eur"]     = round(pnl_eur, 2)
            pos["final_eur"]   = round(final_eur, 2)
            pos["duration_min"] = round((time.time() - pos["entry_time"]) / 60, 1)
            pos["closed"]      = True
            pos["exit_reason"] = reason
            pos["exit_mc"]     = data.get("market_cap", 0)

            # Ajouter à l'historique
            self.simulations_history.append(pos.copy())

            # Retirer des positions ouvertes
            del self.open_positions[mint]

            # Update stats
            self.total_closed += 1
            self.total_pnl_eur += pnl_eur

            # Nourrit le ML
            if self.ml_scorer:
                try:
                    self.ml_scorer.record_result(
                        token_name=pos["symbol"],
                        is_win=(pnl_pct > 0),
                        pnl_pct=pnl_pct,
                    )
                except Exception as e:
                    logger.debug(f"ML record error : {e}")

            self._save_data()

            logger.info(
                f"🎮 Simu CLOSE : ${pos['symbol']} "
                f"PnL {pnl_pct:+.1f}% ({pnl_eur:+.2f}€)"
            )

            return {
                "success":       True,
                "simulation":    pos,
                "pnl_pct":       pnl_pct,
                "pnl_eur":       pnl_eur,
                "final_eur":     final_eur,
                "duration_min":  pos["duration_min"],
            }

        except Exception as e:
            logger.error(f"Simulate sell error : {e}")
            return {"success": False, "message": str(e)}

    # ════════════════════════════════════════
    # BOUCLE DE MISE À JOUR PnL
    # ════════════════════════════════════════

    async def _check_loop(self):
        """Met à jour les PnL et détecte les auto-closes"""
        while self.running:
            try:
                if self.open_positions:
                    await self._update_positions()
                await self._auto_close_old()
            except Exception as e:
                logger.error(f"Simulator loop error : {e}")
            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _update_positions(self):
        """Met à jour les PnL des positions ouvertes"""
        for mint in list(self.open_positions.keys()):
            try:
                pos = self.open_positions[mint]
                data = await self._fetch_price(mint)
                if not data or data.get("price", 0) == 0:
                    continue

                current_price = data["price"]
                entry_price = pos["entry_price"]

                pnl_pct = ((current_price - entry_price) / entry_price) * 100

                pos["current_pnl"] = round(pnl_pct, 2)
                pos["current_price"] = current_price

                if pnl_pct > pos["max_gain_pct"]:
                    pos["max_gain_pct"] = round(pnl_pct, 2)

            except Exception as e:
                logger.debug(f"Update pos error : {e}")

    async def _auto_close_old(self):
        """
        Auto-close les positions trop anciennes (>7 jours).
        Considère comme -100% si liquidité disparue.
        """
        cutoff = time.time() - (7 * 86400)  # 7 jours

        for mint in list(self.open_positions.keys()):
            pos = self.open_positions[mint]
            if pos["entry_time"] < cutoff:
                # Auto-close comme perte
                await self.simulate_sell(mint, reason="timeout_7days")

    # ════════════════════════════════════════
    # HELPERS API
    # ════════════════════════════════════════

    async def _fetch_price(self, mint: str) -> dict:
        """Récupère le prix actuel"""
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
            return {
                "price":      float(pair.get("priceUsd", 0) or 0),
                "market_cap": pair.get("marketCap", 0) or pair.get("fdv", 0) or 0,
                "liquidity":  pair.get("liquidity", {}).get("usd", 0) or 0,
            }
        except Exception:
            return None

    # ════════════════════════════════════════
    # STATISTIQUES
    # ════════════════════════════════════════

    def get_stats(self) -> dict:
        """Stats globales"""
        closed = [s for s in self.simulations_history if s.get("closed")]

        wins = [s for s in closed if s.get("pnl_pct", 0) > 0]
        losses = [s for s in closed if s.get("pnl_pct", 0) <= 0]

        total_invested = len(closed) * self.SIMULATED_AMOUNT_EUR
        total_pnl = sum(s.get("pnl_eur", 0) for s in closed)
        roi = (total_pnl / total_invested * 100) if total_invested > 0 else 0
        win_rate = (len(wins) / len(closed) * 100) if closed else 0

        # PnL par période
        now = time.time()
        day_ago = now - 86400
        week_ago = now - (7 * 86400)

        pnl_day = sum(
            s.get("pnl_eur", 0) for s in closed
            if s.get("exit_time", 0) >= day_ago
        )
        pnl_week = sum(
            s.get("pnl_eur", 0) for s in closed
            if s.get("exit_time", 0) >= week_ago
        )

        # Meilleur / pire trade
        best_trade = None
        worst_trade = None
        if closed:
            best_trade = max(closed, key=lambda x: x.get("pnl_pct", 0))
            worst_trade = min(closed, key=lambda x: x.get("pnl_pct", 0))

        # Durée moyenne
        avg_duration = 0
        if closed:
            avg_duration = sum(s.get("duration_min", 0) for s in closed) / len(closed)

        return {
            "total_simulated":  self.total_simulated,
            "open_positions":   len(self.open_positions),
            "closed_positions": len(closed),
            "wins":             len(wins),
            "losses":           len(losses),
            "win_rate":         round(win_rate, 1),
            "total_invested":   round(total_invested, 2),
            "total_pnl":        round(total_pnl, 2),
            "roi_pct":          round(roi, 1),
            "pnl_day":          round(pnl_day, 2),
            "pnl_week":         round(pnl_week, 2),
            "avg_duration_min": round(avg_duration, 1),
            "best_trade":       best_trade,
            "worst_trade":      worst_trade,
        }

    def get_open_positions(self) -> list:
        """Retourne les positions ouvertes avec PnL actuel"""
        return list(self.open_positions.values())

    def get_recent_trades(self, limit: int = 15) -> list:
        """Retourne les derniers trades fermés"""
        closed = [s for s in self.simulations_history if s.get("closed")]
        return sorted(
            closed,
            key=lambda x: x.get("exit_time", 0),
            reverse=True
        )[:limit]

    # ════════════════════════════════════════
    # PERSISTENCE
    # ════════════════════════════════════════

    def _load_data(self):
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.open_positions = data.get("open_positions", {})
                    self.simulations_history = data.get("history", [])
                    self.total_simulated = data.get("total_simulated", 0)
                    self.total_closed = data.get("total_closed", 0)
                    self.total_pnl_eur = data.get("total_pnl_eur", 0)
                    logger.info(
                        f"🎮 Simulations chargées : "
                        f"{len(self.open_positions)} ouvertes, "
                        f"{len(self.simulations_history)} historique"
                    )
        except Exception as e:
            logger.error(f"Simulator load error : {e}")

    def _save_data(self):
        try:
            os.makedirs(os.path.dirname(self.DATA_FILE), exist_ok=True)
            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "open_positions":   self.open_positions,
                    "history":          self.simulations_history,
                    "total_simulated":  self.total_simulated,
                    "total_closed":     self.total_closed,
                    "total_pnl_eur":    self.total_pnl_eur,
                    "saved_at":         datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Simulator save error : {e}")

    def reset(self):
        """Reset toutes les simulations (danger)"""
        count = len(self.simulations_history) + len(self.open_positions)
        self.open_positions = {}
        self.simulations_history = []
        self.total_simulated = 0
        self.total_closed = 0
        self.total_pnl_eur = 0
        self._save_data()
        return count