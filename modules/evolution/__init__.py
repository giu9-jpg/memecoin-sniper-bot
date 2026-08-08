"""
MemeSniper v14.1-EVOLUTION
Exports propres du module evolution
"""

from .event_store import (
    BotEvent,
    EventStore,
    get_event_store,
    log_event,
)

from .feature_store import (
    FeatureStore,
    get_feature_store,
)

from .strategy_optimizer import (
    StrategyOptimizer,
    get_strategy_optimizer,
)

from .drift_guard import (
    DriftGuard,
    get_drift_guard,
)

from .performance_analyzer import (
    PerformanceAnalyzer,
    get_performance_analyzer,
)

from .evolution_orchestrator import (
    EvolutionOrchestrator,
    get_evolution_orchestrator,
    start_evolution,
    stop_evolution,
)

try:
    from .auto_ml import (
        AutoML,
        get_auto_ml,
        maybe_retrain,
    )

except Exception:
    AutoML = None  # type: ignore

    def get_auto_ml():
        return None

    def maybe_retrain(*args, **kwargs):
        return {
            "status": "unavailable",
            "fallback": "heuristic",
        }


EVOLUTION_AVAILABLE = True


__all__ = [
    "BotEvent",
    "EventStore",
    "get_event_store",
    "log_event",

    "FeatureStore",
    "get_feature_store",

    "AutoML",
    "get_auto_ml",
    "maybe_retrain",

    "StrategyOptimizer",
    "get_strategy_optimizer",

    "DriftGuard",
    "get_drift_guard",

    "PerformanceAnalyzer",
    "get_performance_analyzer",

    "EvolutionOrchestrator",
    "get_evolution_orchestrator",
    "start_evolution",
    "stop_evolution",

    "EVOLUTION_AVAILABLE",
]