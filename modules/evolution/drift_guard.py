"""
MemeSniper v14.1-EVOLUTION
Drift Guard

Objectif :
- Détecter si les tokens récents sont très différents de la baseline
- Alerter/logguer seulement
- Ne bloque pas le bot
- Ne fait aucun trading automatique
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .event_store import get_event_store, log_event


JsonDict = Dict[str, Any]


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DriftConfig:
    lookback_hours: int = 24
    min_samples: int = 20
    drift_threshold: float = 2.0
    baseline_path: Path = field(
        default_factory=lambda: Path("data") / "evolution" / "drift_baseline.json"
    )
    features: List[str] = field(
        default_factory=lambda: [
            "score",
            "safety_score",
            "social_score",
            "momentum_score",
            "liquidity",
            "market_cap",
            "volume_24h",
            "holders",
        ]
    )


@dataclass
class DriftResult:
    status: str
    drift_score: float
    samples: int
    drifting_features: List[str]
    details: JsonDict


class DriftGuard:
    def __init__(self, config: Optional[DriftConfig] = None) -> None:
        self.config = config or DriftConfig()
        self.config.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        self.event_store = get_event_store()
        self._lock = threading.RLock()
        self.baseline = self._load_baseline()

        # Compatibilité avec le health-check du bot.
        # Le Drift Guard ne doit PAS bloquer les alertes/paper trading.
        self.trading_paused = False
        self.pause_reason = None
        self.last_drift_score = 0.0
        self.last_status = "unknown"
        self.last_check_at = None

    def _load_baseline(self) -> JsonDict:
        path = self.config.baseline_path

        if not path.exists():
            return {}

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
            return {}
        except Exception:
            return {}

    def _save_baseline(self) -> None:
        self.config.baseline_path.write_text(
            json.dumps(self.baseline, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _extract_feature_value(self, event: JsonDict, feature: str) -> Optional[float]:
        meta = event.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}

        if feature in event:
            value = _safe_float(event.get(feature))
            if value is not None:
                return value

        if feature in meta:
            value = _safe_float(meta.get(feature))
            if value is not None:
                return value

        aliases = {
            "safety_score": ["safety", "token_safety_score"],
            "social_score": ["social", "twitter_score"],
            "momentum_score": ["momentum", "momentum_detector_score"],
            "volume_24h": ["volume", "volume24h", "volume_usd"],
            "market_cap": ["mcap", "marketcap", "market_cap_usd"],
        }

        for alias in aliases.get(feature, []):
            if alias in event:
                value = _safe_float(event.get(alias))
                if value is not None:
                    return value
            if alias in meta:
                value = _safe_float(meta.get(alias))
                if value is not None:
                    return value

        return None

    def _collect_recent_vectors(self) -> Dict[str, List[float]]:
        since = _utc_now() - timedelta(hours=self.config.lookback_hours)
        events = self.event_store.query_events(since=since, limit=10000, ascending=True)

        vectors: Dict[str, List[float]] = {feature: [] for feature in self.config.features}

        for event in events:
            for feature in self.config.features:
                value = self._extract_feature_value(event, feature)
                if value is not None and not math.isnan(value):
                    vectors[feature].append(float(value))

        return vectors

    def _stats(self, values: List[float]) -> JsonDict:
        if not values:
            return {"count": 0, "mean": 0.0, "std": 0.0}

        mean = sum(values) / len(values)

        if len(values) <= 1:
            std = 0.0
        else:
            variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
            std = math.sqrt(max(variance, 0.0))

        return {
            "count": len(values),
            "mean": mean,
            "std": std,
        }

    def _build_baseline(self, vectors: Dict[str, List[float]]) -> JsonDict:
        baseline = {
            "created_at": _utc_now().isoformat(),
            "updated_at": _utc_now().isoformat(),
            "features": {},
        }

        for feature, values in vectors.items():
            baseline["features"][feature] = self._stats(values)

        return baseline

    def _update_baseline_slowly(self, vectors: Dict[str, List[float]], alpha: float = 0.10) -> None:
        if not self.baseline:
            self.baseline = self._build_baseline(vectors)
            self._save_baseline()
            return

        features = self.baseline.setdefault("features", {})

        for feature, values in vectors.items():
            recent = self._stats(values)
            old = features.get(feature) or {"count": 0, "mean": 0.0, "std": 0.0}

            if recent["count"] <= 0:
                continue

            old_count = int(old.get("count", 0) or 0)
            old_mean = float(old.get("mean", 0.0) or 0.0)
            old_std = float(old.get("std", 0.0) or 0.0)

            features[feature] = {
                "count": old_count + recent["count"],
                "mean": (1 - alpha) * old_mean + alpha * recent["mean"],
                "std": max((1 - alpha) * old_std + alpha * recent["std"], 0.0001),
            }

        self.baseline["updated_at"] = _utc_now().isoformat()
        self._save_baseline()

    def check_drift(self, update_baseline: bool = True) -> JsonDict:
        with self._lock:
            vectors = self._collect_recent_vectors()
            total_samples = max((len(v) for v in vectors.values()), default=0)

            if total_samples < self.config.min_samples:
                result = DriftResult(
                    status="skipped",
                    drift_score=0.0,
                    samples=total_samples,
                    drifting_features=[],
                    details={"reason": "not_enough_samples"},
                )

                log_event(
                    "drift_check_skipped",
                    "drift_guard",
                    status="skipped",
                    samples=total_samples,
                    required=self.config.min_samples,
                    meta={"reason": "not_enough_samples"},
                )

                return result.__dict__

            if not self.baseline:
                self.baseline = self._build_baseline(vectors)
                self._save_baseline()

                result = DriftResult(
                    status="baseline_created",
                    drift_score=0.0,
                    samples=total_samples,
                    drifting_features=[],
                    details={"baseline_path": str(self.config.baseline_path)},
                )

                log_event(
                    "drift_baseline_created",
                    "drift_guard",
                    status="baseline_created",
                    samples=total_samples,
                    meta={"baseline_path": str(self.config.baseline_path)},
                )

                return result.__dict__

            drift_scores: JsonDict = {}
            drifting_features: List[str] = []

            baseline_features = self.baseline.get("features") or {}

            for feature in self.config.features:
                recent_stats = self._stats(vectors.get(feature, []))
                base_stats = baseline_features.get(feature) or {}

                if recent_stats["count"] <= 0:
                    continue

                base_mean = float(base_stats.get("mean", 0.0) or 0.0)
                base_std = float(base_stats.get("std", 0.0) or 0.0)
                recent_mean = float(recent_stats.get("mean", 0.0) or 0.0)

                denom = max(base_std, 0.25)
                z_score = abs(recent_mean - base_mean) / denom

                drift_scores[feature] = {
                    "z_score": z_score,
                    "baseline_mean": base_mean,
                    "recent_mean": recent_mean,
                    "baseline_std": base_std,
                    "recent_std": recent_stats["std"],
                    "samples": recent_stats["count"],
                }

                if z_score >= self.config.drift_threshold:
                    drifting_features.append(feature)

            if drift_scores:
                global_drift = sum(x["z_score"] for x in drift_scores.values()) / len(drift_scores)
            else:
                global_drift = 0.0

            status = "drift_detected" if drifting_features else "stable"

            result = DriftResult(
                status=status,
                drift_score=global_drift,
                samples=total_samples,
                drifting_features=drifting_features,
                details={
                    "feature_scores": drift_scores,
                    "threshold": self.config.drift_threshold,
                },
            )

            log_event(
                "drift_check",
                "drift_guard",
                status=status,
                drift_score=global_drift,
                samples=total_samples,
                meta={
                    "drifting_features": drifting_features,
                    "feature_scores": drift_scores,
                    "threshold": self.config.drift_threshold,
                },
            )

            if update_baseline and status == "stable":
                self._update_baseline_slowly(vectors)

            return result.__dict__

    async def check_drift_async(self, update_baseline: bool = True) -> JsonDict:
        return self.check_drift(update_baseline=update_baseline)


    def get_status(self) -> JsonDict:
        """
        Status de compatibilité pour le dashboard / health-check.
        """

        return {
            "status": getattr(self, "last_status", "unknown"),
            "trading_paused": bool(getattr(self, "trading_paused", False)),
            "pause_reason": getattr(self, "pause_reason", None),
            "last_drift_score": float(getattr(self, "last_drift_score", 0.0) or 0.0),
            "last_check_at": getattr(self, "last_check_at", None),
            "paper_trading_only": True,
            "auto_trading": False,
        }

    def is_trading_paused(self) -> bool:
        return bool(getattr(self, "trading_paused", False))


_DRIFT_GUARD: Optional[DriftGuard] = None
_LOCK = threading.RLock()


def get_drift_guard() -> DriftGuard:
    global _DRIFT_GUARD

    with _LOCK:
        if _DRIFT_GUARD is None:
            _DRIFT_GUARD = DriftGuard()
        return _DRIFT_GUARD


__all__ = [
    "DriftConfig",
    "DriftResult",
    "DriftGuard",
    "get_drift_guard",
]