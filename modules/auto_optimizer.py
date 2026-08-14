# modules/auto_optimizer.py — v2.0 SAFE REALISTIC
# ═══════════════════════════════════════════════
# AutoOptimizer sécurisé pour MemeSniper v14.1-EVOLUTION
#
# Objectifs :
# - Ne plus baisser MIN_SCORE à 6.x sur un win rate paper irréaliste
# - Plancher dur configurable : AUTO_OPTIMIZER_MIN_SCORE_FLOOR=8.0
# - Utilise ROI / pertes / nombre de trades plutôt que win rate seul
# - Compatible avec main.py :
#     AutoOptimizer(ml_scorer=..., bull_analyzer=..., alert_sender=...)
#     AutoOptimizer()
#     await start()
#     await stop()
#     get_min_score()
#     get_stats()
#     update_config(...)
#
# Aucun trading réel.

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger


logger = get_logger("auto_optimizer")


JsonDict = Dict[str, Any]


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        if value is None or value == "":
            return default

        return float(str(value).replace(",", "."))

    except Exception:
        return default


def _safe_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        if value is None or value == "":
            return default

        return int(float(str(value).replace(",", ".")))

    except Exception:
        return default


def _env_float(
    name: str,
    default: float,
) -> float:
    return _safe_float(os.getenv(name), default)


def _env_int(
    name: str,
    default: int,
) -> int:
    return _safe_int(os.getenv(name), default)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AutoOptimizer:
    """
    AutoOptimizer sécurisé.

    Règle importante :
    - Le score minimum ne descend jamais sous floor.
    - Par défaut floor = 8.0.
    - Un win rate trop beau ne suffit pas à baisser le score.
    """

    CONFIG_FILE = str(_data_dir() / "optimized_config.json")

    OPTIMIZATION_INTERVAL = _env_int(
        "AUTO_OPTIMIZER_INTERVAL_SECONDS",
        6 * 3600,
    )

    MIN_TRADES_FOR_ANALYSIS = _env_int(
        "AUTO_OPTIMIZER_MIN_TRADES_FOR_ANALYSIS",
        30,
    )

    MIN_TRADES_FOR_LOWERING = _env_int(
        "AUTO_OPTIMIZER_MIN_TRADES_FOR_LOWERING",
        150,
    )

    MIN_SCORE_FLOOR = _env_float(
        "AUTO_OPTIMIZER_MIN_SCORE_FLOOR",
        8.0,
    )

    MIN_SCORE_CEILING = _env_float(
        "AUTO_OPTIMIZER_MIN_SCORE_CEILING",
        9.2,
    )

    DEFAULT_MIN_SCORE = _env_float(
        "MIN_SCORE",
        8.0,
    )

    DEFAULT_MAX_ALERTS_PER_HOUR = _env_int(
        "MAX_ALERTS_PER_HOUR",
        10,
    )

    def __init__(
        self,
        ml_scorer=None,
        bull_analyzer=None,
        alert_sender=None,
    ):
        self.ml_scorer = ml_scorer
        self.bull_analyzer = bull_analyzer
        self.alert_sender = alert_sender

        self.running = False
        self._task: Optional[asyncio.Task] = None

        # Garde les noms historiques utilisés par le bot.
        self.current_config: JsonDict = {
            "min_score": max(
                self.DEFAULT_MIN_SCORE,
                self.MIN_SCORE_FLOOR,
            ),
            "max_alerts_per_hour": self.DEFAULT_MAX_ALERTS_PER_HOUR,
            "min_score_tier1": 6.0,
            "min_score_tier2": 7.0,
            "quality_min": 65,
        }

        self.optimization_history: List[JsonDict] = []
        self.total_optimizations = 0
        self.last_optimization = 0.0

        self.last_stats: JsonDict = {}
        self.last_changes: List[str] = []

        self._load_config()

        # Sécurité absolue au chargement.
        self.current_config["min_score"] = self._clamp_min_score(
            self.current_config.get("min_score", self.DEFAULT_MIN_SCORE)
        )

        self._save_config()

        logger.info(
            f"🎯 Config optimisée chargée "
            f"(MIN_SCORE: {self.current_config.get('min_score', 8.0)})"
        )

    # ════════════════════════════════════════
    # LIFECYCLE
    # ════════════════════════════════════════

    async def start(self):
        self.running = True

        logger.info(
            f"🎯 AutoOptimizer SAFE v2.0 démarré "
            f"(cycle: {self.OPTIMIZATION_INTERVAL / 3600:.0f}h | "
            f"floor:{self.MIN_SCORE_FLOOR})"
        )

        self._task = asyncio.create_task(self._optimization_loop())

    async def stop(self):
        self.running = False

        if self._task and not self._task.done():
            self._task.cancel()

        self._save_config()

        logger.info("🎯 AutoOptimizer arrêté")

    async def _optimization_loop(self):
        # Laisse le bot démarrer tranquillement.
        await asyncio.sleep(3600)

        while self.running:
            try:
                await self._run_optimization()

            except asyncio.CancelledError:
                break

            except Exception as exc:
                logger.error(f"AutoOptimizer error : {exc}")

            await asyncio.sleep(self.OPTIMIZATION_INTERVAL)

    # ════════════════════════════════════════
    # CONFIG
    # ════════════════════════════════════════

    def _clamp_min_score(
        self,
        value: Any,
    ) -> float:
        score = _safe_float(value, self.DEFAULT_MIN_SCORE)

        score = max(score, self.MIN_SCORE_FLOOR)
        score = min(score, self.MIN_SCORE_CEILING)

        return round(score, 2)

    def _load_json(
        self,
        path: Path,
        default: Any,
    ) -> Any:
        try:
            if not path.exists():
                return default

            return json.loads(
                path.read_text(encoding="utf-8")
            )

        except Exception:
            return default

    def _load_config(self):
        try:
            path = Path(self.CONFIG_FILE)

            if not path.exists():
                return

            data = self._load_json(path, {})

            if not isinstance(data, dict):
                return

            raw_config = data.get("config", data)

            if isinstance(raw_config, dict):
                min_score = (
                    raw_config.get("min_score")
                    if "min_score" in raw_config
                    else raw_config.get("MIN_SCORE")
                )

                max_alerts = (
                    raw_config.get("max_alerts_per_hour")
                    if "max_alerts_per_hour" in raw_config
                    else raw_config.get("MAX_ALERTS_PER_HOUR")
                )

                if min_score is not None:
                    self.current_config["min_score"] = self._clamp_min_score(
                        min_score
                    )

                if max_alerts is not None:
                    self.current_config["max_alerts_per_hour"] = max(
                        1,
                        _safe_int(
                            max_alerts,
                            self.DEFAULT_MAX_ALERTS_PER_HOUR,
                        ),
                    )

                # Compatibilité avec les anciens champs
                if "min_score_tier1" in raw_config:
                    self.current_config["min_score_tier1"] = max(
                        5.5,
                        _safe_float(raw_config.get("min_score_tier1"), 6.0),
                    )

                if "min_score_tier2" in raw_config:
                    self.current_config["min_score_tier2"] = max(
                        6.5,
                        _safe_float(raw_config.get("min_score_tier2"), 7.0),
                    )

                if "quality_min" in raw_config:
                    self.current_config["quality_min"] = max(
                        60,
                        _safe_int(raw_config.get("quality_min"), 65),
                    )

            self.optimization_history = (
                data.get("history", [])
                if isinstance(data.get("history", []), list)
                else []
            )

            self.total_optimizations = _safe_int(
                data.get("total_optimizations"),
                0,
            )

            self.last_optimization = _safe_float(
                data.get("last_optimization"),
                0.0,
            )

            self.last_stats = (
                data.get("last_stats", {})
                if isinstance(data.get("last_stats", {}), dict)
                else {}
            )

            self.last_changes = (
                data.get("last_changes", [])
                if isinstance(data.get("last_changes", []), list)
                else []
            )

        except Exception as exc:
            logger.error(f"AutoOptimizer load error : {exc}")

    def _save_config(self):
        try:
            path = Path(self.CONFIG_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)

            self.current_config["min_score"] = self._clamp_min_score(
                self.current_config.get("min_score", self.DEFAULT_MIN_SCORE)
            )

            payload = {
                "config": {
                    # Format historique
                    "min_score": self.current_config["min_score"],
                    "min_score_tier1": self.current_config.get(
                        "min_score_tier1",
                        6.0,
                    ),
                    "min_score_tier2": self.current_config.get(
                        "min_score_tier2",
                        7.0,
                    ),
                    "quality_min": self.current_config.get(
                        "quality_min",
                        65,
                    ),
                    "max_alerts_per_hour": self.current_config.get(
                        "max_alerts_per_hour",
                        self.DEFAULT_MAX_ALERTS_PER_HOUR,
                    ),

                    # Format Railway / uppercase aussi
                    "MIN_SCORE": self.current_config["min_score"],
                    "MAX_ALERTS_PER_HOUR": self.current_config.get(
                        "max_alerts_per_hour",
                        self.DEFAULT_MAX_ALERTS_PER_HOUR,
                    ),
                },
                "history": self.optimization_history[-100:],
                "total_optimizations": self.total_optimizations,
                "last_optimization": self.last_optimization,
                "last_stats": self.last_stats,
                "last_changes": self.last_changes,
                "safety": {
                    "min_score_floor": self.MIN_SCORE_FLOOR,
                    "min_score_ceiling": self.MIN_SCORE_CEILING,
                    "paper_trading_only": True,
                    "auto_trading": False,
                },
                "saved_at": _utc_now_iso(),
            }

            path.write_text(
                json.dumps(
                    payload,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        except Exception as exc:
            logger.error(f"AutoOptimizer save error : {exc}")

    def update_config(
        self,
        new_config: JsonDict,
    ):
        """
        Compatible avec main.py hot reload.

        Accepte :
        - {"config": {"MIN_SCORE": 8.0}}
        - {"MIN_SCORE": 8.0}
        - {"min_score": 8.0}
        """

        try:
            if not isinstance(new_config, dict):
                return

            raw = new_config.get("config", new_config)

            if not isinstance(raw, dict):
                return

            if "MIN_SCORE" in raw or "min_score" in raw:
                incoming = raw.get("MIN_SCORE", raw.get("min_score"))
                incoming = _safe_float(incoming, self.DEFAULT_MIN_SCORE)

                if incoming < self.MIN_SCORE_FLOOR:
                    logger.warning(
                        f"🛡️ AutoOptimizer : MIN_SCORE {incoming} refusé, "
                        f"floor={self.MIN_SCORE_FLOOR}"
                    )

                self.current_config["min_score"] = self._clamp_min_score(
                    incoming
                )

            if "MAX_ALERTS_PER_HOUR" in raw or "max_alerts_per_hour" in raw:
                incoming_alerts = raw.get(
                    "MAX_ALERTS_PER_HOUR",
                    raw.get("max_alerts_per_hour"),
                )

                self.current_config["max_alerts_per_hour"] = max(
                    1,
                    _safe_int(
                        incoming_alerts,
                        self.DEFAULT_MAX_ALERTS_PER_HOUR,
                    ),
                )

            self._save_config()

        except Exception as exc:
            logger.warning(f"AutoOptimizer update_config skip: {exc}")

    # ════════════════════════════════════════
    # PUBLIC API
    # ════════════════════════════════════════

    def get_current_config(self) -> dict:
        return self.current_config.copy()

    def get_min_score(self) -> float:
        return self._clamp_min_score(
            self.current_config.get(
                "min_score",
                self.DEFAULT_MIN_SCORE,
            )
        )

    def get_max_alerts_per_hour(self) -> int:
        return _safe_int(
            self.current_config.get("max_alerts_per_hour"),
            self.DEFAULT_MAX_ALERTS_PER_HOUR,
        )

    def get_stats(self) -> dict:
        return {
            "total_optimizations": self.total_optimizations,
            "last_optimization": self.last_optimization,
            "current_min_score": self.get_min_score(),
            "current_max_alerts_per_hour": self.get_max_alerts_per_hour(),
            "history_count": len(self.optimization_history),
            "min_score_floor": self.MIN_SCORE_FLOOR,
            "min_score_ceiling": self.MIN_SCORE_CEILING,
            "last_stats": self.last_stats,
            "last_changes": self.last_changes,
            "paper_trading_only": True,
            "auto_trading": False,
        }

    def get_history(self) -> list:
        return self.optimization_history.copy()

    # ════════════════════════════════════════
    # STATS SOURCES
    # ════════════════════════════════════════

    def _load_simulator_stats(self) -> JsonDict:
        """
        Lit data/simulations.json.

        Si le futur simulateur v1.4 realistic existe, on utilisera ses champs realistic.
        Sinon on utilise les champs classiques mais on reste très conservateur.
        """

        path = _data_dir() / "simulations.json"
        data = self._load_json(path, {})

        if not isinstance(data, dict):
            return self._empty_sim_stats()

        history = data.get("history", [])

        if not isinstance(history, list):
            return self._empty_sim_stats()

        closed = [
            trade
            for trade in history
            if isinstance(trade, dict) and trade.get("closed")
        ]

        trades = len(closed)

        if trades <= 0:
            return self._empty_sim_stats()

        has_realistic = any(
            "realistic_pnl_pct" in trade
            or "realistic_pnl_eur" in trade
            for trade in closed
        )

        pnl_pcts: List[float] = []
        pnl_eurs: List[float] = []

        for trade in closed:
            if "realistic_pnl_pct" in trade:
                pnl_pct = _safe_float(trade.get("realistic_pnl_pct"))
            else:
                pnl_pct = _safe_float(trade.get("pnl_pct"))

            if "realistic_pnl_eur" in trade:
                pnl_eur = _safe_float(trade.get("realistic_pnl_eur"))
            else:
                pnl_eur = _safe_float(trade.get("pnl_eur"))

            pnl_pcts.append(pnl_pct)
            pnl_eurs.append(pnl_eur)

        wins = [
            pnl
            for pnl in pnl_pcts
            if pnl > 0
        ]

        losses = [
            pnl
            for pnl in pnl_pcts
            if pnl <= 0
        ]

        win_rate = len(wins) / trades * 100

        avg_pnl_pct = (
            sum(pnl_pcts) / trades
            if trades
            else 0.0
        )

        worst_pnl_pct = (
            min(pnl_pcts)
            if pnl_pcts
            else 0.0
        )

        total_invested = trades * 10.0
        total_pnl_eur = sum(pnl_eurs)

        roi_pct = (
            total_pnl_eur / total_invested * 100
            if total_invested > 0
            else 0.0
        )

        big_losses = [
            pnl
            for pnl in pnl_pcts
            if pnl <= -25
        ]

        big_loss_rate = len(big_losses) / trades * 100

        return {
            "trades": trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "roi_pct": round(roi_pct, 1),
            "avg_pnl_pct": round(avg_pnl_pct, 1),
            "worst_pnl_pct": round(worst_pnl_pct, 1),
            "big_loss_rate": round(big_loss_rate, 1),
            "has_realistic": has_realistic,
            "total_pnl_eur": round(total_pnl_eur, 2),
        }

    def _empty_sim_stats(self) -> JsonDict:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "roi_pct": 0.0,
            "avg_pnl_pct": 0.0,
            "worst_pnl_pct": 0.0,
            "big_loss_rate": 0.0,
            "has_realistic": False,
            "total_pnl_eur": 0.0,
        }

    def _load_ml_stats(self) -> JsonDict:
        try:
            if self.ml_scorer and hasattr(self.ml_scorer, "get_stats"):
                stats = self.ml_scorer.get_stats() or {}

                if isinstance(stats, dict):
                    return {
                        "trades": _safe_int(stats.get("trades"), 0),
                        "win_rate": _safe_float(stats.get("win_rate"), 0.0),
                        "avg_pnl": _safe_float(stats.get("avg_pnl"), 0.0),
                    }

        except Exception:
            pass

        return {
            "trades": 0,
            "win_rate": 0.0,
            "avg_pnl": 0.0,
        }

    def _load_bull_stats(self) -> JsonDict:
        try:
            if self.bull_analyzer and hasattr(self.bull_analyzer, "get_stats"):
                stats = self.bull_analyzer.get_stats(days=7) or {}

                if isinstance(stats, dict):
                    return stats

        except Exception:
            pass

        # fallback data/bulls_history.json
        data = self._load_json(
            _data_dir() / "bulls_history.json",
            [],
        )

        if isinstance(data, list):
            return {
                "total": len(data),
            }

        if isinstance(data, dict):
            return {
                "total": len(data),
            }

        return {
            "total": 0,
        }

    # ════════════════════════════════════════
    # DECISION LOGIC
    # ════════════════════════════════════════

    def _decide_new_min_score(
        self,
        current: float,
        sim_stats: JsonDict,
        ml_stats: JsonDict,
    ) -> tuple[float, List[str]]:
        changes: List[str] = []

        trades = _safe_int(sim_stats.get("trades"), 0)
        win_rate = _safe_float(sim_stats.get("win_rate"), 0.0)
        roi_pct = _safe_float(sim_stats.get("roi_pct"), 0.0)
        worst_pnl = _safe_float(sim_stats.get("worst_pnl_pct"), 0.0)
        big_loss_rate = _safe_float(sim_stats.get("big_loss_rate"), 0.0)
        has_realistic = bool(sim_stats.get("has_realistic", False))

        ml_trades = _safe_int(ml_stats.get("trades"), 0)
        ml_win_rate = _safe_float(ml_stats.get("win_rate"), 0.0)
        ml_avg_pnl = _safe_float(ml_stats.get("avg_pnl"), 0.0)

        new_score = current

        # Sécurité : si current est déjà sous le floor, on corrige immédiatement.
        if current < self.MIN_SCORE_FLOOR:
            new_score = self.MIN_SCORE_FLOOR
            changes.append(
                f"🛡️ min_score remonté au floor {self.MIN_SCORE_FLOOR}"
            )
            return new_score, changes

        # Pas assez de données : ne jamais baisser.
        if trades < self.MIN_TRADES_FOR_ANALYSIS:
            changes.append(
                f"⏸️ Pas assez de trades simulator "
                f"({trades}/{self.MIN_TRADES_FOR_ANALYSIS}) → maintien"
            )
            return new_score, changes

        # Win rate irréaliste sans realistic mode : suspect.
        if win_rate >= 80 and not has_realistic:
            changes.append(
                f"⚠️ Win rate simulator {win_rate:.0f}% suspect "
                f"sans realistic PnL → aucune baisse"
            )
            return new_score, changes

        # ML aussi peut être biaisé par le paper idéal.
        if ml_win_rate >= 80 and ml_trades >= 30 and not has_realistic:
            changes.append(
                f"⚠️ Win rate ML {ml_win_rate:.0f}% suspect "
                f"sans realistic PnL → aucune baisse"
            )
            return new_score, changes

        # Stats très mauvaises : on durcit fort.
        if roi_pct < -5 or big_loss_rate >= 20 or worst_pnl <= -40:
            new_score = min(
                self.MIN_SCORE_CEILING,
                current + 0.3,
            )

            changes.append(
                f"🔒 Risque élevé ROI {roi_pct:+.1f}% / "
                f"big losses {big_loss_rate:.0f}% / worst {worst_pnl:+.1f}% "
                f"→ min_score +0.3"
            )

            return new_score, changes

        # Stats faibles : on durcit légèrement.
        if roi_pct < 0 or win_rate < 30:
            new_score = min(
                self.MIN_SCORE_CEILING,
                current + 0.2,
            )

            changes.append(
                f"🔒 Performance faible WR {win_rate:.0f}% / "
                f"ROI {roi_pct:+.1f}% → min_score +0.2"
            )

            return new_score, changes

        # Performance correcte : maintien tant que l'échantillon est limité.
        if trades < self.MIN_TRADES_FOR_LOWERING:
            changes.append(
                f"✅ Performance correcte mais échantillon limité "
                f"({trades}/{self.MIN_TRADES_FOR_LOWERING}) → maintien"
            )

            return new_score, changes

        # Baisse autorisée seulement en mode realistic + stats solides.
        if (
            has_realistic
            and roi_pct >= 8
            and win_rate >= 40
            and big_loss_rate <= 8
            and worst_pnl > -30
            and ml_avg_pnl >= 0
        ):
            new_score = max(
                self.MIN_SCORE_FLOOR,
                current - 0.1,
            )

            changes.append(
                f"📈 Realistic ROI {roi_pct:+.1f}% solide "
                f"→ min_score -0.1 max"
            )

            return new_score, changes

        changes.append(
            f"✅ Maintien min_score : "
            f"WR {win_rate:.0f}% / ROI {roi_pct:+.1f}% / "
            f"realistic={has_realistic}"
        )

        return new_score, changes

    async def _run_optimization(self):
        logger.info("🎯 Optimisation SAFE en cours...")

        current = self.get_min_score()

        sim_stats = self._load_simulator_stats()
        ml_stats = self._load_ml_stats()
        bull_stats = self._load_bull_stats()

        old_config = self.current_config.copy()

        new_score, changes = self._decide_new_min_score(
            current=current,
            sim_stats=sim_stats,
            ml_stats=ml_stats,
        )

        new_score = self._clamp_min_score(new_score)

        self.current_config["min_score"] = new_score

        self.last_stats = {
            "simulator": sim_stats,
            "ml": ml_stats,
            "bulls": bull_stats,
        }

        self.last_changes = changes

        self.total_optimizations += 1
        self.last_optimization = time.time()

        self.optimization_history.append(
            {
                "timestamp": _utc_now_iso(),
                "old_config": old_config,
                "new_config": self.current_config.copy(),
                "changes": changes,
                "sim_stats": sim_stats,
                "ml_stats": ml_stats,
                "bull_stats": bull_stats,
            }
        )

        if len(self.optimization_history) > 100:
            self.optimization_history = self.optimization_history[-100:]

        self._save_config()

        await self._send_optimization_report(
            old_config=old_config,
            new_config=self.current_config,
            changes=changes,
            sim_stats=sim_stats,
            ml_stats=ml_stats,
            bull_stats=bull_stats,
        )

        if old_config.get("min_score") != self.current_config.get("min_score"):
            logger.info(
                f"🎯 Optimisation SAFE terminée : "
                f"MIN_SCORE {old_config.get('min_score')} → "
                f"{self.current_config.get('min_score')}"
            )

        else:
            logger.info(
                f"🎯 Optimisation SAFE terminée : "
                f"MIN_SCORE maintenu à {self.current_config.get('min_score')}"
            )

    # ════════════════════════════════════════
    # TELEGRAM REPORT
    # ════════════════════════════════════════

    async def _send_optimization_report(
        self,
        old_config: dict,
        new_config: dict,
        changes: List[str],
        sim_stats: dict,
        ml_stats: dict,
        bull_stats: dict,
    ):
        try:
            if not self.alert_sender:
                return

            if not hasattr(self.alert_sender, "_send_telegram"):
                return

            trades = _safe_int(sim_stats.get("trades"), 0)
            win_rate = _safe_float(sim_stats.get("win_rate"), 0.0)
            roi = _safe_float(sim_stats.get("roi_pct"), 0.0)
            avg_pnl = _safe_float(sim_stats.get("avg_pnl_pct"), 0.0)
            worst = _safe_float(sim_stats.get("worst_pnl_pct"), 0.0)
            big_loss = _safe_float(sim_stats.get("big_loss_rate"), 0.0)
            realistic = "OUI" if sim_stats.get("has_realistic") else "NON"

            ml_trades = _safe_int(ml_stats.get("trades"), 0)
            ml_wr = _safe_float(ml_stats.get("win_rate"), 0.0)
            ml_avg = _safe_float(ml_stats.get("avg_pnl"), 0.0)

            bulls_total = (
                bull_stats.get("total")
                or bull_stats.get("bulls")
                or 0
            )

            if changes:
                changes_text = "\n".join(
                    f"• {self._esc(change)}"
                    for change in changes
                )
            else:
                changes_text = "• Aucun changement"

            old_score = old_config.get("min_score", "?")
            new_score = new_config.get("min_score", "?")

            if old_score == new_score:
                score_line = f"⚙️ min\\_score maintenu : `{new_score}`"
            else:
                score_line = (
                    f"⚙️ min\\_score : `{old_score}` → `{new_score}`"
                )

            msg = (
                "🎯 *AUTO\\-OPTIMIZER SAFE v2\\.0*\n"
                "━━━━━━━━━━━━━━\n\n"
                "📊 *Analyse Simulator :*\n"
                f"Trades : `{trades}`\n"
                f"Win rate : `{win_rate:.1f}%`\n"
                f"ROI : `{roi:+.1f}%`\n"
                f"PnL moyen : `{avg_pnl:+.1f}%`\n"
                f"Pire trade : `{worst:+.1f}%`\n"
                f"Big loss rate : `{big_loss:.1f}%`\n"
                f"Realistic PnL : `{self._esc(realistic)}`\n\n"
                "🧠 *Analyse ML :*\n"
                f"Trades : `{ml_trades}`\n"
                f"Win rate : `{ml_wr:.1f}%`\n"
                f"PnL moyen : `{ml_avg:+.1f}%`\n\n"
                "🎯 *Analyse Bulls \\(7j\\) :*\n"
                f"Bulls détectés : `{bulls_total}`\n\n"
                "━━━━━━━━━━━━━━\n"
                "🔧 *DÉCISION :*\n\n"
                f"{score_line}\n"
                f"🛡️ Floor sécurité : `{self.MIN_SCORE_FLOOR}`\n\n"
                f"{changes_text}\n\n"
                "━━━━━━━━━━━━━━\n"
                f"📈 Total optimisations : `{self.total_optimizations}`\n"
                f"⏰ Prochaine analyse dans "
                f"`{int(self.OPTIMIZATION_INTERVAL / 3600)}h`"
            )

            await self.alert_sender._send_telegram(msg)

        except Exception as exc:
            logger.error(f"Optimizer report error : {exc}")

    def _esc(
        self,
        text: Any,
    ) -> str:
        special = r"_*[]()~`>#+-=|{}.!"
        return "".join(
            f"\\{char}" if char in special else char
            for char in str(text)
        )


__all__ = [
    "AutoOptimizer",
]