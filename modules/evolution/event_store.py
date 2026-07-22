# modules/evolution/event_store.py
"""
Event Store immuable — Source de vérité unique.
Append-only, partitionné par jour, schema versionné.
"""
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Any, Optional
from datetime import datetime
from pathlib import Path
import threading
import gzip

EVENT_SCHEMA_VERSION = "2.0"

@dataclass
class BotEvent:
    """Event canonique — TOUT passe par ici."""
    # Identité
    event_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    schema_version: str = EVENT_SCHEMA_VERSION
    
    # Type & Source
    event_type: str = ""           # detection, decision, outcome, model_update, config_change
    source_module: str = ""        # grpc_listener, token_analyzer, decision_engine, simulator, etc.
    
    # Contexte token
    token_mint: str = ""
    token_symbol: str = ""
    pool_address: str = ""
    
    # Features à T0 (snapshot au moment de la décision)
    features: dict = field(default_factory=dict)
    
    # Décision prise
    decision: dict = field(default_factory=dict)  # {tier, score, safety, action, reason, conviction_factors}
    
    # Outcome (rempli plus tard par outcome_updater)
    outcome: dict = field(default_factory=dict)   # {max_roi, min_roi, time_to_peak, rugged, exit_reason, pnl_pct}
    
    # Métadonnées
    meta: dict = field(default_factory=dict)      # {bot_version, config_hash, regime, etc.}

class EventStore:
    """
    Stockage append-only partitionné par jour.
    Compression gzip automatique après 24h.
    """
    
    def __init__(self, base_path: str = "data/events"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._buffers: dict[str, list[BotEvent]] = {}  # date -> events
        self._flush_interval = 10  # flush every 10 events
        self._counters: dict[str, int] = {}
        
    def _get_date_key(self, ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y%m%d")
    
    def _get_file_path(self, date_key: str, compressed: bool = False) -> Path:
        ext = ".jsonl.gz" if compressed else ".jsonl"
        return self.base_path / f"events_{date_key}{ext}"
    
    def append(self, event: BotEvent) -> str:
        """Thread-safe append. Retourne event_id."""
        date_key = self._get_date_key(event.timestamp)
        
        with self._lock:
            if date_key not in self._buffers:
                self._buffers[date_key] = []
                self._counters[date_key] = 0
            
            self._buffers[date_key].append(event)
            self._counters[date_key] += 1
            
            # Flush périodique
            if self._counters[date_key] >= self._flush_interval:
                self._flush_date(date_key)
        
        return event.event_id
    
    def _flush_date(self, date_key: str):
        """Écrit le buffer sur disque."""
        if date_key not in self._buffers or not self._buffers[date_key]:
            return
        
        file_path = self._get_file_path(date_key, compressed=False)
        with open(file_path, "a", encoding="utf-8") as f:
            for event in self._buffers[date_key]:
                f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        
        self._buffers[date_key].clear()
        self._counters[date_key] = 0
    
    def flush_all(self):
        """Force flush tous les buffers."""
        with self._lock:
            for date_key in list(self._buffers.keys()):
                self._flush_date(date_key)
    
    def compress_old_partitions(self, days_old: int = 1):
        """Compresse les partitions de plus de N jours."""
        cutoff = datetime.now().timestamp() - (days_old * 86400)
        for file_path in self.base_path.glob("events_*.jsonl"):
            # Extract date from filename
            try:
                date_str = file_path.stem.replace("events_", "")
                file_date = datetime.strptime(date_str, "%Y%m%d").timestamp()
                if file_date < cutoff:
                    self._compress_file(file_path)
            except ValueError:
                continue
    
    def _compress_file(self, src: Path):
        dst = src.with_suffix(".jsonl.gz")
        with open(src, "rb") as f_in, gzip.open(dst, "wb") as f_out:
            f_out.write(f_in.read())
        src.unlink()
    
    def query(self, 
              start_ts: float, 
              end_ts: float, 
              event_types: list[str] | None = None,
              token_mint: str | None = None) -> list[BotEvent]:
        """Lit events dans une fenêtre temporelle."""
        results = []
        current = datetime.fromtimestamp(start_ts)
        end_dt = datetime.fromtimestamp(end_ts)
        
        while current <= end_dt:
            date_key = current.strftime("%Y%m%d")
            for ext in [".jsonl", ".jsonl.gz"]:
                file_path = self.base_path / f"events_{date_key}{ext}"
                if file_path.exists():
                    results.extend(self._read_file(file_path, start_ts, end_ts, event_types, token_mint))
            current = current.replace(day=current.day + 1)
        
        return results
    
    def _read_file(self, path: Path, start_ts: float, end_ts: float, 
                   event_types: list[str] | None, token_mint: str | None) -> list[BotEvent]:
        events = []
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    ts = data.get("timestamp", 0)
                    if ts < start_ts or ts > end_ts:
                        continue
                    if event_types and data.get("event_type") not in event_types:
                        continue
                    if token_mint and data.get("token_mint") != token_mint:
                        continue
                    events.append(BotEvent(**data))
                except Exception:
                    continue
        return events


# === SINGLETON GLOBAL ===
_event_store: EventStore | None = None

def get_event_store() -> EventStore:
    global _event_store
    if _event_store is None:
        _event_store = EventStore()
    return _event_store

def log_event(event_type: str, source: str, **kwargs) -> str:
    """Helper rapide pour logger depuis n'importe où."""
    store = get_event_store()
    event = BotEvent(
        event_type=event_type,
        source_module=source,
        **kwargs
    )
    return store.append(event)