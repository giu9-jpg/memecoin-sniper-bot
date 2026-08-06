"""
MemeSniper v14.1-EVOLUTION
Strategy Optimizer

Objectif :
- Optimiser progressivement les poids de scoring
- Fonctionne même sans beaucoup de data
- Ne fait aucun trading automatique
- Compatible Railway/local
"""

from __future__ import annotations

import json
import os
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .event_store import get_event_store, log_event


JsonDict = Dict[str, Any]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class StrategyConfig:
    min_samples: int = 25
    lookback_days: int = 14
    optimization_trials: int = 120
    min_score_floor: float = 5.0
    max_score_ceiling: float = 9.5
    output_path: Path = field(
        default_factory=lambda: Path("data") / "evolution" / "strategy_weights.json"
    )


@dataclass
class StrategyState:
    score_weight: float = 0.45
    safety_weight: float = 0.25
    social_weight: float = 0.15
    momentum_weight: float = 0.15
    alert_threshold: float = 7.5
    last_optimized_at: Optional[str] = None
    samples_used: int = 0
    objective_score: float = 0.0


class StrategyOptimizer:
    def __init__(self, config: Optional[StrategyConfig] = None) -> None:
        self.config = config or StrategyConfig()
        self.config.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_store = get_event_store()
        self._lock = threading.RLock()
        self.state = self._load_state()

    def _load_state(self) -> StrategyState:
        path = self.config.output_path

        if not path.exists():
            return StrategyState()

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return StrategyState(
                score_weight=_safe_float(raw.get("score_weight"), 0.45),
                safety_weight=_safe_float(raw.get("safety_weight"), 0.25),
                social_weight=_safe_float(raw.get("social_weight"), 0.15),
                momentum_weight=_safe_float(raw.get("momentum_weight"), 0.15),
                alert_threshold=_safe_float(raw.get("alert_threshold"), 7.5),
                last_optimized_at=raw.get("last_optimized_at"),
                samples_used=int(raw.get("samples_used", 0) or 0),
                objective_score=_safe_float(raw.get("objective_score"), 0.0),
            )
        except Exception:
            return StrategyState()

    def _save_state(self) -> None:
        payload = {
            "score_weight": self.state.score_weight,
            "safety_weight": self.state.safety_weight,
            "social_weight": self.state.social_weight,
            "momentum_weight": self.state.momentum_weight,
            "alert_threshold": self.state.alert_threshold,
            "last_optimized_at": self.state.last_optimized_at,
            "samples_used": self.state.samples_used,
            "objective_score": self.state.objective_score,
        }

        self.config.output_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def get_current_strategy(self) -> JsonDict:
        return {
            "score_weight": self.state.score_weight,
            "safety_weight": self.state.safety_weight,
            "social_weight": self.state.social_weight,
            "momentum_weight": self.state.momentum_weight,
            "alert_threshold": self.state.alert_threshold,
            "last_optimized_at": self.state.last_optimized_at,
            "samples_used": self.state.samples_used,
            "objective_score": self.state.objective_score,
        }

    def recommend_weights(self) -> JsonDict:
        return self.get_current_strategy()

    def _extract_training_rows(self) -> List[JsonDict]:
        since = _utc_now() - timedelta(days=self.config.lookback_days)
        events = self.event_store.query_events(since=since, limit=10000, ascending=True)

        rows: List[JsonDict] = []

        for event in events:
            meta = event.get("meta") or {}
            if not isinstance(meta, dict):
                meta = {}

            score = _safe_float(event.get("score"), _safe_float(meta.get("score"), 0.0))
            if score <= 0:
                continue

            pnl = _safe_float(
                event.get("pnl_pct"),
                _safe_float(meta.get("pnl_pct"), _safe_float(meta.get("paper_pnl_pct"), 0.0)),
            )

            outcome = str(event.get("outcome") or meta.get("outcome") or "").lower()

            if not outcome:
                if pnl > 5:
                    outcome = "win"
                elif pnl < -5:
                    outcome = "loss"
                else:
                    outcome = "neutral"

            rows.append(
                {
                    "score": score,
                    "safety": _safe_float(
                        meta.get("safety_score"),
                        _safe_float(meta.get("safety"), score),
                    ),
                    "social": _safe_float(
                        meta.get("social_score"),
                        _safe_float(meta.get("social"), 5.0),
                    ),
                    "momentum": _safe_float(
                        meta.get("momentum_score"),
                        _safe_float(meta.get("momentum"), 5.0),
                    ),
                    "pnl_pct": pnl,
                    "outcome": outcome,
                }
            )

        return rows

    def _candidate_score(
        self,
        rows: List[JsonDict],
        score_weight: float,
        safety_weight: float,
        social_weight: float,
        momentum_weight: float,
        threshold: float,
    ) -> float:
        total_weight = max(
            score_weight + safety_weight + social_weight + momentum_weight,
            0.0001,
        )

        normalized = {
            "score": score_weight / total_weight,
            "safety": safety_weight / total_weight,
            "social": social_weight / total_weight,
            "momentum": momentum_weight / total_weight,
        }

        objective = 0.0
        selected = 0

        for row in rows:
            final_score = (
                row["score"] * normalized["score"]
                + row["safety"] * normalized["safety"]
                + row["social"] * normalized["social"]
                + row["momentum"] * normalized["momentum"]
            )

            would_alert = final_score >= threshold

            pnl = _safe_float(row.get("pnl_pct"), 0.0)
            outcome = str(row.get("outcome") or "").lower()

            if would_alert:
                selected += 1

                if outcome in ("win", "winner", "profit", "tp"):
                    objective += 2.0
                elif outcome in ("loss", "loser", "sl", "rug"):
                    objective -= 2.5
                else:
                    objective += pnl / 10.0

                objective += max(min(pnl / 20.0, 2.0), -2.0)
            else:
                if outcome in ("loss", "loser", "sl", "rug"):
                    objective += 0.4
                elif outcome in ("win", "winner", "profit", "tp"):
                    objective -= 0.4

        if selected == 0:
            objective -= 5.0

        # Pénalise une stratégie qui alerte trop ou pas assez
        alert_ratio = selected / max(len(rows), 1)
        if alert_ratio > 0.35:
            objective -= (alert_ratio - 0.35) * 10
        if alert_ratio < 0.03:
            objective -= (0.03 - alert_ratio) * 10

        return objective

    def optimize(self, force: bool = False) -> JsonDict:
        with self._lock:
            rows = self._extract_training_rows()

            if len(rows) < self.config.min_samples and not force:
                result = {
                    "status": "skipped",
                    "reason": "not_enough_samples",
                    "samples": len(rows),
                    "required": self.config.min_samples,
                    "strategy": self.get_current_strategy(),
                }

                log_event(
                    "strategy_optimization_skipped",
                    "strategy_optimizer",
                    status="skipped",
                    samples=len(rows),
                    required=self.config.min_samples,
                    meta={"reason": "not_enough_samples"},
                )

                return result

            best = {
                "objective": float("-inf"),
                "score_weight": self.state.score_weight,
                "safety_weight": self.state.safety_weight,
                "social_weight": self.state.social_weight,
                "momentum_weight": self.state.momentum_weight,
                "alert_threshold": self.state.alert_threshold,
            }

            trials = max(10, int(self.config.optimization_trials))

            for _ in range(trials):
                score_w = random.uniform(0.25, 0.65)
                safety_w = random.uniform(0.10, 0.40)
                social_w = random.uniform(0.05, 0.30)
                momentum_w = random.uniform(0.05, 0.30)
                threshold = random.uniform(
                    self.config.min_score_floor,
                    self.config.max_score_ceiling,
                )

                objective = self._candidate_score(
                    rows,
                    score_w,
                    safety_w,
                    social_w,
                    momentum_w,
                    threshold,
                )

                if objective > best["objective"]:
                    best = {
                        "objective": objective,
                        "score_weight": score_w,
                        "safety_weight": safety_w,
                        "social_weight": social_w,
                        "momentum_weight": momentum_w,
                        "alert_threshold": threshold,
                    }

            total = max(
                best["score_weight"]
                + best["safety_weight"]
                + best["social_weight"]
                + best["momentum_weight"],
                0.0001,
            )

            self.state.score_weight = best["score_weight"] / total
            self.state.safety_weight = best["safety_weight"] / total
            self.state.social_weight = best["social_weight"] / total
            self.state.momentum_weight = best["momentum_weight"] / total
            self.state.alert_threshold = best["alert_threshold"]
            self.state.last_optimized_at = _utc_now().isoformat()
            self.state.samples_used = len(rows)
            self.state.objective_score = best["objective"]

            self._save_state()

            result = {
                "status": "optimized",
                "samples": len(rows),
                "strategy": self.get_current_strategy(),
            }

            log_event(
                "strategy_optimized",
                "strategy_optimizer",
                status="optimized",
                samples=len(rows),
                objective_score=self.state.objective_score,
                meta={"strategy": self.get_current_strategy()},
            )

            return result

    async def optimize_async(self, force: bool = False) -> JsonDict:
        return self.optimize(force=force)

    def record_trade_outcome(
        self,
        token_mint: str,
        token_symbol: Optional[str] = None,
        pnl_pct: Optional[float] = None,
        outcome: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        return log_event(
            "paper_trade_outcome",
            "strategy_optimizer",
            token_mint=token_mint,
            token_symbol=token_symbol,
            pnl_pct=pnl_pct,
            outcome=outcome,
            meta=kwargs,
        )


_STRATEGY_OPTIMIZER: Optional[StrategyOptimizer] = None
_LOCK = threading.RLock()


def get_strategy_optimizer() -> StrategyOptimizer:
    global _STRATEGY_OPTIMIZER

    with _LOCK:
        if _STRATEGY_OPTIMIZER is None:
            _STRATEGY_OPTIMIZER = StrategyOptimizer()
        return _STRATEGY_OPTIMIZER


__all__ = [
    "StrategyConfig",
    "StrategyState",
    "StrategyOptimizer",
    "get_strategy_optimizer",
]