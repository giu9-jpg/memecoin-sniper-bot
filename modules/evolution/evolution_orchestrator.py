"""
MemeSniper v14.1-EVOLUTION
Evolution Orchestrator

Objectif :
- Lancer les boucles Event Store / Optimizer / Drift Guard / Auto-ML
- Ne jamais casser le bot principal
- Alertes + paper trading uniquement
- Aucun trading automatique
"""

from __future__ import annotations

import asyncio
import inspect
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .event_store import get_event_store, log_event
from .strategy_optimizer import get_strategy_optimizer
from .drift_guard import get_drift_guard


JsonDict = Dict[str, Any]


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class EvolutionOrchestratorConfig:
    enabled: bool = _env_bool("EVOLUTION_ENABLED", True)

    maintenance_interval: int = _env_int("EVOLUTION_MAINTENANCE_INTERVAL", 300)
    strategy_interval: int = _env_int("EVOLUTION_STRATEGY_INTERVAL", 1800)
    drift_interval: int = _env_int("EVOLUTION_DRIFT_INTERVAL", 900)
    report_interval: int = _env_int("EVOLUTION_REPORT_INTERVAL", 3600)
    automl_interval: int = _env_int("EVOLUTION_AUTOML_INTERVAL", 7200)

    run_strategy_optimizer: bool = _env_bool("EVOLUTION_STRATEGY_ENABLED", True)
    run_drift_guard: bool = _env_bool("EVOLUTION_DRIFT_ENABLED", True)
    run_automl: bool = _env_bool("EVOLUTION_AUTOML_ENABLED", True)


class EvolutionOrchestrator:
    def __init__(self, config: Optional[EvolutionOrchestratorConfig] = None) -> None:
        self.config = config or EvolutionOrchestratorConfig()

        self.event_store = get_event_store()
        self.strategy_optimizer = get_strategy_optimizer()
        self.drift_guard = get_drift_guard()

        self._tasks: List[asyncio.Task[Any]] = []
        self._running = False
        self._lock = threading.RLock()

    @property
    def is_running(self) -> bool:
        return self._running

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def start(self) -> "EvolutionOrchestrator":
        with self._lock:
            if self._running:
                return self

            if not self.config.enabled:
                log_event(
                    "orchestrator_disabled",
                    "evolution_orchestrator",
                    status="disabled",
                    meta={"reason": "EVOLUTION_ENABLED=false"},
                )
                return self

            self._running = True

        log_event(
            "orchestrator_started",
            "evolution_orchestrator",
            status="started",
            meta={
                "maintenance_interval": self.config.maintenance_interval,
                "strategy_interval": self.config.strategy_interval,
                "drift_interval": self.config.drift_interval,
                "report_interval": self.config.report_interval,
                "automl_interval": self.config.automl_interval,
                "paper_trading_only": True,
                "auto_trading": False,
            },
        )

        self._tasks = [
            asyncio.create_task(
                self._loop(
                    name="maintenance",
                    interval=self.config.maintenance_interval,
                    callback=self.maintenance_once,
                    run_immediately=True,
                )
            ),
            asyncio.create_task(
                self._loop(
                    name="report",
                    interval=self.config.report_interval,
                    callback=self.report_once,
                    run_immediately=False,
                )
            ),
        ]

        if self.config.run_strategy_optimizer:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        name="strategy_optimizer",
                        interval=self.config.strategy_interval,
                        callback=self.strategy_once,
                        run_immediately=False,
                    )
                )
            )

        if self.config.run_drift_guard:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        name="drift_guard",
                        interval=self.config.drift_interval,
                        callback=self.drift_once,
                        run_immediately=False,
                    )
                )
            )

        if self.config.run_automl:
            self._tasks.append(
                asyncio.create_task(
                    self._loop(
                        name="automl",
                        interval=self.config.automl_interval,
                        callback=self.automl_once,
                        run_immediately=False,
                    )
                )
            )

        return self

    async def stop(self) -> None:
        with self._lock:
            self._running = False

        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        self._tasks = []

        log_event(
            "orchestrator_stopped",
            "evolution_orchestrator",
            status="stopped",
        )

    async def _loop(
        self,
        name: str,
        interval: int,
        callback: Any,
        run_immediately: bool = False,
    ) -> None:
        safe_interval = max(15, int(interval or 60))

        log_event(
            "orchestrator_loop_started",
            "evolution_orchestrator",
            status="loop_started",
            meta={"loop": name, "interval": safe_interval},
        )

        if not run_immediately:
            await asyncio.sleep(min(safe_interval, 10))

        while self._running:
            try:
                await self._maybe_await(callback())
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_event(
                    "orchestrator_loop_error",
                    "evolution_orchestrator",
                    status="error",
                    meta={
                        "loop": name,
                        "error": str(exc),
                    },
                )

            await asyncio.sleep(safe_interval)

    async def maintenance_once(self) -> JsonDict:
        stats = self.event_store.aggregate_daily_stats(days=1)

        result = {
            "status": "ok",
            "timestamp": _utc_now().isoformat(),
            "stats": stats,
        }

        log_event(
            "maintenance_tick",
            "evolution_orchestrator",
            status="ok",
            meta=result,
        )

        return result

    async def strategy_once(self) -> JsonDict:
        try:
            result = self.strategy_optimizer.optimize(force=False)

            log_event(
                "strategy_loop_ok",
                "evolution_orchestrator",
                status="ok",
                meta={"result": result},
            )

            return {
                "status": "ok",
                "result": result,
            }

        except Exception as exc:
            log_event(
                "strategy_loop_error",
                "evolution_orchestrator",
                status="error",
                meta={"error": str(exc)},
            )
            return {
                "status": "error",
                "error": str(exc),
            }

    async def drift_once(self) -> JsonDict:
        try:
            result = self.drift_guard.check_drift(update_baseline=True)

            log_event(
                "drift_loop_ok",
                "evolution_orchestrator",
                status="ok",
                meta={"result": result},
            )

            return {
                "status": "ok",
                "result": result,
            }

        except Exception as exc:
            log_event(
                "drift_loop_error",
                "evolution_orchestrator",
                status="error",
                meta={"error": str(exc)},
            )
            return {
                "status": "error",
                "error": str(exc),
            }

    async def automl_once(self) -> JsonDict:
        """
        Appelle Auto-ML si le module existe.
        Si Auto-ML n'est pas encore prêt, on log et on continue.
        """
        try:
            from .auto_ml import get_auto_ml  # import lazy volontaire

            auto_ml = get_auto_ml()

            if hasattr(auto_ml, "run_once"):
                result = await self._maybe_await(auto_ml.run_once())
            elif hasattr(auto_ml, "train"):
                result = await self._maybe_await(auto_ml.train())
            elif hasattr(auto_ml, "retrain"):
                result = await self._maybe_await(auto_ml.retrain())
            else:
                result = {
                    "status": "skipped",
                    "reason": "no_supported_method",
                }

            log_event(
                "automl_loop_ok",
                "evolution_orchestrator",
                status="ok",
                meta={"result": result},
            )

            return {
                "status": "ok",
                "result": result,
            }

        except ImportError:
            result = {
                "status": "skipped",
                "reason": "auto_ml_module_unavailable",
            }

            log_event(
                "automl_loop_skipped",
                "evolution_orchestrator",
                status="skipped",
                meta=result,
            )

            return result

        except Exception as exc:
            log_event(
                "automl_loop_error",
                "evolution_orchestrator",
                status="error",
                meta={"error": str(exc)},
            )

            return {
                "status": "error",
                "error": str(exc),
            }

    async def report_once(self) -> JsonDict:
        stats_1d = self.event_store.aggregate_daily_stats(days=1)
        stats_7d = self.event_store.aggregate_daily_stats(days=7)

        strategy = self.strategy_optimizer.get_current_strategy()

        result = {
            "status": "ok",
            "timestamp": _utc_now().isoformat(),
            "stats_1d": stats_1d,
            "stats_7d": stats_7d,
            "strategy": strategy,
            "paper_trading_only": True,
            "auto_trading": False,
        }

        log_event(
            "evolution_report",
            "evolution_orchestrator",
            status="ok",
            meta=result,
        )

        return result


_ORCHESTRATOR: Optional[EvolutionOrchestrator] = None
_LOCK = threading.RLock()


def get_evolution_orchestrator() -> EvolutionOrchestrator:
    global _ORCHESTRATOR

    with _LOCK:
        if _ORCHESTRATOR is None:
            _ORCHESTRATOR = EvolutionOrchestrator()
        return _ORCHESTRATOR


async def start_evolution() -> EvolutionOrchestrator:
    orchestrator = get_evolution_orchestrator()
    await orchestrator.start()
    return orchestrator


async def stop_evolution() -> None:
    global _ORCHESTRATOR

    if _ORCHESTRATOR is not None:
        await _ORCHESTRATOR.stop()


__all__ = [
    "EvolutionOrchestratorConfig",
    "EvolutionOrchestrator",
    "get_evolution_orchestrator",
    "start_evolution",
    "stop_evolution",
]