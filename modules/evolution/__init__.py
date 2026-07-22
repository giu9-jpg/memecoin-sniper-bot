# modules/evolution/__init__.py
"""
Evolution Package — Auto-improving trading bot infrastructure.
"""
from .event_store import get_event_store, log_event, BotEvent, EventStore
from .feature_store import get_feature_store, FeatureStore, FeatureVector, LabelSet
from .auto_ml import get_auto_ml, AutoMLPipeline, ChampionModel, ModelMetrics
from .strategy_optimizer import get_strategy_optimizer, StrategyOptimizer, StrategyConfig, StrategyPerformance
from .drift_guard import get_drift_guard, DriftGuard, DriftAlert
from .evolution_orchestrator import get_orchestrator, EvolutionOrchestrator, start_evolution, stop_evolution

__all__ = [
    "get_event_store", "log_event", "BotEvent", "EventStore",
    "get_feature_store", "FeatureStore", "FeatureVector", "LabelSet",
    "get_auto_ml", "AutoMLPipeline", "ChampionModel", "ModelMetrics",
    "get_strategy_optimizer", "StrategyOptimizer", "StrategyConfig", "StrategyPerformance",
    "get_drift_guard", "DriftGuard", "DriftAlert",
    "get_orchestrator", "EvolutionOrchestrator", "start_evolution", "stop_evolution",
]