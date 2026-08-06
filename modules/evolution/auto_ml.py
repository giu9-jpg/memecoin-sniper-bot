"""
MemeSniper v14.1-EVOLUTION
Auto-ML robuste Railway/local

Important :
- N'importe AUCUN LightGBM au démarrage.
- N'importe AUCUN XGBoost au démarrage.
- Si sklearn/joblib sont disponibles : entraînement simple RandomForest.
- Si les libs ML ne sont pas disponibles : fallback heuristique.
- Ne doit jamais faire crasher le bot principal.
- Alertes + paper trading uniquement, aucun trading automatique.
"""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .event_store import get_event_store, log_event


JsonDict = Dict[str, Any]


class AwaitableDict(dict):
    """
    Petit helper de compatibilité.

    Permet que le résultat fonctionne dans les deux cas :
        result = maybe_retrain()
        result = await maybe_retrain()
    """

    def __await__(self):
        async def _coro():
            return self

        return _coro().__await__()


def _result(payload: Dict[str, Any]) -> AwaitableDict:
    return AwaitableDict(payload)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default

        value = float(value)

        if math.isnan(value) or math.isinf(value):
            return default

        return value
    except Exception:
        return default


def _safe_json_load(path: Path) -> JsonDict:
    try:
        if not path.exists():
            return {}

        data = json.loads(path.read_text(encoding="utf-8"))

        if isinstance(data, dict):
            return data

        return {}
    except Exception:
        return {}


def _safe_json_save(path: Path, payload: JsonDict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception:
        pass


@dataclass
class AutoMLConfig:
    enabled: bool = field(default_factory=lambda: _env_bool("EVOLUTION_AUTOML_ENABLED", True))
    min_samples: int = field(default_factory=lambda: _env_int("EVOLUTION_AUTOML_MIN_SAMPLES", 20))
    lookback_days: int = field(default_factory=lambda: _env_int("EVOLUTION_AUTOML_LOOKBACK_DAYS", 30))
    retrain_interval_minutes: int = field(
        default_factory=lambda: _env_int("EVOLUTION_AUTOML_RETRAIN_MINUTES", 120)
    )

    model_path: Path = field(
        default_factory=lambda: Path("data") / "evolution" / "automl_model.joblib"
    )
    metrics_path: Path = field(
        default_factory=lambda: Path("data") / "evolution" / "automl_metrics.json"
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
            "age_minutes",
            "buy_ratio",
        ]
    )


class AutoML:
    def __init__(self, config: Optional[AutoMLConfig] = None) -> None:
        self.config = config or AutoMLConfig()
        self.event_store = get_event_store()
        self._lock = threading.RLock()

        self.model: Any = None
        self.model_loaded: bool = False
        self.last_metrics: JsonDict = _safe_json_load(self.config.metrics_path)

        self.config.model_path.parent.mkdir(parents=True, exist_ok=True)
        self.config.metrics_path.parent.mkdir(parents=True, exist_ok=True)

        self._load_model_safely()

    def _load_model_safely(self) -> None:
        """
        Charge le modèle si joblib existe.
        Si ça échoue, on continue en fallback heuristique.
        """
        try:
            if not self.config.model_path.exists():
                return

            import joblib  # type: ignore

            self.model = joblib.load(self.config.model_path)
            self.model_loaded = True

        except Exception as exc:
            self.model = None
            self.model_loaded = False

            self.last_metrics = {
                "status": "model_load_failed",
                "error": str(exc),
                "fallback": "heuristic",
                "updated_at": _utc_now().isoformat(),
            }

            _safe_json_save(self.config.metrics_path, self.last_metrics)

    def _extract_from_event(self, event: JsonDict, name: str) -> float:
        meta = event.get("meta") or {}

        if not isinstance(meta, dict):
            meta = {}

        if name in event:
            return _safe_float(event.get(name), 0.0)

        if name in meta:
            return _safe_float(meta.get(name), 0.0)

        aliases = {
            "safety_score": ["safety", "token_safety_score", "safetyScore"],
            "social_score": ["social", "twitter_score", "socialScore"],
            "momentum_score": ["momentum", "momentum_detector_score", "momentumScore"],
            "volume_24h": ["volume", "volume24h", "volume_usd", "volumeUsd"],
            "market_cap": ["mcap", "marketcap", "market_cap_usd", "marketCap"],
            "age_minutes": ["age", "token_age_minutes", "ageMinutes"],
            "buy_ratio": ["buyRatio", "buy_ratio_pct", "buyers_ratio"],
            "holders": ["holder_count", "holders_count"],
        }

        for alias in aliases.get(name, []):
            if alias in event:
                return _safe_float(event.get(alias), 0.0)

            if alias in meta:
                return _safe_float(meta.get(alias), 0.0)

        return 0.0

    def _vector_from_event(self, event: JsonDict) -> List[float]:
        vector: List[float] = []

        for feature in self.config.features:
            value = self._extract_from_event(event, feature)

            # Compression douce pour les grosses valeurs
            if feature in ("liquidity", "market_cap", "volume_24h", "holders"):
                value = math.log1p(max(value, 0.0))

            vector.append(float(value))

        return vector

    def _vector_from_mapping(self, payload: JsonDict) -> List[float]:
        event = {
            **payload,
            "meta": payload.get("meta", payload),
        }
        return self._vector_from_event(event)

    def _label_from_event(self, event: JsonDict) -> Optional[int]:
        meta = event.get("meta") or {}

        if not isinstance(meta, dict):
            meta = {}

        outcome = str(event.get("outcome") or meta.get("outcome") or "").lower()

        if outcome in ("win", "winner", "profit", "tp", "take_profit", "success"):
            return 1

        if outcome in ("loss", "loser", "sl", "stop_loss", "rug", "fail", "failed"):
            return 0

        pnl = _safe_float(
            event.get("pnl_pct"),
            _safe_float(meta.get("pnl_pct"), _safe_float(meta.get("paper_pnl_pct"), 0.0)),
        )

        if pnl >= 10:
            return 1

        if pnl <= -10:
            return 0

        return None

    def _collect_training_data(self) -> Tuple[List[List[float]], List[int]]:
        since = _utc_now() - timedelta(days=max(1, int(self.config.lookback_days)))

        events: List[JsonDict] = []

        try:
            if hasattr(self.event_store, "query_events"):
                events = self.event_store.query_events(
                    since=since,
                    limit=20000,
                    ascending=True,
                )
            elif hasattr(self.event_store, "query"):
                events = self.event_store.query(
                    since=since,
                    limit=20000,
                    ascending=True,
                )
        except Exception:
            events = []

        x_rows: List[List[float]] = []
        y_rows: List[int] = []

        for event in events:
            label = self._label_from_event(event)

            if label is None:
                continue

            vector = self._vector_from_event(event)

            if not vector:
                continue

            x_rows.append(vector)
            y_rows.append(label)

        return x_rows, y_rows

    def _save_metrics(self, metrics: JsonDict) -> None:
        self.last_metrics = metrics
        _safe_json_save(self.config.metrics_path, metrics)

    def train(self, force: bool = False) -> AwaitableDict:
        """
        Entraîne un petit modèle sklearn si possible.
        Si sklearn n'est pas disponible, fallback sans crash.
        """
        with self._lock:
            if not self.config.enabled:
                result = {
                    "status": "disabled",
                    "reason": "EVOLUTION_AUTOML_ENABLED=false",
                    "fallback": "heuristic",
                }
                self._save_metrics(result)
                return _result(result)

            x_rows, y_rows = self._collect_training_data()
            samples = len(y_rows)

            if samples < self.config.min_samples and not force:
                result = {
                    "status": "skipped",
                    "reason": "not_enough_samples",
                    "samples": samples,
                    "required": self.config.min_samples,
                    "fallback": "heuristic",
                    "updated_at": _utc_now().isoformat(),
                }

                self._save_metrics(result)

                log_event(
                    "automl_training_skipped",
                    "auto_ml",
                    status="skipped",
                    samples=samples,
                    required=self.config.min_samples,
                    meta={"reason": "not_enough_samples"},
                )

                return _result(result)

            if len(set(y_rows)) < 2:
                result = {
                    "status": "skipped",
                    "reason": "only_one_class",
                    "samples": samples,
                    "classes": list(sorted(set(y_rows))),
                    "fallback": "heuristic",
                    "updated_at": _utc_now().isoformat(),
                }

                self._save_metrics(result)

                log_event(
                    "automl_training_skipped",
                    "auto_ml",
                    status="skipped",
                    samples=samples,
                    meta={"reason": "only_one_class"},
                )

                return _result(result)

            try:
                # Import lazy : pas au démarrage du bot.
                from sklearn.ensemble import RandomForestClassifier  # type: ignore
                from sklearn.metrics import accuracy_score  # type: ignore
                from sklearn.model_selection import train_test_split  # type: ignore
                import joblib  # type: ignore

                test_size = 0.25 if samples >= 12 else 0.33

                try:
                    x_train, x_test, y_train, y_test = train_test_split(
                        x_rows,
                        y_rows,
                        test_size=test_size,
                        random_state=42,
                        stratify=y_rows if min(y_rows.count(0), y_rows.count(1)) >= 2 else None,
                    )
                except Exception:
                    x_train, x_test, y_train, y_test = train_test_split(
                        x_rows,
                        y_rows,
                        test_size=test_size,
                        random_state=42,
                    )

                model = RandomForestClassifier(
                    n_estimators=120,
                    max_depth=5,
                    min_samples_leaf=2,
                    random_state=42,
                    class_weight="balanced",
                )

                model.fit(x_train, y_train)

                predictions = model.predict(x_test)
                accuracy = float(accuracy_score(y_test, predictions)) if y_test else 0.0

                package = {
                    "model": model,
                    "features": self.config.features,
                    "trained_at": _utc_now().isoformat(),
                    "samples": samples,
                }

                joblib.dump(package, self.config.model_path)

                self.model = package
                self.model_loaded = True

                result = {
                    "status": "trained",
                    "model": "RandomForestClassifier",
                    "samples": samples,
                    "accuracy": accuracy,
                    "features": self.config.features,
                    "model_path": str(self.config.model_path),
                    "updated_at": _utc_now().isoformat(),
                    "fallback": False,
                }

                self._save_metrics(result)

                log_event(
                    "automl_trained",
                    "auto_ml",
                    status="trained",
                    samples=samples,
                    confidence=accuracy,
                    meta=result,
                )

                return _result(result)

            except Exception as exc:
                # Aucun crash du bot si sklearn/joblib échoue.
                self.model = None
                self.model_loaded = False

                result = {
                    "status": "skipped",
                    "reason": "training_failed",
                    "error": str(exc),
                    "samples": samples,
                    "fallback": "heuristic",
                    "updated_at": _utc_now().isoformat(),
                }

                self._save_metrics(result)

                log_event(
                    "automl_training_failed",
                    "auto_ml",
                    status="error",
                    samples=samples,
                    meta={"error": str(exc)},
                )

                return _result(result)

    def retrain(self, force: bool = False) -> AwaitableDict:
        return self.train(force=force)

    def run_once(self, force: bool = False) -> AwaitableDict:
        return self.maybe_retrain(force=force)

    def maybe_retrain(self, force: bool = False) -> AwaitableDict:
        if force:
            return self.train(force=True)

        last_trained_at = self.last_metrics.get("updated_at") or self.last_metrics.get("trained_at")

        if last_trained_at:
            try:
                last_dt = datetime.fromisoformat(str(last_trained_at).replace("Z", "+00:00"))

                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)

                elapsed = _utc_now() - last_dt

                if elapsed < timedelta(minutes=max(1, int(self.config.retrain_interval_minutes))):
                    return _result(
                        {
                            "status": "skipped",
                            "reason": "too_early",
                            "last_trained_at": last_dt.isoformat(),
                            "next_retrain_after_minutes": self.config.retrain_interval_minutes,
                            "fallback": not self.model_loaded,
                        }
                    )
            except Exception:
                pass

        return self.train(force=False)

    def _heuristic_predict(self, payload: JsonDict) -> JsonDict:
        score = _safe_float(payload.get("score"), 0.0)

        meta = payload.get("meta") or {}

        if not isinstance(meta, dict):
            meta = {}

        safety = _safe_float(
            payload.get("safety_score"),
            _safe_float(meta.get("safety_score"), _safe_float(meta.get("safety"), score)),
        )

        social = _safe_float(
            payload.get("social_score"),
            _safe_float(meta.get("social_score"), _safe_float(meta.get("social"), 5.0)),
        )

        momentum = _safe_float(
            payload.get("momentum_score"),
            _safe_float(meta.get("momentum_score"), _safe_float(meta.get("momentum"), 5.0)),
        )

        confidence = (
            0.45 * max(min(score / 10.0, 1.0), 0.0)
            + 0.30 * max(min(safety / 10.0, 1.0), 0.0)
            + 0.15 * max(min(social / 10.0, 1.0), 0.0)
            + 0.10 * max(min(momentum / 10.0, 1.0), 0.0)
        )

        return {
            "status": "heuristic",
            "proba_win": float(confidence),
            "confidence": float(confidence),
            "model_loaded": False,
            "fallback": True,
        }

    def predict(self, payload: Optional[JsonDict] = None, **kwargs: Any) -> JsonDict:
        payload = payload or {}
        payload.update(kwargs)

        if not self.model_loaded or not self.model:
            return self._heuristic_predict(payload)

        try:
            package = self.model

            if isinstance(package, dict) and "model" in package:
                model = package["model"]
            else:
                model = package

            vector = self._vector_from_mapping(payload)

            proba_win = 0.5

            if hasattr(model, "predict_proba"):
                probabilities = model.predict_proba([vector])[0]

                if len(probabilities) >= 2:
                    proba_win = float(probabilities[1])
                else:
                    proba_win = float(probabilities[0])
            elif hasattr(model, "predict"):
                pred = model.predict([vector])[0]
                proba_win = float(pred)

            return {
                "status": "ok",
                "proba_win": proba_win,
                "confidence": proba_win,
                "model_loaded": True,
                "fallback": False,
            }

        except Exception as exc:
            result = self._heuristic_predict(payload)
            result["status"] = "fallback_after_predict_error"
            result["error"] = str(exc)
            return result

    def predict_proba(self, payload: Optional[JsonDict] = None, **kwargs: Any) -> float:
        result = self.predict(payload, **kwargs)
        return float(result.get("proba_win", result.get("confidence", 0.5)))

    def score_token(self, payload: Optional[JsonDict] = None, **kwargs: Any) -> JsonDict:
        return self.predict(payload, **kwargs)

    def predict_token(self, payload: Optional[JsonDict] = None, **kwargs: Any) -> JsonDict:
        return self.predict(payload, **kwargs)

    def get_status(self) -> JsonDict:
        return {
            "enabled": self.config.enabled,
            "model_loaded": self.model_loaded,
            "model_path": str(self.config.model_path),
            "metrics_path": str(self.config.metrics_path),
            "last_metrics": self.last_metrics,
            "fallback_available": True,
            "paper_trading_only": True,
            "auto_trading": False,
        }


_AUTO_ML: Optional[AutoML] = None
_LOCK = threading.RLock()


def get_auto_ml() -> AutoML:
    global _AUTO_ML

    with _LOCK:
        if _AUTO_ML is None:
            _AUTO_ML = AutoML()

        return _AUTO_ML


def maybe_retrain(*args: Any, **kwargs: Any) -> AwaitableDict:
    """
    Fonction globale importée par main.py.

    Compatible :
        maybe_retrain()
        await maybe_retrain()
    """
    try:
        force = bool(kwargs.pop("force", False))
        return get_auto_ml().maybe_retrain(force=force)
    except Exception as exc:
        return _result(
            {
                "status": "error",
                "reason": "maybe_retrain_failed",
                "error": str(exc),
                "fallback": "heuristic",
            }
        )


def train_auto_ml(*args: Any, **kwargs: Any) -> AwaitableDict:
    try:
        force = bool(kwargs.pop("force", True))
        return get_auto_ml().train(force=force)
    except Exception as exc:
        return _result(
            {
                "status": "error",
                "reason": "train_auto_ml_failed",
                "error": str(exc),
                "fallback": "heuristic",
            }
        )


def predict_token(payload: Optional[JsonDict] = None, **kwargs: Any) -> JsonDict:
    try:
        return get_auto_ml().predict_token(payload, **kwargs)
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "proba_win": 0.5,
            "confidence": 0.5,
            "fallback": True,
        }


__all__ = [
    "AutoMLConfig",
    "AutoML",
    "get_auto_ml",
    "maybe_retrain",
    "train_auto_ml",
    "predict_token",
]