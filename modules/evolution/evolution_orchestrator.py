# modules/evolution/evolution_orchestrator.py
"""
Chef d'orchestre — coordinate toutes les couches.
Boucle principale: collecte → features → labels → training → optimization → validation → deployment
"""
import asyncio
import time
import logging
from datetime import datetime

from modules.evolution.event_store import get_event_store, log_event
from modules.evolution.feature_store import get_feature_store
from modules.evolution.auto_ml import get_auto_ml, maybe_retrain
from modules.evolution.strategy_optimizer import get_strategy_optimizer
from modules.evolution.drift_guard import get_drift_guard

logger = logging.getLogger(__name__)

class EvolutionOrchestrator:
    """
    Boucle d'auto-évolution perpétuelle.
    """
    
    def __init__(self):
        self.event_store = get_event_store()
        self.feature_store = get_feature_store()
        self.auto_ml = get_auto_ml()
        self.strategy_opt = get_strategy_optimizer()
        self.drift_guard = get_drift_guard()
        
        self.running = False
        self.tasks: list[asyncio.Task] = []
        
        # Intervalles (secondes)
        self.intervals = {
            "flush_events": 30,           # Flush event store
            "compute_labels": 300,        # Calcule labels pour détections non labelisées
            "retrain_check": 3600,        # Vérifie si réentraînement nécessaire
            "optimize_strategy": 86400,   # Optimisation stratégie (quotidien)
            "drift_check": 3600,          # Vérification drift (horaire)
            "compress_events": 86400,     # Compression partitions (quotidien)
            "report": 21600,              # Rapport santé (6h)
        }
    
    async def start(self):
        """Démarre toutes les boucles."""
        if self.running:
            return
        
        self.running = True
        logger.info("🧬 Evolution Orchestrator STARTED")
        
        self.tasks = [
            asyncio.create_task(self._loop("flush_events", self._flush_events)),
            asyncio.create_task(self._loop("compute_labels", self._compute_labels_loop)),
            asyncio.create_task(self._loop("retrain_check", self._retrain_check_loop)),
            asyncio.create_task(self._loop("optimize_strategy", self._optimize_strategy_loop)),
            asyncio.create_task(self._loop("drift_check", self._drift_check_loop)),
            asyncio.create_task(self._loop("compress_events", self._compress_loop)),
            asyncio.create_task(self._loop("report", self._report_loop)),
        ]
        
        log_event("orchestrator_started", "evolution_orchestrator", event_type="system")
    
    async def stop(self):
        """Arrêt propre."""
        self.running = False
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.event_store.flush_all()
        log_event("orchestrator_stopped", "evolution_orchestrator", event_type="system")
        logger.info("🧬 Evolution Orchestrator STOPPED")
    
    async def _loop(self, name: str, coro_func):
        """Boucle générique avec intervalle."""
        interval = self.intervals[name]
        while self.running:
            try:
                start = time.time()
                await coro_func()
                elapsed = time.time() - start
                await asyncio.sleep(max(0, interval - elapsed))
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Loop {name} error: {e}")
                log_event("loop_error", "evolution_orchestrator", 
                         loop=name, error=str(e), event_type="system_error")
                await asyncio.sleep(interval)
    
    async def _flush_events(self):
        self.event_store.flush_all()
    
    async def _compute_labels_loop(self):
        """Calcule labels pour toutes les détections non labelisées."""
        # Récupère events "detection" sans outcome récent
        end_ts = time.time()
        start_ts = end_ts - (7 * 86400)  # 7 jours
        
        events = self.event_store.query(start_ts, end_ts, event_types=["detection"])
        unlabeled = [e for e in events if not e.outcome.get("labeled", False)]
        
        for event in unlabeled[:100]:  # Batch de 100 max par cycle
            # Récupère price history depuis simulator / DexScreener
            price_history = await self._fetch_price_history(event.token_mint, event.timestamp)
            if price_history:
                labels = self.feature_store.compute_labels(
                    event.token_mint, event.timestamp, price_history
                )
                self.feature_store.save_label_set(labels)
                
                # Met à jour l'event original
                event.outcome["labeled"] = True
                event.outcome["labels"] = labels.labels
                # Ré-écrit l'event (append nouvelle version)
                log_event("detection", event.source_module, 
                         token_mint=event.token_mint,
                         timestamp=event.timestamp,
                         features=event.features,
                         decision=event.decision,
                         outcome=event.outcome,
                         meta=event.meta)
    
    async def _fetch_price_history(self, token_mint: str, start_ts: float) -> list[dict]:
        """À connecter à ton simulator / DexScreener cache."""
        # TODO: implémenter avec modules/simulator.py ou cache DexScreener
        return []
    
    async def _retrain_check_loop(self):
        maybe_retrain()
    
    async def _optimize_strategy_loop(self):
        """Optimisation quotidienne de la stratégie."""
        if not self.drift_guard.is_evolution_allowed():
            logger.info("Strategy optimization skipped: evolution paused by drift guard")
            return
        
        logger.info("🔧 Starting daily strategy optimization...")
        try:
            best_config = self.strategy_opt.optimize(n_trials=50, timeout=1800)
            if best_config:
                # Applique la nouvelle config (hot reload)
                await self._apply_config(best_config)
                log_event("config_updated", "evolution_orchestrator",
                         config=best_config.to_dict(), event_type="config_change")
        except Exception as e:
            logger.error(f"Strategy optimization failed: {e}")
    
    async def _apply_config(self, config):
        """Hot-reload config dans modules actifs."""
        # Écrit config optimisée
        import json
        from pathlib import Path
        Path("data/optimized_config.json").write_text(json.dumps(config.to_dict(), indent=2))
        
        # Notifie modules (via event bus ou callback)
        log_event("config_reload_requested", "evolution_orchestrator", event_type="config_change")
    
    async def _drift_check_loop(self):
        alerts = self.drift_guard.check_health()
        if alerts:
            logger.warning(f"Drift check: {len(alerts)} alerts raised")
    
    async def _compress_loop(self):
        self.event_store.compress_old_partitions(days_old=1)
    
    async def _report_loop(self):
        """Rapport de santé périodique."""
        status = {
            "timestamp": time.time(),
            "champion_model": self.auto_ml.champion.model_id if self.auto_ml.champion else None,
            "champion_age_days": (time.time() - self.auto_ml.champion.metrics.trained_at) / 86400 if self.auto_ml.champion else None,
            "trading_paused": self.drift_guard.trading_paused,
            "evolution_paused": self.drift_guard.auto_evolution_paused,
            "unacknowledged_alerts": len(self.drift_guard.get_unacknowledged_alerts()),
            "recent_trades": len(self.drift_guard.recent_trades),
            "best_strategy_value": self.strategy_opt.study.best_value if self.strategy_opt.study.trials else None,
        }
        
        log_event("health_report", "evolution_orchestrator", **status, event_type="report")
        logger.info(f"📊 Health Report: {status}")


# Singleton
_orchestrator: EvolutionOrchestrator | None = None

def get_orchestrator() -> EvolutionOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = EvolutionOrchestrator()
    return _orchestrator

async def start_evolution():
    """Point d'entrée à appeler au démarrage du bot (dans main.py)."""
    orch = get_orchestrator()
    await orch.start()

async def stop_evolution():
    orch = get_orchestrator()
    await orch.stop()