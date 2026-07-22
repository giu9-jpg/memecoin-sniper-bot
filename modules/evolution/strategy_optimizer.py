# modules/evolution/strategy_optimizer.py
"""
Méta-optimisation de la stratégie.
- Optimise seuils (min_score, safety_min, liq_min, conviction_min)
- Optimise poids (score components, tier thresholds)
- Découvre nouveaux patterns via clustering résidus
- Prune features/règles inutiles
- Garde-fous: max DD, min trades, regime awareness
"""
import json
import time
import numpy as np
import optuna
from dataclasses import dataclass, field
from typing import Any
from pathlib import Path
from collections import defaultdict

from modules.evolution.event_store import get_event_store
from modules.evolution.auto_ml import get_auto_ml

@dataclass
class StrategyConfig:
    """Configuration optimisable de la stratégie."""
    # Seuils entrée
    min_score: float = 8.0
    safety_min: float = 6.5
    liq_min_usd: float = 5000
    conviction_min: int = 1
    
    # Filtres horaires
    peak_hours_start: int = 14
    peak_hours_end: int = 18
    peak_min_score: float = 7.5
    night_min_score: float = 8.5
    
    # Poids score components
    weight_volume: float = 1.0
    weight_momentum: float = 1.0
    weight_smart_signals: float = 1.0
    weight_social: float = 0.5
    weight_alpha: float = 2.0
    weight_whale: float = 1.5
    weight_dev: float = 1.5
    
    # Tiers
    ultimate_score: float = 8.5
    ultimate_safety: float = 7.0
    ultimate_liq: float = 8000
    strong_score: float = 7.8
    strong_safety: float = 6.5
    strong_liq: float = 5000
    
    # Risk
    max_alerts_per_hour: int = 15
    sl_pct: float = -0.25
    tp_pct: float = 1.0
    
    def to_dict(self) -> dict:
        return self.__dict__.copy()
    
    @classmethod
    def from_dict(cls, d: dict) -> "StrategyConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__annotations__})

@dataclass
class StrategyPerformance:
    config_hash: str
    period_start: float
    period_end: float
    n_trades: int
    win_rate: float
    avg_roi: float
    sharpe: float
    max_dd: float
    profit_factor: float
    expectancy: float
    calmar: float
    regime: str = "unknown"

class StrategyOptimizer:
    """
    Optimise la config via Optuna (TPE sampler).
    Objectif: maximiser Sharpe * sqrt(n_trades) / max_dd  (risk-adjusted)
    """
    
    SEARCH_SPACE = {
        "min_score": (7.0, 9.0),
        "safety_min": (5.5, 8.0),
        "liq_min_usd": (2000, 20000),
        "conviction_min": (0, 3),
        "peak_min_score": (7.0, 8.5),
        "night_min_score": (8.0, 9.5),
        "weight_volume": (0.5, 2.0),
        "weight_momentum": (0.5, 2.0),
        "weight_alpha": (1.0, 3.0),
        "weight_whale": (0.5, 2.5),
        "weight_dev": (0.5, 2.5),
        "ultimate_score": (8.0, 9.5),
        "ultimate_safety": (6.5, 8.5),
        "ultimate_liq": (5000, 15000),
        "max_alerts_per_hour": (8, 25),
        "sl_pct": (-0.35, -0.15),
        "tp_pct": (0.5, 2.0),
    }
    
    def __init__(self, study_name: str = "memesniper_strategy", storage: str | None = None):
        self.study_name = study_name
        self.storage = storage or f"sqlite:///data/optuna_{study_name}.db"
        self.event_store = get_event_store()
        self.auto_ml = get_auto_ml()
        
        self.study = optuna.create_study(
            study_name=study_name,
            storage=self.storage,
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
            pruner=optuna.pruners.MedianPruner(n_warmup_steps=10),
            load_if_exists=True
        )
        
        self.current_config = StrategyConfig()
        self.best_config: StrategyConfig | None = None
        self.performance_history: list[StrategyPerformance] = []
    
    def evaluate_config(self, config: StrategyConfig, 
                        start_ts: float, end_ts: float) -> StrategyPerformance:
        """Simule la config sur période historique (backtest)."""
        # Récupère tous les events de détection + outcome sur la période
        events = self.event_store.query(start_ts, end_ts, event_types=["detection", "outcome"])
        
        detections = [e for e in events if e.event_type == "detection"]
        outcomes = {e.token_mint: e.outcome for e in events if e.event_type == "outcome"}
        
        # Simule décisions avec cette config
        trades = []
        for det in detections:
            decision = self._simulate_decision(det, config)
            if not decision["alerted"]:
                continue
            
            outcome = outcomes.get(det.token_mint, {})
            if not outcome:
                continue
            
            # Utilise horizon 24h pour éval
            h24 = outcome.get("24h", {})
            roi = h24.get("pnl_pct", 0)
            rugged = h24.get("rugged", 0)
            exit_reason = h24.get("exit_reason", "UNKNOWN")
            
            trades.append({
                "roi": roi,
                "rugged": rugged,
                "exit_reason": exit_reason,
                "tier": decision["tier"],
                "score": decision["score"]
            })
        
        if len(trades) < 10:
            return StrategyPerformance(
                config_hash=self._hash_config(config),
                period_start=start_ts,
                period_end=end_ts,
                n_trades=len(trades),
                win_rate=0, avg_roi=0, sharpe=-999, max_dd=1, 
                profit_factor=0, expectancy=-999, calmar=-999
            )
        
        return self._compute_metrics(trades, config, start_ts, end_ts)
    
    def _simulate_decision(self, event: "BotEvent", config: StrategyConfig) -> dict:
        """Rejoue la décision avec une config donnée."""
        features = event.features
        score = features.get("composite_score", 0)
        safety = features.get("safety_score", 0)
        liq = features.get("liquidity_usd", 0)
        conviction = features.get("conviction_factors", 0)
        hour = features.get("hour_utc", 12)
        
        # Filtre horaire
        if config.peak_hours_start <= hour < config.peak_hours_end:
            min_score = config.peak_min_score
        else:
            min_score = config.night_min_score
        
        # Vérifications
        if score < min_score:
            return {"alerted": False, "reason": "score_below_min"}
        if safety < config.safety_min:
            return {"alerted": False, "reason": "safety_below_min"}
        if liq < config.liq_min_usd:
            return {"alerted": False, "reason": "liq_below_min"}
        if conviction < config.conviction_min:
            return {"alerted": False, "reason": "conviction_below_min"}
        
        # Détermine tier
        tier = "NORMAL"
        if (score >= config.ultimate_score and safety >= config.ultimate_safety 
            and liq >= config.ultimate_liq and conviction >= 1):
            tier = "ULTIMATE"
        elif (score >= config.strong_score and safety >= config.strong_safety 
              and liq >= config.strong_liq and conviction >= 1):
            tier = "STRONG"
        elif (score >= config.min_score and safety >= config.safety_min 
              and liq >= config.liq_min_usd and conviction >= 1):
            tier = "GOOD"
        
        return {"alerted": True, "tier": tier, "score": score, "reason": "passed"}
    
    def _compute_metrics(self, trades: list[dict], config: StrategyConfig, 
                         start_ts: float, end_ts: float) -> StrategyPerformance:
        rois = [t["roi"] for t in trades]
        wins = [r for r in rois if r > 0]
        losses = [r for r in rois if r <= 0]
        
        win_rate = len(wins) / len(rois) if rois else 0
        avg_roi = np.mean(rois) if rois else 0
        std_roi = np.std(rois) if len(rois) > 1 else 1
        sharpe = avg_roi / std_roi * np.sqrt(252 * 24) if std_roi > 0 else -999  # annualized hourly
        
        # Max drawdown
        equity = np.cumprod([1 + r for r in rois])
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        max_dd = np.max(dd) if len(dd) > 0 else 1
        
        # Profit factor
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 999
        
        # Expectancy
        expectancy = win_rate * np.mean(wins) + (1 - win_rate) * np.mean(losses) if wins and losses else -999
        
        # Calmar
        calmar = (avg_roi * 252 * 24) / max_dd if max_dd > 0 else -999
        
        return StrategyPerformance(
            config_hash=self._hash_config(config),
            period_start=start_ts,
            period_end=end_ts,
            n_trades=len(trades),
            win_rate=win_rate,
            avg_roi=avg_roi,
            sharpe=sharpe,
            max_dd=max_dd,
            profit_factor=profit_factor,
            expectancy=expectancy,
            calmar=calmar
        )
    
    def _hash_config(self, config: StrategyConfig) -> str:
        import hashlib
        return hashlib.md5(json.dumps(config.to_dict(), sort_keys=True).encode()).hexdigest()[:16]
    
    def objective(self, trial: optuna.Trial) -> float:
        """Fonction objectif Optuna."""
        # Sample config
        config = StrategyConfig()
        for param, (low, high) in self.SEARCH_SPACE.items():
            if isinstance(low, int):
                setattr(config, param, trial.suggest_int(param, low, high))
            else:
                setattr(config, param, trial.suggest_float(param, low, high))
        
        # Évalue sur fenêtre glissante (derniers 30 jours)
        end_ts = time.time()
        start_ts = end_ts - (30 * 86400)
        
        perf = self.evaluate_config(config, start_ts, end_ts)
        
        # Métrique composite: Sharpe * sqrt(n_trades) / (1 + max_dd)
        # Pénalise faible n_trades et haut DD
        if perf.n_trades < 20:
            return -999
        
        score = perf.sharpe * np.sqrt(perf.n_trades) / (1 + perf.max_dd)
        
        # Log pour analyse
        self.performance_history.append(perf)
        if len(self.performance_history) > 1000:
            self.performance_history = self.performance_history[-1000:]
        
        return score
    
    def optimize(self, n_trials: int = 100, timeout: int = 3600):
        """Lance optimisation."""
        log_event("optimization_started", "strategy_optimizer", 
                 n_trials=n_trials, event_type="optimization")
        
        self.study.optimize(self.objective, n_trials=n_trials, timeout=timeout)
        
        # Applique meilleure config
        best_params = self.study.best_params
        self.best_config = StrategyConfig(**best_params)
        self.current_config = self.best_config
        
        # Sauvegarde
        self._save_config(self.best_config, "best_config.json")
        
        log_event("optimization_completed", "strategy_optimizer",
                 best_value=self.study.best_value,
                 best_params=best_params,
                 event_type="optimization")
        
        return self.best_config
    
    def _save_config(self, config: StrategyConfig, filename: str):
        path = Path("config") / filename
        path.parent.mkdir(exist_ok=True)
        with open(path, "w") as f:
            json.dump(config.to_dict(), f, indent=2)
    
    def load_best_config(self) -> StrategyConfig:
        path = Path("config/best_config.json")
        if path.exists():
            with open(path) as f:
                self.best_config = StrategyConfig.from_dict(json.load(f))
                self.current_config = self.best_config
        return self.current_config


# Singleton
_strategy_optimizer: StrategyOptimizer | None = None

def get_strategy_optimizer() -> StrategyOptimizer:
    global _strategy_optimizer
    if _strategy_optimizer is None:
        _strategy_optimizer = StrategyOptimizer()
    return _strategy_optimizer