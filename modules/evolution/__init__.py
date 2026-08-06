"""
MemeSniper v14.1-EVOLUTION
Exports propres du module evolution
"""

from .event_store import BotEvent, EventStore, get_event_store, log_event
from .strategy_optimizer import StrategyOptimizer, get_strategy_optimizer
from .drift_guard import DriftGuard, get_drift_guard
from .evolution_orchestrator import (
    EvolutionOrchestrator,
    get_evolution_orchestrator,
    start_evolution,
    stop_evolution,
)

try:
    from .feature_store import get_feature_store
except Exception:
    def get_feature_store():
        return None

try:
    from .auto_ml import get_auto_ml
except Exception:
    def get_auto_ml():
        return None

EVOLUTION_AVAILABLE = True

__all__ = [
    "BotEvent",
    "EventStore",
    "get_event_store",
    "log_event",
    "get_feature_store",
    "get_auto_ml",
    "StrategyOptimizer",
    "get_strategy_optimizer",
    "DriftGuard",
    "get_drift_guard",
    "EvolutionOrchestrator",
    "get_evolution_orchestrator",
    "start_evolution",
    "stop_evolution",
    "EVOLUTION_AVAILABLE",
]