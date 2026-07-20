# modules/auto_optimizer.py — v1.0 CORRIGÉ
# FIX AUDIT : aucun bug critique, nettoyage imports

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("auto_optimizer")


class AutoOptimizer:

    OPTIMIZATION_INTERVAL       = 21600   # 6 heures
    MIN_TRADES_FOR_OPTIMIZATION = 20
    MIN_SCORE_MIN               = 6.0
    MIN_SCORE_MAX               = 8.5
    CONFIG_FILE                 = "data/optimized_config.json"

    def __init__(self, ml_scorer, bull_analyzer, alert_sender):
        self.ml_scorer     = ml_scorer
        self.bull_analyzer = bull_analyzer
        self.alert_sender  = alert_sender
        self.running       = False

        self.current_config = {
            "min_score":       7.5,
            "min_score_tier1": 5.5,
            "min_score_tier2": 6.5,
            "quality_min":     60,
        }

        self.optimization_history = []
        self.total_optimizations  = 0
        self.last_optimization    = 0

        self._load_config()

    async def start(self):
        self.running = True
        logger.info(
            f"🎯 AutoOptimizer démarré "
            f"(cycle: {self.OPTIMIZATION_INTERVAL/3600:.0f}h)"
        )
        asyncio.create_task(self._optimization_loop())

    async def stop(self):
        self.running = False
        self._save_config()
        logger.info("🎯 AutoOptimizer arrêté")

    async def _optimization_loop(self):
        await asyncio.sleep(3600)
        while self.running:
            try:
                await self._run_optimization()
            except Exception as e:
                logger.error(f"AutoOptimizer error : {e}")
            await asyncio.sleep(self.OPTIMIZATION_INTERVAL)

    async def _run_optimization(self):
        logger.info("🎯 Optimisation en cours...")

        ml_stats = self.ml_scorer.get_stats()

        if ml_stats.get("trades", 0) < self.MIN_TRADES_FOR_OPTIMIZATION:
            logger.info(
                f"🎯 Pas assez de trades "
                f"({ml_stats.get('trades', 0)}/{self.MIN_TRADES_FOR_OPTIMIZATION})"
            )
            return

        bull_stats   = self.bull_analyzer.get_stats(days=7)
        suggestions  = self._calculate_optimizations(ml_stats, bull_stats)

        if not suggestions:
            logger.info("🎯 Aucune optimisation nécessaire")
            return

        old_config = self.current_config.copy()
        self._apply_suggestions(suggestions)

        self.total_optimizations += 1
        self.last_optimization    = time.time()

        self.optimization_history.append({
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "old_config":  old_config,
            "new_config":  self.current_config.copy(),
            "suggestions": suggestions,
            "ml_win_rate": ml_stats.get("win_rate", 0),
        })

        if len(self.optimization_history) > 20:
            self.optimization_history = self.optimization_history[-20:]

        self._save_config()

        await self._send_optimization_report(
            old_config, self.current_config, suggestions,
            ml_stats, bull_stats
        )

        logger.info(
            f"🎯 Optimisation terminée : {len(suggestions)} changement(s)"
        )

    def _calculate_optimizations(
        self, ml_stats: dict, bull_stats: dict
    ) -> list:
        suggestions       = []
        win_rate          = ml_stats.get("win_rate", 0)
        trades            = ml_stats.get("trades", 0)
        avg_pnl           = ml_stats.get("avg_pnl", 0)
        current_min_score = self.current_config["min_score"]

        if win_rate < 40 and current_min_score < self.MIN_SCORE_MAX:
            new_score = min(self.MIN_SCORE_MAX, current_min_score + 0.3)
            suggestions.append({
                "param":  "min_score",
                "old":    current_min_score,
                "new":    new_score,
                "reason": f"Win rate faible ({win_rate:.0f}%)",
                "action": "Plus sélectif",
            })

        elif win_rate > 65 and trades > 30 and current_min_score > self.MIN_SCORE_MIN:
            new_score = max(self.MIN_SCORE_MIN, current_min_score - 0.2)
            suggestions.append({
                "param":  "min_score",
                "old":    current_min_score,
                "new":    new_score,
                "reason": f"Excellent win rate ({win_rate:.0f}%)",
                "action": "Plus d'opportunités",
            })

        if avg_pnl < 0 and self.current_config["min_score_tier1"] < 6.0:
            suggestions.append({
                "param":  "min_score_tier1",
                "old":    self.current_config["min_score_tier1"],
                "new":    6.0,
                "reason": f"PnL moyen négatif ({avg_pnl:.0f}%)",
                "action": "Tier1 plus strict",
            })

        if bull_stats.get("total", 0) > 20:
            suggestions.append({
                "param":  "info",
                "old":    "N/A",
                "new":    f"{bull_stats['total']} bulls détectés",
                "reason": "Analyse marché",
                "action": "Voir /bullrun pour details",
            })

        return suggestions

    def _apply_suggestions(self, suggestions: list):
        for sug in suggestions:
            param = sug["param"]
            if param != "info" and param in self.current_config:
                self.current_config[param] = sug["new"]

    async def _send_optimization_report(
        self,
        old_config:  dict,
        new_config:  dict,
        suggestions: list,
        ml_stats:    dict,
        bull_stats:  dict,
    ):
        try:
            lines = [
                "🎯 *AUTO\\-OPTIMIZER*",
                "━━━━━━━━━━━━━━",
                "",
                f"📊 *Analyse ML :*",
                f"  Trades : `{ml_stats.get('trades', 0)}`",
                f"  Win rate : `{ml_stats.get('win_rate', 0):.1f}%`",
                f"  PnL moyen : `{ml_stats.get('avg_pnl', 0):+.0f}%`",
                "",
                f"🎯 *Analyse Bulls \\(7j\\) :*",
                f"  Bulls détectés : `{bull_stats.get('total', 0)}`",
                "",
                "━━━━━━━━━━━━━━",
                "🔧 *CHANGEMENTS APPLIQUÉS :*",
                "",
            ]

            for sug in suggestions:
                param = sug["param"]
                if param == "info":
                    continue
                lines.append(
                    f"⚙️ *{self._esc(param)}* : "
                    f"`{sug['old']}` → `{sug['new']}`"
                )
                lines.append(f"   💡 {self._esc(sug['reason'])}")
                lines.append(f"   → {self._esc(sug['action'])}")
                lines.append("")

            lines.extend([
                "━━━━━━━━━━━━━━",
                f"📈 Total optimisations : `{self.total_optimizations}`",
                f"⏰ Prochaine analyse dans 6h",
            ])

            await self.alert_sender._send_telegram("\n".join(lines))

        except Exception as e:
            logger.error(f"Optimizer report error : {e}")

    def _esc(self, text: str) -> str:
        special = r'_*[]()~`>#+-=|{}.!'
        return "".join(
            f"\\{c}" if c in special else c
            for c in str(text)
        )

    def get_current_config(self) -> dict:
        return self.current_config.copy()

    def get_min_score(self) -> float:
        return self.current_config.get("min_score", 7.5)

    def get_stats(self) -> dict:
        return {
            "total_optimizations": self.total_optimizations,
            "last_optimization":   self.last_optimization,
            "current_min_score":   self.current_config.get("min_score", 7.5),
            "history_count":       len(self.optimization_history),
        }

    def get_history(self) -> list:
        return self.optimization_history.copy()

    def _load_config(self):
        try:
            if os.path.exists(self.CONFIG_FILE):
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.current_config       = data.get("config", self.current_config)
                    self.optimization_history = data.get("history", [])
                    self.total_optimizations  = data.get("total_optimizations", 0)
                    self.last_optimization    = data.get("last_optimization", 0)
                    logger.info(
                        f"🎯 Config optimisée chargée "
                        f"(MIN_SCORE: {self.current_config.get('min_score', 7.5)})"
                    )
        except Exception as e:
            logger.error(f"AutoOptimizer load error : {e}")

    def _save_config(self):
        try:
            os.makedirs(os.path.dirname(self.CONFIG_FILE), exist_ok=True)
            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "config":              self.current_config,
                    "history":             self.optimization_history,
                    "total_optimizations": self.total_optimizations,
                    "last_optimization":   self.last_optimization,
                    "saved_at":            datetime.now(timezone.utc).isoformat(),
                }, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"AutoOptimizer save error : {e}")