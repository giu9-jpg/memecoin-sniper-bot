"""
MemeSniper v14.1-EVOLUTION
Feature Store Railway-safe

Objectifs :
- Pas d'import pandas/numpy au démarrage
- Stockage JSONL dans DATA_DIR/features
- Compatible avec l'Event Store actuel
- Sert de base pour l'analyse winners/losers et Auto-ML léger
- Aucun trading réel
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


JsonDict = Dict[str, Any]
FEATURE_VERSION = "4.0"


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default

        return float(str(value).replace(",", "."))

    except Exception:
        return default


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()

    return str(obj)


@dataclass
class FeatureVector:
    token_mint: str
    timestamp: float
    feature_version: str = FEATURE_VERSION
    features: JsonDict = field(default_factory=dict)
    feature_hash: str = ""

    def __post_init__(self) -> None:
        if not self.feature_hash:
            raw = json.dumps(
                self.features,
                sort_keys=True,
                default=_json_default,
            )

            self.feature_hash = hashlib.md5(
                raw.encode("utf-8")
            ).hexdigest()[:16]

    def to_dict(self) -> JsonDict:
        return {
            "token_mint": self.token_mint,
            "timestamp": self.timestamp,
            "feature_version": self.feature_version,
            "feature_hash": self.feature_hash,
            "features": self.features,
        }


@dataclass
class LabelSet:
    token_mint: str
    detection_ts: float
    labels: JsonDict = field(default_factory=dict)

    def to_dict(self) -> JsonDict:
        return {
            "token_mint": self.token_mint,
            "detection_ts": self.detection_ts,
            "labels": self.labels,
        }


class FeatureStore:
    def __init__(
        self,
        base_path: Optional[str | Path] = None,
    ) -> None:
        self.base_path = Path(
            base_path
            or os.getenv("FEATURE_STORE_PATH")
            or (_data_dir() / "features")
        )

        self.base_path.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()

    def _feature_path(
        self,
        ts: Optional[float] = None,
    ) -> Path:
        ts = ts or time.time()

        date_key = datetime.fromtimestamp(
            ts,
            tz=timezone.utc,
        ).strftime("%Y%m%d")

        return self.base_path / f"features_{date_key}.jsonl"

    def _label_path(
        self,
        ts: Optional[float] = None,
    ) -> Path:
        ts = ts or time.time()

        date_key = datetime.fromtimestamp(
            ts,
            tz=timezone.utc,
        ).strftime("%Y%m%d")

        return self.base_path / f"labels_{date_key}.jsonl"

    def extract_features(self, context: JsonDict) -> FeatureVector:
        """
        Extraction robuste depuis :
        - analysis
        - safety
        - event meta
        """

        meta = context.get("meta") or {}

        if not isinstance(meta, dict):
            meta = {}

        safety = context.get("safety") or meta.get("safety") or {}

        if not isinstance(safety, dict):
            safety = {}

        features = {
            "score": _safe_float(
                context.get("score", meta.get("score", 0))
            ),

            "safety_score": _safe_float(
                safety.get(
                    "score",
                    meta.get("safety_score", 0),
                )
            ),

            "liquidity": _safe_float(
                context.get(
                    "liquidity",
                    meta.get(
                        "liquidity",
                        meta.get("onchain_liquidity_usd", 0),
                    ),
                )
            ),

            "market_cap": _safe_float(
                context.get(
                    "market_cap",
                    meta.get("market_cap", 0),
                )
            ),

            "holders": _safe_float(
                context.get(
                    "holders",
                    meta.get(
                        "holders",
                        meta.get("onchain_holder_count", 0),
                    ),
                )
            ),

            "top10_pct": _safe_float(
                context.get(
                    "top10_pct",
                    meta.get(
                        "top10_pct",
                        meta.get("onchain_top10_pct", 100),
                    ),
                ),
                100,
            ),

            "age_minutes": _safe_float(
                context.get(
                    "age_minutes",
                    meta.get("age_minutes", 0),
                )
            ),

            "age_seconds": _safe_float(
                context.get(
                    "age",
                    meta.get("onchain_age_seconds", 0),
                )
            ),

            "volume_5m": _safe_float(
                context.get(
                    "volume_5m",
                    meta.get("volume_5m", 0),
                )
            ),

            "volume_1h": _safe_float(
                context.get(
                    "volume_1h",
                    meta.get("volume_1h", 0),
                )
            ),

            "volume_24h": _safe_float(
                context.get(
                    "volume_24h",
                    meta.get("volume_24h", 0),
                )
            ),

            "price_change_5m": _safe_float(
                context.get(
                    "price_change_5m",
                    meta.get("price_change_5m", 0),
                )
            ),

            "alpha_wallets": _safe_float(
                context.get(
                    "alpha_wallets",
                    meta.get("alpha_wallets", 0),
                )
            ),

            "conviction": _safe_float(
                context.get(
                    "conviction",
                    meta.get("conviction_factors", 0),
                )
            ),

            "twitter_mentions_5m": _safe_float(
                context.get(
                    "twitter_mentions_5m",
                    meta.get("twitter_mentions_5m", 0),
                )
            ),

            "hour_utc": datetime.now(timezone.utc).hour,
        }

        return FeatureVector(
            token_mint=str(
                context.get("token_mint")
                or context.get("mint")
                or context.get("address")
                or ""
            ),
            timestamp=_safe_float(
                context.get("timestamp"),
                time.time(),
            ),
            features=features,
        )

    def save_feature_vector(
        self,
        fv: FeatureVector,
    ) -> None:
        with self._lock:
            path = self._feature_path(fv.timestamp)

            with path.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        fv.to_dict(),
                        ensure_ascii=False,
                        default=_json_default,
                    )
                    + "\n"
                )

    def record_features(
        self,
        context: JsonDict,
    ) -> FeatureVector:
        fv = self.extract_features(context)

        self.save_feature_vector(fv)

        return fv

    def compute_labels_from_trade(
        self,
        trade: JsonDict,
    ) -> LabelSet:
        labels = {
            "pnl_pct": _safe_float(trade.get("pnl_pct", 0)),
            "pnl_eur": _safe_float(trade.get("pnl_eur", 0)),
            "is_win": (
                1
                if _safe_float(trade.get("pnl_pct", 0)) > 0
                else 0
            ),
            "is_big_loss": (
                1
                if _safe_float(trade.get("pnl_pct", 0)) <= -30
                else 0
            ),
            "exit_reason": trade.get("exit_reason", "unknown"),
            "duration_min": _safe_float(
                trade.get("duration_min", 0)
            ),
            "max_gain_pct": _safe_float(
                trade.get("max_gain_pct", 0)
            ),
            "min_loss_pct": _safe_float(
                trade.get("min_loss_pct", 0)
            ),
        }

        return LabelSet(
            token_mint=str(
                trade.get("mint")
                or trade.get("token_mint")
                or ""
            ),
            detection_ts=_safe_float(
                trade.get("entry_time"),
                time.time(),
            ),
            labels=labels,
        )

    def save_label_set(
        self,
        ls: LabelSet,
    ) -> None:
        with self._lock:
            path = self._label_path(ls.detection_ts)

            with path.open("a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        ls.to_dict(),
                        ensure_ascii=False,
                        default=_json_default,
                    )
                    + "\n"
                )

    def record_trade_label(
        self,
        trade: JsonDict,
    ) -> LabelSet:
        ls = self.compute_labels_from_trade(trade)

        self.save_label_set(ls)

        return ls

    def iter_jsonl(
        self,
        pattern: str,
        limit: int = 10000,
    ) -> List[JsonDict]:
        rows: List[JsonDict] = []

        for path in sorted(self.base_path.glob(pattern)):
            try:
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip():
                            continue

                        rows.append(json.loads(line))

                        if len(rows) >= limit:
                            return rows

            except Exception:
                continue

        return rows

    def load_feature_rows(
        self,
        limit: int = 10000,
    ) -> List[JsonDict]:
        return self.iter_jsonl(
            "features_*.jsonl",
            limit=limit,
        )

    def load_label_rows(
        self,
        limit: int = 10000,
    ) -> List[JsonDict]:
        return self.iter_jsonl(
            "labels_*.jsonl",
            limit=limit,
        )

    def load_training_data(
        self,
        limit: int = 10000,
    ) -> Tuple[List[List[float]], List[int], List[str]]:
        """
        Retourne :
          X, y, feature_names

        Cette méthode ne dépend pas de pandas/numpy.
        """

        features = self.load_feature_rows(limit=limit)
        labels = self.load_label_rows(limit=limit)

        label_by_mint = {
            row.get("token_mint"): row
            for row in labels
            if row.get("token_mint")
        }

        feature_names = [
            "score",
            "safety_score",
            "liquidity",
            "market_cap",
            "holders",
            "top10_pct",
            "age_minutes",
            "volume_5m",
            "volume_1h",
            "price_change_5m",
            "alpha_wallets",
            "conviction",
            "hour_utc",
        ]

        x_rows: List[List[float]] = []
        y_rows: List[int] = []

        for row in features:
            mint = row.get("token_mint")
            label = label_by_mint.get(mint)

            if not label:
                continue

            y = int(
                (label.get("labels") or {}).get("is_win", 0)
            )

            feat = row.get("features") or {}

            x_rows.append(
                [
                    _safe_float(feat.get(name), 0.0)
                    for name in feature_names
                ]
            )

            y_rows.append(y)

        return x_rows, y_rows, feature_names

    def get_status(self) -> JsonDict:
        return {
            "base_path": str(self.base_path),
            "feature_files": len(
                list(self.base_path.glob("features_*.jsonl"))
            ),
            "label_files": len(
                list(self.base_path.glob("labels_*.jsonl"))
            ),
            "features_loaded": len(
                self.load_feature_rows(limit=100000)
            ),
            "labels_loaded": len(
                self.load_label_rows(limit=100000)
            ),
        }


_feature_store: Optional[FeatureStore] = None
_lock = threading.RLock()


def get_feature_store() -> FeatureStore:
    global _feature_store

    with _lock:
        if _feature_store is None:
            _feature_store = FeatureStore()

        return _feature_store


__all__ = [
    "FEATURE_VERSION",
    "FeatureVector",
    "LabelSet",
    "FeatureStore",
    "get_feature_store",
]