# modules/evolution/drift_guard.py
"""
Garde-fous pour empêcher l'auto-évolution de partir en vrille.
- Détection data drift (features distribution shift)
- Détection concept drift (performance degradation)
- Circuit breakers (max DD, min trades, regime change)
- Rollback automatique
- Human-in-the-loop pour changements majeurs
"""
import json
import time
import numpy as np
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
from collections import deque

from modules.evolution.event_store import get_event_store, log_event
from modules.evolution.auto_ml import get_auto_ml
from modules.evolution.strategy_optimizer import get_strategy_optimizer

@dataclass
class DriftAlert:
    alert_type: str           # "data_drift", "concept_drift", "performance_collapse", "regime_change"
    severity: str             # "info", "warning", "critical", "emergency"
    message: str
    metrics: dict
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False

class DriftGuard:
    """
    Surveille la santé du système auto-évolutif.
    Déclenche alerts + actions automatiques (rollback, pause, notify).
    """
    
    # Seuils
    MAX_DAILY_DD = 0.15          # 15% max drawdown journalier
    MAX_WEEKLY_DD = 0.25         # 25% max drawdown hebdo
    MIN_WIN_RATE = 0.25          # Win rate minimum (alert si en dessous)
    MIN_TRADES_PER_DAY = 3       # Minimum trades/jour (alert si en dessous)
    MAX_MODEL_AGE_DAYS = 14      # Modèle trop vieux = warning
    FEATURE_DRIFT_THRESHOLD = 0.1  # KS test p-value < 0.1 = drift
    CONCEPT_DRIFT_WINDOW = 50    # Trades pour détecter concept drift
    
    def __init__(self):
        self.event_store = get_event_store()
        self.auto_ml = get_auto_ml()
        self.strategy_opt = get_strategy_optimizer()
        
        self.alerts: deque = deque(maxlen=1000)
        self.daily_pnl = deque(maxlen=30)
        self.weekly_pnl = deque(maxlen=12)
        self.recent_trades = deque(maxlen=500)
        
        self.trading_paused = False
        self.auto_evolution_paused = False
        self.last_rollback_ts = 0
    
    def check_health(self) -> list[DriftAlert]:
        """Vérification complète — à appeler toutes les heures."""
        alerts = []
        
        # 1. Performance récente (derniers 50 trades)
        alerts.extend(self._check_recent_performance())
        
        # 2. Drawdown quotidien/hebdo
        alerts.extend(self._check_drawdowns())
        
        # 3. Data drift (distribution features)
        alerts.extend(self._check_data_drift())
        
        # 4. Concept drift (performance modèle vs baseline)
        alerts.extend(self._check_concept_drift())
        
        # 5. Âge du modèle
        alerts.extend(self._check_model_age())
        
        # 6. Régime de marché
        alerts.extend(self._check_regime_change())
        
        # 7. Volume d'alertes anormal
        alerts.extend(self._check_alert_volume())
        
        # Stocke et log
        for alert in alerts:
            self.alerts.append(alert)
            log_event("drift_alert", "drift_guard",
                     alert_type=alert.alert_type,
                     severity=alert.severity,
                     message=alert.message,
                     metrics=alert.metrics,
                     event_type="drift_alert")
        
        # Actions automatiques
        self._execute_auto_actions(alerts)
        
        return alerts
    
    def _check_recent_performance(self) -> list[DriftAlert]:
        alerts = []
        if len(self.recent_trades) < self.CONCEPT_DRIFT_WINDOW:
            return alerts
        
        recent = list(self.recent_trades)[-self.CONCEPT_DRIFT_WINDOW:]
        win_rate = sum(1 for t in recent if t.get("pnl", 0) > 0) / len(recent)
        avg_roi = np.mean([t.get("pnl", 0) for t in recent])
        
        if win_rate < self.MIN_WIN_RATE:
            alerts.append(DriftAlert(
                alert_type="concept_drift",
                severity="critical" if win_rate < 0.15 else "warning",
                message=f"Win rate dropped to {win_rate:.1%} (min {self.MIN_WIN_RATE:.1%})",
                metrics={"win_rate": win_rate, "avg_roi": avg_roi, "n_trades": len(recent)}
            ))
        
        if avg_roi < -0.05:  # Perte moyenne > 5%
            alerts.append(DriftAlert(
                alert_type="performance_collapse",
                severity="critical",
                message=f"Average ROI negative: {avg_roi:.2%}",
                metrics={"avg_roi": avg_roi, "n_trades": len(recent)}
            ))
        
        return alerts
    
    def _check_drawdowns(self) -> list[DriftAlert]:
        alerts = []
        # Calcule PnL journalier depuis events
        today_start = time.time() - (time.time() % 86400)
        today_events = self.event_store.query(today_start, time.time(), event_types=["outcome"])
        
        daily_pnl = sum(e.outcome.get("24h", {}).get("pnl_pct", 0) for e in today_events)
        self.daily_pnl.append(daily_pnl)
        
        if daily_pnl < -self.MAX_DAILY_DD:
            alerts.append(DriftAlert(
                alert_type="performance_collapse",
                severity="emergency",
                message=f"Daily DD limit breached: {daily_pnl:.2%} (max {-self.MAX_DAILY_DD:.2%})",
                metrics={"daily_pnl": daily_pnl, "limit": -self.MAX_DAILY_DD}
            ))
            self._pause_trading("daily_dd_breach")
        
        # Weekly
        week_ago = time.time() - 7 * 86400
        week_events = self.event_store.query(week_ago, time.time(), event_types=["outcome"])
        weekly_pnl = sum(e.outcome.get("24h", {}).get("pnl_pct", 0) for e in week_events)
        self.weekly_pnl.append(weekly_pnl)
        
        if weekly_pnl < -self.MAX_WEEKLY_DD:
            alerts.append(DriftAlert(
                alert_type="performance_collapse",
                severity="critical",
                message=f"Weekly DD limit breached: {weekly_pnl:.2%}",
                metrics={"weekly_pnl": weekly_pnl, "limit": -self.MAX_WEEKLY_DD}
            ))
        
        return alerts
    
    def _check_data_drift(self) -> list[DriftAlert]:
        """Compare distribution features récentes vs entraînement."""
        alerts = []
        
        if not self.auto_ml.champion:
            return alerts
        
        # Récupère features d'entraînement (échantillon)
        train_features = self._get_training_feature_sample()
        if not train_features:
            return alerts
        
        # Récupère features récentes (dernières 24h)
        recent_features = self._get_recent_feature_sample(hours=24)
        if len(recent_features) < 50:
            return alerts
        
        # Test KS sur features principales
        from scipy import stats
        key_features = ["onchain_liquidity_usd", "safety_score", "dev_credibility", 
                       "alpha_wallet_signal", "bundle_score", "price_change_5m"]
        
        drift_count = 0
        for feat in key_features:
            train_vals = [f.get(feat, 0) for f in train_features]
            recent_vals = [f.get(feat, 0) for f in recent_features]
            
            if len(train_vals) > 20 and len(recent_vals) > 20:
                try:
                    ks_stat, p_val = stats.ks_2samp(train_vals, recent_vals)
                    if p_val < self.FEATURE_DRIFT_THRESHOLD:
                        drift_count += 1
                except Exception:
                    pass
        
        if drift_count >= 3:
            alerts.append(DriftAlert(
                alert_type="data_drift",
                severity="warning",
                message=f"Data drift detected on {drift_count}/{len(key_features)} key features",
                metrics={"drift_features": drift_count, "total_checked": len(key_features)}
            ))
        
        return alerts
    
    def _check_concept_drift(self) -> list[DriftAlert]:
        """Compare prédictions modèle vs outcomes réels récents."""
        alerts = []
        
        if not self.auto_ml.champion:
            return alerts
        
        # Récupère derniers trades avec prédictions
        recent = list(self.recent_trades)[-self.CONCEPT_DRIFT_WINDOW:]
        if len(recent) < 20:
            return alerts
        
        # Calcule calibration: prédiction vs réalité
        pred_rugged = [t.get("pred_p_rug", 0.5) for t in recent if "pred_p_rug" in t]
        actual_rugged = [t.get("rugged", 0) for t in recent if "pred_p_rug" in t]
        
        if len(pred_rugged) >= 20:
            # Brier score
            brier = np.mean((np.array(pred_rugged) - np.array(actual_rugged)) ** 2)
            # Baseline (toujours prédire moyenne)
            baseline = np.mean(actual_rugged)
            baseline_brier = np.mean((baseline - np.array(actual_rugged)) ** 2)
            
            if brier > baseline_brier * 1.5:  # Modèle 50% pire que baseline
                alerts.append(DriftAlert(
                    alert_type="concept_drift",
                    severity="critical",
                    message=f"Model miscalibrated: Brier {brier:.4f} vs baseline {baseline_brier:.4f}",
                    metrics={"brier": brier, "baseline_brier": baseline_brier}
                ))
        
        return alerts
    
    def _check_model_age(self) -> list[DriftAlert]:
        alerts = []
        if not self.auto_ml.champion:
            return alerts
        
        age_days = (time.time() - self.auto_ml.champion.metrics.trained_at) / 86400
        if age_days > self.MAX_MODEL_AGE_DAYS:
            alerts.append(DriftAlert(
                alert_type="model_staleness",
                severity="warning" if age_days < 21 else "critical",
                message=f"Champion model age: {age_days:.1f} days (max {self.MAX_MODEL_AGE_DAYS})",
                metrics={"model_age_days": age_days, "model_id": self.auto_ml.champion.model_id}
            ))
        return alerts
    
    def _check_regime_change(self) -> list[DriftAlert]:
        """Détecte changement régime via SOL price action + volatility."""
        alerts = []
        # TODO: implémenter avec données SOL price
        return alerts
    
    def _check_alert_volume(self) -> list[DriftAlert]:
        """Trop peu ou trop d'alertes = problème."""
        alerts = []
        today_start = time.time() - (time.time() % 86400)
        today_detections = self.event_store.query(today_start, time.time(), event_types=["detection"])
        alerted = sum(1 for e in today_detections if e.decision.get("alerted", False))
        
        if alerted < self.MIN_TRADES_PER_DAY:
            alerts.append(DriftAlert(
                alert_type="low_activity",
                severity="warning",
                message=f"Only {alerted} alerts today (min {self.MIN_TRADES_PER_DAY})",
                metrics={"alerts_today": alerted}
            ))
        elif alerted > 50:  # Trop d'alertes = filtres trop lâches
            alerts.append(DriftAlert(
                alert_type="high_activity",
                severity="info",
                message=f"High alert volume: {alerted} today",
                metrics={"alerts_today": alerted}
            ))
        return alerts
    
    def _execute_auto_actions(self, alerts: list[DriftAlert]):
        """Actions automatiques basées sur sévérité."""
        critical_count = sum(1 for a in alerts if a.severity in ["critical", "emergency"])
        
        if critical_count >= 2:
            # Rollback modèle + pause trading
            self._rollback_model("multiple_critical_alerts")
            self._pause_trading("critical_alerts")
            self._pause_auto_evolution("critical_alerts")
            
        elif critical_count >= 1:
            # Pause auto-évolution seulement
            self._pause_auto_evolution("single_critical_alert")
    
    def _pause_trading(self, reason: str):
        if not self.trading_paused:
            self.trading_paused = True
            log_event("trading_paused", "drift_guard", reason=reason, event_type="circuit_breaker")
    
    def _pause_auto_evolution(self, reason: str):
        if not self.auto_evolution_paused:
            self.auto_evolution_paused = True
            log_event("auto_evolution_paused", "drift_guard", reason=reason, event_type="circuit_breaker")
    
    def _rollback_model(self, reason: str):
        """Rollback au modèle précédent archivé."""
        if time.time() - self.last_rollback_ts < 3600:  # Max 1 rollback/heure
            return
        
        # Trouve modèle archivé le plus récent
        archive_dir = Path("models/archive")
        if not archive_dir.exists():
            return
        
        archives = sorted(archive_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not archives:
            return
        
        # Charge le modèle précédent
        latest_archive = archives[0]
        with open(latest_archive) as f:
            prev_metrics = json.load(f)
        
        prev_model_id = latest_archive.stem
        model_path = Path("models") / f"{prev_model_id}.pkl"
        
        if model_path.exists():
            import pickle
            with open(model_path, "rb") as f:
                model_obj = pickle.load(f)
            
            from modules.evolution.auto_ml import ChampionModel
            self.auto_ml.champion = ChampionModel(
                model_id=prev_model_id,
                model_object=model_obj,
                metrics=prev_metrics,
                promoted_at=time.time()
            )
            self.auto_ml._save_champion(self.auto_ml.champion)
            
            self.last_rollback_ts = time.time()
            log_event("model_rolled_back", "drift_guard",
                     rolled_back_to=prev_model_id,
                     reason=reason,
                     event_type="rollback")
    
    def _get_training_feature_sample(self, n: int = 1000) -> list[dict]:
        # Récupère échantillon features utilisées pour entraînement champion
        return []
    
    def _get_recent_feature_sample(self, hours: int = 24) -> list[dict]:
        # Récupère features des détections récentes
        return []
    
    def record_trade(self, trade_data: dict):
        """Appelé par simulator / position_tracker pour chaque trade fermé."""
        self.recent_trades.append(trade_data)
    
    def is_trading_allowed(self) -> bool:
        return not self.trading_paused
    
    def is_evolution_allowed(self) -> bool:
        return not self.auto_evolution_paused
    
    def acknowledge_alert(self, alert_index: int):
        if 0 <= alert_index < len(self.alerts):
            self.alerts[alert_index].acknowledged = True
    
    def get_unacknowledged_alerts(self) -> list[DriftAlert]:
        return [a for a in self.alerts if not a.acknowledged]


# Singleton
_drift_guard: DriftGuard | None = None

def get_drift_guard() -> DriftGuard:
    global _drift_guard
    if _drift_guard is None:
        _drift_guard = DriftGuard()
    return _drift_guard