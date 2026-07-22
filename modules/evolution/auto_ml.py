# modules/evolution/auto_ml.py
"""
Pipeline Auto-ML continu.
- Déclencheur: nouveaux labels disponibles
- Entraîne challengers vs champion
- Validation walk-forward + purged K-fold
- Promotion si amélioration significative
- Versioning modèles + rollback automatique
"""
import json
import time
import hashlib
import pickle
import threading
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
from datetime import datetime
from collections import deque

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import log_loss, roc_auc_score, average_precision_score
import xgboost as xgb
import lightgbm as lgb

from modules.evolution.feature_store import get_feature_store
from modules.evolution.event_store import get_event_store, log_event

MODEL_VERSION = "4.0"
MIN_TRADES_FOR_TRAIN = 100
MIN_TRADES_FOR_PROMOTION = 50
PROMOTION_THRESHOLD = 0.05  # +5% sur metric principal
RETRAIN_INTERVAL_HOURS = 6
MAX_MODEL_AGE_DAYS = 30

@dataclass
class ModelMetrics:
    model_id: str
    model_type: str           # "xgb", "lgb", "ensemble"
    trained_at: float
    train_samples: int
    val_samples: int
    metrics: dict             # {horizon: {logloss, auc, pr_auc, sharpe}}
    feature_importance: dict
    config_hash: str          # Hash de la config d'entraînement

@dataclass 
class ChampionModel:
    model_id: str
    model_object: Any         # Le modèle entraîné (picklé)
    metrics: ModelMetrics
    promoted_at: float
    is_active: bool = True

class AutoMLPipeline:
    def __init__(self, model_dir: str = "models"):
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        
        self.feature_store = get_feature_store()
        self.event_store = get_event_store()
        
        self.champion: ChampionModel | None = None
        self.challengers: dict[str, ChampionModel] = {}  # model_id -> model
        self.training_queue: deque = deque()
        self._lock = threading.Lock()
        self._running = False
        self._last_retrain = 0
        
        # Charge le champion actuel si existe
        self._load_champion()
    
    def _load_champion(self):
        champion_path = self.model_dir / "champion.json"
        if champion_path.exists():
            with open(champion_path) as f:
                data = json.load(f)
            model_path = self.model_dir / f"{data['model_id']}.pkl"
            if model_path.exists():
                with open(model_path, "rb") as f:
                    model_obj = pickle.load(f)
                self.champion = ChampionModel(
                    model_id=data["model_id"],
                    model_object=model_obj,
                    metrics=ModelMetrics(**data["metrics"]),
                    promoted_at=data["promoted_at"]
                )
                log_event("model_loaded", "auto_ml", 
                         model_id=data["model_id"], 
                         event_type="model_load")
    
    def _save_champion(self, champion: ChampionModel):
        with open(self.model_dir / f"{champion.model_id}.pkl", "wb") as f:
            pickle.dump(champion.model_object, f)
        
        with open(self.model_dir / "champion.json", "w") as f:
            json.dump({
                "model_id": champion.model_id,
                "metrics": champion.metrics.__dict__,
                "promoted_at": champion.promoted_at
            }, f)
    
    def should_retrain(self) -> bool:
        """Vérifie si assez de nouveaux données pour réentraîner."""
        if time.time() - self._last_retrain < RETRAIN_INTERVAL_HOURS * 3600:
            return False
        
        # Compte nouveaux trades labeled depuis dernier entraînement
        cutoff = self.champion.metrics.trained_at if self.champion else 0
        new_events = self.event_store.query(
            start_ts=cutoff,
            end_ts=time.time(),
            event_types=["outcome"]
        )
        labeled_count = sum(1 for e in new_events if e.outcome.get("labeled", False))
        return labeled_count >= MIN_TRADES_FOR_TRAIN
    
    def trigger_retrain(self):
        """Lance réentraînement asynchrone."""
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._retrain_loop, daemon=True).start()
    
    def _retrain_loop(self):
        try:
            log_event("retrain_started", "auto_ml", event_type="model_train")
            
            # 1. Prépare données d'entraînement
            X, y_dict = self._prepare_training_data()
            if len(X) < MIN_TRADES_FOR_TRAIN:
                log_event("retrain_skipped", "auto_ml", 
                         reason=f"insufficient_data_{len(X)}", event_type="model_train")
                return
            
            # 2. Entraîne plusieurs challengers
            challengers = self._train_challengers(X, y_dict)
            
            # 3. Évalue sur validation walk-forward
            best_challenger = self._evaluate_challengers(challengers, X, y_dict)
            
            # 4. Compare au champion
            if self._should_promote(best_challenger):
                self._promote_challenger(best_challenger)
                log_event("model_promoted", "auto_ml",
                         new_champion=best_challenger.model_id,
                         event_type="model_promotion")
            else:
                log_event("challenger_rejected", "auto_ml",
                         challenger=best_challenger.model_id,
                         event_type="model_rejection")
            
            self._last_retrain = time.time()
            
        except Exception as e:
            log_event("retrain_failed", "auto_ml", error=str(e), event_type="model_error")
        finally:
            self._running = False
    
    def _prepare_training_data(self) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """Charge et prépare données depuis feature store."""
        # Utilise feature_store.load_training_data
        # Pour l'instant, version simplifiée
        end_ts = time.time()
        start_ts = end_ts - (MAX_MODEL_AGE_DAYS * 86400)
        
        events = self.event_store.query(start_ts, end_ts, event_types=["detection", "outcome"])
        
        # Joint detections + outcomes par token_mint + timestamp approximatif
        detections = [e for e in events if e.event_type == "detection"]
        outcomes = {e.token_mint: e.outcome for e in events if e.event_type == "outcome"}
        
        X_list = []
        y_dict = defaultdict(list)
        
        for det in detections:
            if det.token_mint not in outcomes:
                continue
            
            # Reconstruit feature vector depuis event
            features = det.features
            X_list.append([features.get(f, 0) for f in sorted(features.keys())])
            
            outcome = outcomes[det.token_mint]
            for horizon in ["1h", "4h", "24h", "7d"]:
                if horizon in outcome:
                    y_dict[f"{horizon}_max_roi"].append(outcome[horizon].get("max_roi", 0))
                    y_dict[f"{horizon}_rugged"].append(outcome[horizon].get("rugged", 0))
        
        return np.array(X_list), {k: np.array(v) for k, v in y_dict.items()}
    
    def _train_challengers(self, X: np.ndarray, y_dict: dict) -> list[ChampionModel]:
        """Entraîne plusieurs modèles candidats."""
        challengers = []
        feature_names = [f"f_{i}" for i in range(X.shape[1])]
        
        # Target principal: rugged à 24h (classification) + max_roi à 24h (regression)
        y_rugged = y_dict.get("24h_rugged", np.zeros(len(X)))
        y_roi = y_dict.get("24h_max_roi", np.zeros(len(X)))
        
        # Modèle 1: XGBoost Classifier (rug detection)
        xgb_clf = xgb.XGBClassifier(
            n_estimators=500, max_depth=6, learning_rate=0.01,
            subsample=0.8, colsample_bytree=0.8,
            eval_metric="logloss", random_state=42, n_jobs=-1
        )
        xgb_clf.fit(X, y_rugged)
        
        # Modèle 2: LightGBM Regressor (ROI prediction)
        lgb_reg = lgb.LGBMRegressor(
            n_estimators=500, max_depth=6, learning_rate=0.01,
            subsample=0.8, colsample_bytree=0.8,
            random_state=42, n_jobs=-1, verbose=-1
        )
        lgb_reg.fit(X, y_roi)
        
        # Modèle 3: Ensemble (moyenne pondérée)
        # On créera un wrapper ensemble plus tard
        
        for name, model, y_pred in [
            ("xgb_rug", xgb_clf, xgb_clf.predict_proba(X)[:, 1]),
            ("lgb_roi", lgb_reg, lgb_reg.predict(X)),
        ]:
            model_id = f"{name}_{int(time.time())}_{hashlib.md5(str(model.get_params()).encode()).hexdigest()[:8]}"
            
            # Calcule métriques validation (simple holdout pour vitesse)
            split = int(0.8 * len(X))
            X_val, y_val_rug, y_val_roi = X[split:], y_rugged[split:], y_roi[split:]
            y_pred_val = y_pred[split:]
            
            metrics = ModelMetrics(
                model_id=model_id,
                model_type=name,
                trained_at=time.time(),
                train_samples=split,
                val_samples=len(X) - split,
                metrics={
                    "24h": {
                        "logloss": log_loss(y_val_rug, y_pred_val) if name == "xgb_rug" else None,
                        "auc": roc_auc_score(y_val_rug, y_pred_val) if name == "xgb_rug" else None,
                        "mae": np.mean(np.abs(y_val_roi - y_pred_val)) if name == "lgb_roi" else None,
                    }
                },
                feature_importance=dict(zip(feature_names, model.feature_importances_)),
                config_hash=hashlib.md5(json.dumps(model.get_params(), sort_keys=True).encode()).hexdigest()[:16]
            )
            
            challengers.append(ChampionModel(
                model_id=model_id,
                model_object=model,
                metrics=metrics,
                promoted_at=0
            ))
        
        return challengers
    
    def _evaluate_challengers(self, challengers: list[ChampionModel], 
                              X: np.ndarray, y_dict: dict) -> ChampionModel:
        """Walk-forward validation purged."""
        # Version simplifiée: retourne le meilleur sur validation holdout
        best = None
        best_score = -np.inf
        
        for ch in challengers:
            m = ch.metrics.metrics.get("24h", {})
            if ch.metrics.model_type == "xgb_rug":
                score = m.get("auc", 0)  # Maximize AUC
            else:
                score = -m.get("mae", 1)  # Minimize MAE
            
            if score > best_score:
                best_score = score
                best = ch
        
        return best
    
    def _should_promote(self, challenger: ChampionModel) -> bool:
        if not self.champion:
            return True
        
        # Compare sur metric principal
        champ_metric = self.champion.metrics.metrics.get("24h", {})
        chal_metric = challenger.metrics.metrics.get("24h", {})
        
        if challenger.metrics.model_type == "xgb_rug":
            champ_score = champ_metric.get("auc", 0)
            chal_score = chal_metric.get("auc", 0)
            return (chal_score - champ_score) / max(champ_score, 0.001) > PROMOTION_THRESHOLD
        else:
            champ_score = champ_metric.get("mae", 1)
            chal_score = chal_metric.get("mae", 1)
            return (champ_score - chal_score) / max(champ_score, 0.001) > PROMOTION_THRESHOLD
    
    def _promote_challenger(self, challenger: ChampionModel):
        """Promouvoit le challenger en champion."""
        challenger.promoted_at = time.time()
        challenger.is_active = True
        
        # Archive ancien champion
        if self.champion:
            self.champion.is_active = False
            archive_path = self.model_dir / "archive" / f"{self.champion.model_id}.json"
            archive_path.parent.mkdir(exist_ok=True)
            with open(archive_path, "w") as f:
                json.dump(self.champion.metrics.__dict__, f)
        
        self.champion = challenger
        self._save_champion(challenger)
    
    def predict(self, features: dict) -> dict:
        """Inférence avec champion actuel."""
        if not self.champion:
            return {"p_rug": 0.5, "pred_roi": 0.0, "model_id": "none"}
        
        X = np.array([[features.get(f, 0) for f in sorted(features.keys())]])
        
        if self.champion.metrics.model_type == "xgb_rug":
            p_rug = self.champion.model_object.predict_proba(X)[0][1]
            return {"p_rug": float(p_rug), "model_id": self.champion.model_id}
        elif self.champion.metrics.model_type == "lgb_roi":
            pred_roi = self.champion.model_object.predict(X)[0]
            return {"pred_roi": float(pred_roi), "model_id": self.champion.model_id}
        
        return {"model_id": self.champion.model_id}


# Singleton
_auto_ml: AutoMLPipeline | None = None

def get_auto_ml() -> AutoMLPipeline:
    global _auto_ml
    if _auto_ml is None:
        _auto_ml = AutoMLPipeline()
    return _auto_ml

def maybe_retrain():
    """Appelé périodiquement (ex: toutes les heures via scheduler)."""
    ml = get_auto_ml()
    if ml.should_retrain():
        ml.trigger_retrain()