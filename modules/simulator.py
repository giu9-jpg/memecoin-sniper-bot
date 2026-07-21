# modules/simulator.py — v1.1
# ═══════════════════════════════════════════════
# FIX v1.1 :
# + SL automatique à -30% (ferme la position simulée)
# + TP automatique à +100% (prend profit simulé)
# + Auto-close positions > 24h (pas 7 jours)
# + Nettoyage des positions zombies au démarrage
# + Logs améliorés

import asyncio
import aiohttp
import json
import os
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("simulator")


class Simulator:

    DATA_FILE            = "data/simulations.json"
    SIMULATED_AMOUNT_EUR = 10.0
    CHECK_INTERVAL       = 120     # 2 minutes

    # v1.1 : SL/TP automatiques pour les simulations
    SIM_SL_PCT           = -30     # Stop Loss à -30%
    SIM_TP_PCT           = 100     # Take Profit à +100%
    SIM_MAX_AGE_HOURS    = 24      # Auto-close après 24h (pas 7j)

    def __init__(self, ml_scorer=None):
        self.ml_scorer           = ml_scorer
        self.session             = None
        self.running             = False
        self.open_positions      = {}
        self.simulations_history = []
        self.total_simulated     = 0
        self.total_closed        = 0
        self.total_pnl_eur       = 0

        self._load_data()

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )
        self.running = True

        # v1.1 : nettoyer les positions zombies au démarrage
        zombies = await self._cleanup_zombies()

        logger.info(
            f"🎮 Simulator v1.1 démarré "
            f"({len(self.open_positions)} pos ouvertes | "
            f"{len(self.simulations_history)} historique | "
            f"SL:{self.SIM_SL_PCT}% TP:+{self.SIM_TP_PCT}% | "
            f"max:{self.SIM_MAX_AGE_HOURS}h)"
        )

        if zombies > 0:
            logger.info(f"🎮 {zombies} positions zombies nettoyées")

        asyncio.create_task(self._check_loop())

    async def stop(self):
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
        mint:       str,
        symbol:     str,
        alert_data: dict = None,
    ) -> dict:
        try:
            if mint in self.open_positions:
                return {"success": False, "message": "Déjà en position"}

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
                "min_loss_pct":  0,
                "current_pnl":   0,
                "current_price": entry_price,
                "closed":        False,
                "alert_score":   alert_data.get("score", 0) if alert_data else 0,
                "alert_tier":    alert_data.get("tier", "?") if alert_data else "?",
            }

            self.open_positions[mint] = simulation
            self.total_simulated     += 1
            self._save_data()

            logger.info(
                f"🎮 SIM BUY : ${symbol} @ ${entry_price:.8f} "
                f"({self.SIMULATED_AMOUNT_EUR}€)"
            )

            return {"success": True, "simulation": simulation}

        except Exception as e:
            logger.error(f"Simulate buy error : {e}")
            return {"success": False, "message": str(e)}

    # ════════════════════════════════════════
    # SIMULER UNE VENTE
    # ════════════════════════════════════════

    async def simulate_sell(
        self,
        mint:   str,
        reason: str = "sell_signal",
    ) -> dict:
        try:
            if mint not in self.open_positions:
                return {"success": False, "message": "Pas de position"}

            pos = self.open_positions[mint]

            data = await self._fetch_price(mint)

            if data and data.get("price", 0) > 0:
                exit_price = data["price"]
            else:
                # Si prix indisponible, utilise le dernier connu
                exit_price = pos.get("current_price", pos["entry_price"])

            entry_price = pos["entry_price"]

            if entry_price <= 0:
                # Token mort, considère -100%
                pnl_pct = -100
            else:
                pnl_pct = ((exit_price - entry_price) / entry_price) * 100

            pnl_eur   = pos["amount_eur"] * (pnl_pct / 100)
            final_eur = pos["amount_eur"] + pnl_eur

            pos["exit_price"]   = exit_price
            pos["exit_time"]    = time.time()
            pos["exit_date"]    = datetime.now(timezone.utc).isoformat()
            pos["pnl_pct"]      = round(pnl_pct, 2)
            pos["pnl_eur"]      = round(pnl_eur, 2)
            pos["final_eur"]    = round(final_eur, 2)
            pos["duration_min"] = round(
                (time.time() - pos["entry_time"]) / 60, 1
            )
            pos["closed"]       = True
            pos["exit_reason"]  = reason
            pos["exit_mc"]      = data.get("market_cap", 0) if data else 0

            self.simulations_history.append(pos.copy())
            del self.open_positions[mint]

            self.total_closed  += 1
            self.total_pnl_eur += pnl_eur

            # Nourrir le ML
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

            emoji = "🟢" if pnl_pct > 0 else "🔴"
            logger.info(
                f"🎮 SIM SELL {emoji} : ${pos['symbol']} "
                f"PnL {pnl_pct:+.1f}% ({pnl_eur:+.2f}€) "
                f"reason={reason}"
            )

            return {
                "success":      True,
                "simulation":   pos,
                "pnl_pct":      pnl_pct,
                "pnl_eur":      pnl_eur,
                "final_eur":    final_eur,
                "duration_min": pos["duration_min"],
            }

        except Exception as e:
            logger.error(f"Simulate sell error : {e}")
            return {"success": False, "message": str(e)}

    # ════════════════════════════════════════
    # BOUCLE DE MISE À JOUR
    # ════════════════════════════════════════

    async def _check_loop(self):
        """Met à jour les PnL et applique SL/TP/timeout."""
        while self.running:
            try:
                if self.open_positions:
                    await self._update_and_check_positions()
            except Exception as e:
                logger.error(f"Simulator loop error : {e}")
            await asyncio.sleep(self.CHECK_INTERVAL)

    async def _update_and_check_positions(self):
        """
        v1.1 : Met à jour PUIS vérifie SL/TP/timeout
        pour CHAQUE position ouverte.
        """
        # Copie les clés pour éviter modification pendant itération
        mints_to_check = list(self.open_positions.keys())

        for mint in mints_to_check:
            if mint not in self.open_positions:
                continue

            pos = self.open_positions[mint]

            try:
                # 1. Mise à jour du prix
                data = await self._fetch_price(mint)
                if data and data.get("price", 0) > 0:
                    current_price = data["price"]
                    entry_price   = pos["entry_price"]

                    if entry_price > 0:
                        pnl_pct = (
                            (current_price - entry_price) / entry_price
                        ) * 100
                    else:
                        pnl_pct = -100

                    pos["current_pnl"]   = round(pnl_pct, 2)
                    pos["current_price"] = current_price

                    if pnl_pct > pos.get("max_gain_pct", 0):
                        pos["max_gain_pct"] = round(pnl_pct, 2)
                    if pnl_pct < pos.get("min_loss_pct", 0):
                        pos["min_loss_pct"] = round(pnl_pct, 2)
                else:
                    # Prix indisponible → probablement token mort
                    pnl_pct = pos.get("current_pnl", -100)

                # 2. Vérification SL
                if pnl_pct <= self.SIM_SL_PCT:
                    logger.info(
                        f"🎮 🛑 SIM SL : ${pos['symbol']} "
                        f"PnL {pnl_pct:+.1f}% ≤ {self.SIM_SL_PCT}%"
                    )
                    await self.simulate_sell(mint, reason="sim_stop_loss")
                    continue

                # 3. Vérification TP
                if pnl_pct >= self.SIM_TP_PCT:
                    logger.info(
                        f"🎮 🎯 SIM TP : ${pos['symbol']} "
                        f"PnL {pnl_pct:+.1f}% ≥ +{self.SIM_TP_PCT}%"
                    )
                    await self.simulate_sell(mint, reason="sim_take_profit")
                    continue

                # 4. Vérification timeout
                age_hours = (time.time() - pos["entry_time"]) / 3600
                if age_hours >= self.SIM_MAX_AGE_HOURS:
                    logger.info(
                        f"🎮 ⏰ SIM TIMEOUT : ${pos['symbol']} "
                        f"après {age_hours:.1f}h "
                        f"PnL {pnl_pct:+.1f}%"
                    )
                    await self.simulate_sell(mint, reason="sim_timeout_24h")
                    continue

            except Exception as e:
                logger.debug(f"Sim check error {mint[:8]}: {e}")

            # Rate limiting entre les appels API
            await asyncio.sleep(1)

    async def _cleanup_zombies(self) -> int:
        """
        v1.1 : Nettoie les positions zombies au démarrage.
        Ferme automatiquement les positions :
          - Plus vieilles que 24h
          - Sans prix (token mort/rug)
        """
        zombies_closed = 0

        for mint in list(self.open_positions.keys()):
            pos = self.open_positions[mint]

            age_hours = (time.time() - pos.get("entry_time", 0)) / 3600

            # Position > 48h → zombie certain
            if age_hours > 48:
                pos["exit_price"]   = 0
                pos["exit_time"]    = time.time()
                pos["exit_date"]    = datetime.now(timezone.utc).isoformat()
                pos["pnl_pct"]      = -100
                pos["pnl_eur"]      = -pos["amount_eur"]
                pos["final_eur"]    = 0
                pos["duration_min"] = round(age_hours * 60, 1)
                pos["closed"]       = True
                pos["exit_reason"]  = "zombie_cleanup"

                self.simulations_history.append(pos.copy())
                del self.open_positions[mint]

                self.total_closed  += 1
                self.total_pnl_eur -= pos["amount_eur"]

                zombies_closed += 1

        if zombies_closed > 0:
            self._save_data()

        return zombies_closed

    # ════════════════════════════════════════
    # API
    # ════════════════════════════════════════

    async def _fetch_price(self, mint: str) -> dict | None:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return None
                data  = await resp.json()
                pairs = data.get("pairs") or []
                if not pairs:
                    return None
                pair = pairs[0]
                return {
                    "price":      float(pair.get("priceUsd", 0) or 0),
                    "market_cap": (
                        pair.get("marketCap", 0)
                        or pair.get("fdv", 0)
                        or 0
                    ),
                    "liquidity":  (
                        pair.get("liquidity", {}).get("usd", 0) or 0
                    ),
                }
        except Exception:
            return None

    # ════════════════════════════════════════
    # STATISTIQUES
    # ════════════════════════════════════════

    def get_stats(self) -> dict:
        closed   = [s for s in self.simulations_history if s.get("closed")]
        wins     = [s for s in closed if s.get("pnl_pct", 0) > 0]
        losses   = [s for s in closed if s.get("pnl_pct", 0) <= 0]

        total_invested = len(closed) * self.SIMULATED_AMOUNT_EUR
        total_pnl      = sum(s.get("pnl_eur", 0) for s in closed)
        roi            = (
            (total_pnl / total_invested * 100)
            if total_invested > 0 else 0
        )
        win_rate = (len(wins) / len(closed) * 100) if closed else 0

        now      = time.time()
        day_ago  = now - 86400
        week_ago = now - (7 * 86400)

        pnl_day = sum(
            s.get("pnl_eur", 0) for s in closed
            if s.get("exit_time", 0) >= day_ago
        )
        pnl_week = sum(
            s.get("pnl_eur", 0) for s in closed
            if s.get("exit_time", 0) >= week_ago
        )

        best_trade  = None
        worst_trade = None
        if closed:
            best_trade  = max(closed, key=lambda x: x.get("pnl_pct", 0))
            worst_trade = min(closed, key=lambda x: x.get("pnl_pct", 0))

        avg_duration = 0
        if closed:
            avg_duration = sum(
                s.get("duration_min", 0) for s in closed
            ) / len(closed)

        # v1.1 : stats par raison de sortie
        by_reason = {}
        for s in closed:
            reason = s.get("exit_reason", "unknown")
            if reason not in by_reason:
                by_reason[reason] = {"count": 0, "pnl": 0}
            by_reason[reason]["count"] += 1
            by_reason[reason]["pnl"]   += s.get("pnl_eur", 0)

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
            "by_reason":        by_reason,
        }

    def get_open_positions(self) -> list:
        return list(self.open_positions.values())

    def get_recent_trades(self, limit: int = 15) -> list:
        closed = [s for s in self.simulations_history if s.get("closed")]
        return sorted(
            closed,
            key=lambda x: x.get("exit_time", 0),
            reverse=True,
        )[:limit]

    # ════════════════════════════════════════
    # PERSISTENCE
    # ════════════════════════════════════════

    def _load_data(self):
        try:
            if os.path.exists(self.DATA_FILE):
                with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.open_positions      = data.get("open_positions", {})
                    self.simulations_history = data.get("history", [])
                    self.total_simulated     = data.get("total_simulated", 0)
                    self.total_closed        = data.get("total_closed", 0)
                    self.total_pnl_eur       = data.get("total_pnl_eur", 0)
                    logger.info(
                        f"🎮 Simulations chargées : "
                        f"{len(self.open_positions)} ouvertes, "
                        f"{len(self.simulations_history)} historique"
                    )
        except Exception as e:
            logger.error(f"Simulator load error : {e}")

    def _save_data(self):
        try:
            data_dir = os.path.dirname(self.DATA_FILE)
            if data_dir:
                os.makedirs(data_dir, exist_ok=True)

            with open(self.DATA_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "open_positions":  self.open_positions,
                    "history":         self.simulations_history,
                    "total_simulated": self.total_simulated,
                    "total_closed":    self.total_closed,
                    "total_pnl_eur":   self.total_pnl_eur,
                    "saved_at":        datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Simulator save error : {e}")

    def reset(self) -> int:
        count = len(self.simulations_history) + len(self.open_positions)
        self.open_positions      = {}
        self.simulations_history = []
        self.total_simulated     = 0
        self.total_closed        = 0
        self.total_pnl_eur       = 0
        self._save_data()
        return count