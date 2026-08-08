"""
MemeSniper v14.1-EVOLUTION
Drift Guard robuste

Objectifs :
- Détecter si les tokens récents sont très différents de la baseline
- Ne fait AUCUN trading automatique
- Par défaut, ne bloque pas le bot
- Expose des flags compatibles avec main.py :
  - trading_paused
  - auto_evolution_paused
  - is_trading_allowed()
  - is_evolution_allowed()
  - get_status()
"""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


from .event_store import get_event_store, log_event


JsonDict = Dict[str, Any]


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


def _safe_float(
    value: Any,
    default: Optional[float] = None,
) -> Optional[float]:
    try:
        if value is None or value == "":
            return default

        value = float(str(value).replace(",", "."))

        if math.isnan(value) or math.isinf(value):
            return default

        return value

    except Exception:
        return default


def _env_bool(
    name: str,
    default: bool = False,
) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    return str(raw).strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
        "oui",
    )


def _env_int(
    name: str,
    default: int,
) -> int:
    try:
        return int(
            float(
                str(
                    os.getenv(name, str(default))
                ).replace(",", ".")
            )
        )
    except Exception:
        return default


def _env_float(
    name: str,
    default: float,
) -> float:
    try:
        return float(
            str(
                os.getenv(name, str(default))
            ).replace(",", ".")
        )
    except Exception:
        return default


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class DriftConfig:
    lookback_hours: int = field(
        default_factory=lambda: _env_int(
            "DRIFT_LOOKBACK_HOURS",
            24,
        )
    )

    min_samples: int = field(
        default_factory=lambda: _env_int(
            "DRIFT_MIN_SAMPLES",
            20,
        )
    )

    drift_threshold: float = field(
        default_factory=lambda: _env_float(
            "DRIFT_THRESHOLD",
            2.0,
        )
    )

    # Par défaut, le Drift Guard observe seulement.
    # Il ne bloque pas les alertes/paper trading.
    pause_trading_on_drift: bool = field(
        default_factory=lambda: _env_bool(
            "DRIFT_PAUSE_TRADING",
            False,
        )
    )

    pause_evolution_on_drift: bool = field(
        default_factory=lambda: _env_bool(
            "DRIFT_PAUSE_EVOLUTION",
            False,
        )
    )

    baseline_path: Path = field(
        default_factory=lambda: (
            _data_dir() / "evolution" / "drift_baseline.json"
        )
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
    def __init__(
        self,
        config: Optional[DriftConfig] = None,
    ) -> None:
        self.config = config or DriftConfig()

        self.config.baseline_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.event_store = get_event_store()
        self._lock = threading.RLock()
        self.baseline = self._load_baseline()

        # Compatibilité main.py / dashboard.
        self.trading_paused = False
        self.auto_evolution_paused = False

        self.pause_reason: Optional[str] = None
        self.evolution_pause_reason: Optional[str] = None

        self.last_drift_score = 0.0
        self.last_status = "unknown"
        self.last_check_at: Optional[str] = None
        self.last_result: JsonDict = {}

    def _load_baseline(self) -> JsonDict:
        try:
            if not self.config.baseline_path.exists():
                return {}

            data = json.loads(
                self.config.baseline_path.read_text(
                    encoding="utf-8",
                )
            )

            if isinstance(data, dict):
                return data

            return {}

        except Exception:
            return {}

    def _save_baseline(self) -> None:
        try:
            self.config.baseline_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            self.config.baseline_path.write_text(
                json.dumps(
                    self.baseline,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        except Exception:
            pass

    def _extract_feature_value(
        self,
        event: JsonDict,
        feature: str,
    ) -> Optional[float]:
        meta = event.get("meta") or {}

        if not isinstance(meta, dict):
            meta = {}

        features = (
            event.get("features")
            or meta.get("features")
            or {}
        )

        if not isinstance(features, dict):
            features = {}

        for container in (event, meta, features):
            if feature in container:
                value = _safe_float(container.get(feature))

                if value is not None:
                    return value

        aliases = {
            "score": [
                "composite_score",
            ],
            "safety_score": [
                "safety",
                "token_safety_score",
            ],
            "social_score": [
                "social",
                "twitter_score",
            ],
            "momentum_score": [
                "momentum",
                "momentum_detector_score",
            ],
            "liquidity": [
                "onchain_liquidity_usd",
                "liquidity_usd",
            ],
            "market_cap": [
                "mcap",
                "marketcap",
                "market_cap_usd",
            ],
            "volume_24h": [
                "volume",
                "volume24h",
                "volume_usd",
            ],
            "holders": [
                "onchain_holder_count",
                "holder_count",
            ],
        }

        for alias in aliases.get(feature, []):
            for container in (event, meta, features):
                if alias in container:
                    value = _safe_float(container.get(alias))

                    if value is not None:
                        return value

        return None

    def _collect_recent_vectors(self) -> Dict[str, List[float]]:
        since = _utc_now() - timedelta(
            hours=max(1, int(self.config.lookback_hours))
        )

        try:
            events = self.event_store.query_events(
                since=since,
                limit=10000,
                ascending=True,
            )

        except Exception:
            events = []

        vectors: Dict[str, List[float]] = {
            feature: []
            for feature in self.config.features
        }

        for event in events:
            for feature in self.config.features:
                value = self._extract_feature_value(
                    event,
                    feature,
                )

                if value is not None:
                    vectors[feature].append(float(value))

        return vectors

    def _stats(
        self,
        values: List[float],
    ) -> JsonDict:
        if not values:
            return {
                "count": 0,
                "mean": 0.0,
                "std": 0.0,
            }

        mean = sum(values) / len(values)

        if len(values) <= 1:
            std = 0.0
        else:
            std = math.sqrt(
                max(
                    sum((x - mean) ** 2 for x in values)
                    / (len(values) - 1),
                    0.0,
                )
            )

        return {
            "count": len(values),
            "mean": mean,
            "std": std,
        }

    def _build_baseline(
        self,
        vectors: Dict[str, List[float]],
    ) -> JsonDict:
        return {
            "created_at": _utc_now().isoformat(),
            "updated_at": _utc_now().isoformat(),
            "features": {
                feature: self._stats(values)
                for feature, values in vectors.items()
            },
        }

    def _update_baseline_slowly(
        self,
        vectors: Dict[str, List[float]],
        alpha: float = 0.10,
    ) -> None:
        if not self.baseline:
            self.baseline = self._build_baseline(vectors)
            self._save_baseline()
            return

        features = self.baseline.setdefault("features", {})

        for feature, values in vectors.items():
            recent = self._stats(values)

            if recent["count"] <= 0:
                continue

            old = features.get(feature) or {
                "count": 0,
                "mean": 0.0,
                "std": 0.0,
            }

            old_count = int(old.get("count", 0) or 0)
            old_mean = float(old.get("mean", 0.0) or 0.0)
            old_std = float(old.get("std", 0.0) or 0.0)

            features[feature] = {
                "count": old_count + recent["count"],
                "mean": (
                    (1 - alpha) * old_mean
                    + alpha * recent["mean"]
                ),
                "std": max(
                    (1 - alpha) * old_std
                    + alpha * recent["std"],
                    0.0001,
                ),
            }

        self.baseline["updated_at"] = _utc_now().isoformat()

        self._save_baseline()

    def _apply_pause_policy(
        self,
        status: str,
        drift_score: float,
        drifting_features: List[str],
    ) -> None:
        # Par défaut : observation seulement.
        self.trading_paused = False
        self.auto_evolution_paused = False
        self.pause_reason = None
        self.evolution_pause_reason = None

        if (
            status == "drift_detected"
            and self.config.pause_trading_on_drift
        ):
            self.trading_paused = True
            self.pause_reason = (
                f"drift_score={drift_score:.2f} "
                f"features={','.join(drifting_features[:4])}"
            )

        if (
            status == "drift_detected"
            and self.config.pause_evolution_on_drift
        ):
            self.auto_evolution_paused = True
            self.evolution_pause_reason = (
                f"drift_score={drift_score:.2f}"
            )

    def check_drift(
        self,
        update_baseline: bool = True,
    ) -> JsonDict:
        with self._lock:
            vectors = self._collect_recent_vectors()

            total_samples = max(
                (len(v) for v in vectors.values()),
                default=0,
            )

            if total_samples < self.config.min_samples:
                result = DriftResult(
                    status="skipped",
                    drift_score=0.0,
                    samples=total_samples,
                    drifting_features=[],
                    details={
                        "reason": "not_enough_samples",
                        "required": self.config.min_samples,
                    },
                )

                self.last_status = result.status
                self.last_drift_score = 0.0
                self.last_check_at = _utc_now().isoformat()
                self.last_result = result.__dict__

                self._apply_pause_policy(
                    result.status,
                    0.0,
                    [],
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
                    details={
                        "baseline_path": str(
                            self.config.baseline_path
                        )
                    },
                )

                self.last_status = result.status
                self.last_drift_score = 0.0
                self.last_check_at = _utc_now().isoformat()
                self.last_result = result.__dict__

                self._apply_pause_policy(
                    result.status,
                    0.0,
                    [],
                )

                log_event(
                    "drift_baseline_created",
                    "drift_guard",
                    status="baseline_created",
                    samples=total_samples,
                )

                return result.__dict__

            drift_scores: JsonDict = {}
            drifting_features: List[str] = []

            baseline_features = self.baseline.get("features") or {}

            for feature in self.config.features:
                recent_stats = self._stats(
                    vectors.get(feature, [])
                )

                base_stats = baseline_features.get(feature) or {}

                if recent_stats["count"] <= 0:
                    continue

                base_mean = float(
                    base_stats.get("mean", 0.0) or 0.0
                )

                base_std = float(
                    base_stats.get("std", 0.0) or 0.0
                )

                recent_mean = float(
                    recent_stats.get("mean", 0.0) or 0.0
                )

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
                global_drift = (
                    sum(
                        x["z_score"]
                        for x in drift_scores.values()
                    )
                    / len(drift_scores)
                )
            else:
                global_drift = 0.0

            status = (
                "drift_detected"
                if drifting_features
                else "stable"
            )

            self._apply_pause_policy(
                status,
                global_drift,
                drifting_features,
            )

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

            self.last_status = status
            self.last_drift_score = global_drift
            self.last_check_at = _utc_now().isoformat()
            self.last_result = result.__dict__

            log_event(
                "drift_check",
                "drift_guard",
                status=status,
                drift_score=global_drift,
                samples=total_samples,
                meta={
                    "drifting_features": drifting_features,
                    "threshold": self.config.drift_threshold,
                },
            )

            if update_baseline and status == "stable":
                self._update_baseline_slowly(vectors)

            return result.__dict__

    async def check_drift_async(
        self,
        update_baseline: bool = True,
    ) -> JsonDict:
        return self.check_drift(update_baseline=update_baseline)

    def is_trading_paused(self) -> bool:
        return bool(self.trading_paused)

    def is_trading_allowed(self) -> bool:
        return not bool(self.trading_paused)

    def is_evolution_allowed(self) -> bool:
        return not bool(self.auto_evolution_paused)

    def get_status(self) -> JsonDict:
        return {
            "status": self.last_status,
            "trading_paused": bool(self.trading_paused),
            "auto_evolution_paused": bool(
                self.auto_evolution_paused
            ),
            "pause_reason": self.pause_reason,
            "evolution_pause_reason": self.evolution_pause_reason,
            "last_drift_score": float(
                self.last_drift_score or 0.0
            ),
            "last_check_at": self.last_check_at,
            "baseline_path": str(self.config.baseline_path),
            "paper_trading_only": True,
            "auto_trading": False,
            "last_result": self.last_result,
        }


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