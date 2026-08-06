"""
MemeSniper v14.1-EVOLUTION
Event Store robuste SQLite

Correctifs importants :
- log_event accepte *args et **kwargs
- corrige définitivement :
  log_event() got multiple values for argument 'event_type'
- supporte source_module / source
- supporte event_type en doublon en le déplaçant dans meta["subtype"]
- corrige les bugs de dates avec timedelta
- l'Event Store ne doit jamais faire planter le bot principal
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


JsonDict = Dict[str, Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: Any = None) -> str:
    if value is None:
        return _utc_now().isoformat()

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=timezone.utc).isoformat()

    return str(value)


def _json_default(obj: Any) -> Any:
    try:
        import numpy as np  # type: ignore

        if isinstance(obj, np.integer):
            return int(obj)

        if isinstance(obj, np.floating):
            return float(obj)

        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass

    if isinstance(obj, (datetime, date)):
        return _to_iso(obj)

    if isinstance(obj, set):
        return list(obj)

    return str(obj)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _safe_json_loads(raw: Any) -> JsonDict:
    try:
        data = json.loads(raw or "{}")
        if isinstance(data, dict):
            return data
        return {"value": data}
    except Exception:
        return {}


@dataclass(init=False)
class BotEvent:
    """
    Événement flexible.

    Cette classe accepte volontairement *args et **kwargs.

    Exemples supportés :

    BotEvent("detection", "early_detector", token_mint="...")
    BotEvent(event_type="detection", source_module="early_detector")
    BotEvent("orchestrator_started", "evolution_orchestrator", event_type="system")

    Le dernier cas ne plante plus : event_type="system" devient meta["subtype"].
    """

    id: str
    timestamp: str
    event_type: str
    source_module: str

    token_mint: Optional[str]
    token_symbol: Optional[str]

    score: Optional[float]
    price_usd: Optional[float]
    market_cap: Optional[float]
    liquidity: Optional[float]
    volume_24h: Optional[float]
    holders: Optional[float]

    outcome: Optional[str]
    pnl_pct: Optional[float]
    confidence: Optional[float]

    status: Optional[str]
    tags: List[str]
    meta: JsonDict

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        meta: JsonDict = {}

        # 1) event_type principal
        if len(args) >= 1:
            main_event_type = str(args[0] or "unknown")

            # Si event_type existe aussi en keyword, on ne plante pas.
            # On le garde comme sous-type metadata.
            if "event_type" in kwargs:
                meta["subtype"] = kwargs.pop("event_type")
        else:
            main_event_type = str(kwargs.pop("event_type", "unknown") or "unknown")

        # 2) source principal
        if len(args) >= 2:
            main_source = str(args[1] or "unknown")

            if "source_module" in kwargs:
                meta["source_module_alias"] = kwargs.pop("source_module")

            if "source" in kwargs:
                meta["source_alias"] = kwargs.pop("source")
        else:
            if "source_module" in kwargs:
                main_source = str(kwargs.pop("source_module") or "unknown")
            elif "source" in kwargs:
                main_source = str(kwargs.pop("source") or "unknown")
            else:
                main_source = "unknown"

        # 3) Args supplémentaires éventuels
        if len(args) > 2:
            meta["extra_args"] = list(args[2:])

        # 4) Meta utilisateur
        raw_meta = kwargs.pop("meta", {})
        if isinstance(raw_meta, dict):
            meta.update(raw_meta)
        elif raw_meta not in (None, ""):
            meta["meta_raw"] = raw_meta

        self.timestamp = _to_iso(kwargs.pop("timestamp", None))

        self.event_type = main_event_type or "unknown"
        self.source_module = main_source or "unknown"

        self.token_mint = kwargs.pop("token_mint", None)
        self.token_symbol = kwargs.pop("token_symbol", None)

        self.score = _safe_float(kwargs.pop("score", None))
        self.price_usd = _safe_float(kwargs.pop("price_usd", None))
        self.market_cap = _safe_float(kwargs.pop("market_cap", None))
        self.liquidity = _safe_float(kwargs.pop("liquidity", None))
        self.volume_24h = _safe_float(kwargs.pop("volume_24h", None))
        self.holders = _safe_float(kwargs.pop("holders", None))

        self.outcome = kwargs.pop("outcome", None)
        self.pnl_pct = _safe_float(kwargs.pop("pnl_pct", None))
        self.confidence = _safe_float(kwargs.pop("confidence", None))

        self.status = kwargs.pop("status", None)

        raw_tags = kwargs.pop("tags", [])
        if isinstance(raw_tags, list):
            self.tags = [str(x) for x in raw_tags]
        elif raw_tags:
            self.tags = [str(raw_tags)]
        else:
            self.tags = []

        # Tout champ inconnu part dans meta au lieu de faire planter le bot
        for key, value in kwargs.items():
            meta[key] = value

        # Si id est fourni, on le récupère
        provided_id = meta.pop("id", None)

        self.meta = meta
        self.id = str(provided_id or self._make_id())

    def _make_id(self) -> str:
        raw = json.dumps(
            {
                "timestamp": self.timestamp,
                "event_type": self.event_type,
                "source_module": self.source_module,
                "token_mint": self.token_mint,
                "token_symbol": self.token_symbol,
                "score": self.score,
                "status": self.status,
                "meta": self.meta,
            },
            sort_keys=True,
            default=_json_default,
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def to_dict(self) -> JsonDict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "source_module": self.source_module,
            "token_mint": self.token_mint,
            "token_symbol": self.token_symbol,
            "score": self.score,
            "price_usd": self.price_usd,
            "market_cap": self.market_cap,
            "liquidity": self.liquidity,
            "volume_24h": self.volume_24h,
            "holders": self.holders,
            "outcome": self.outcome,
            "pnl_pct": self.pnl_pct,
            "confidence": self.confidence,
            "status": self.status,
            "tags": self.tags,
            "meta": self.meta,
        }


class EventStore:
    def __init__(self, db_path: Optional[Union[str, Path]] = None) -> None:
        default_path = Path("data") / "evolution" / "events.sqlite3"

        self.db_path = Path(
            db_path
            or os.getenv("EVOLUTION_DB_PATH")
            or os.getenv("EVENT_STORE_DB")
            or default_path
        )

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")

                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        source_module TEXT NOT NULL,
                        token_mint TEXT,
                        token_symbol TEXT,
                        score REAL,
                        outcome TEXT,
                        pnl_pct REAL,
                        status TEXT,
                        payload TEXT NOT NULL
                    );
                    """
                )

                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_source ON events(source_module);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_token ON events(token_mint);"
                )

                # Migration douce si ancienne DB sans colonne status
                try:
                    conn.execute("ALTER TABLE events ADD COLUMN status TEXT;")
                except Exception:
                    pass

    def append(
        self,
        event: Optional[Union[BotEvent, Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> str:
        if isinstance(event, BotEvent):
            bot_event = event
        elif isinstance(event, dict):
            bot_event = BotEvent(**event)
        elif event is None:
            bot_event = BotEvent(**kwargs)
        else:
            bot_event = BotEvent(
                "unknown_event_object",
                "event_store",
                raw_event=event,
                **kwargs,
            )

        payload = bot_event.to_dict()

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO events (
                        id,
                        timestamp,
                        event_type,
                        source_module,
                        token_mint,
                        token_symbol,
                        score,
                        outcome,
                        pnl_pct,
                        status,
                        payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        bot_event.id,
                        bot_event.timestamp,
                        bot_event.event_type,
                        bot_event.source_module,
                        bot_event.token_mint,
                        bot_event.token_symbol,
                        bot_event.score,
                        bot_event.outcome,
                        bot_event.pnl_pct,
                        bot_event.status,
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            default=_json_default,
                        ),
                    ),
                )

        return bot_event.id

    def append_event(self, *args: Any, **kwargs: Any) -> str:
        event = BotEvent(*args, **kwargs)
        return self.append(event)

    def log_event(self, *args: Any, **kwargs: Any) -> str:
        event = BotEvent(*args, **kwargs)
        return self.append(event)

    def query_events(
        self,
        event_type: Optional[str] = None,
        source_module: Optional[str] = None,
        token_mint: Optional[str] = None,
        since: Optional[Any] = None,
        until: Optional[Any] = None,
        limit: int = 1000,
        ascending: bool = False,
    ) -> List[JsonDict]:
        where: List[str] = []
        params: List[Any] = []

        if event_type:
            where.append("event_type = ?")
            params.append(event_type)

        if source_module:
            where.append("source_module = ?")
            params.append(source_module)

        if token_mint:
            where.append("token_mint = ?")
            params.append(token_mint)

        if since:
            where.append("timestamp >= ?")
            params.append(_to_iso(since))

        if until:
            where.append("timestamp < ?")
            params.append(_to_iso(until))

        sql = "SELECT * FROM events"

        if where:
            sql += " WHERE " + " AND ".join(where)

        sql += " ORDER BY timestamp " + ("ASC" if ascending else "DESC")
        sql += " LIMIT ?"

        params.append(max(1, int(limit)))

        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(sql, params).fetchall()

        events: List[JsonDict] = []

        for row in rows:
            payload = _safe_json_loads(row["payload"])

            payload.update(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "event_type": row["event_type"],
                    "source_module": row["source_module"],
                    "token_mint": row["token_mint"],
                    "token_symbol": row["token_symbol"],
                    "score": row["score"],
                    "outcome": row["outcome"],
                    "pnl_pct": row["pnl_pct"],
                }
            )

            try:
                payload["status"] = row["status"]
            except Exception:
                pass

            events.append(payload)

        return events

    def query(self, *args: Any, **kwargs: Any) -> List[JsonDict]:
        """
        Alias de compatibilité.

        Certains bouts du bot appellent encore :
            event_store.query(...)

        Alors que la nouvelle version utilise :
            event_store.query_events(...)

        Cette méthode évite :
            'EventStore' object has no attribute 'query'
        """

        filters: JsonDict = {}

        if len(args) == 1 and isinstance(args[0], dict):
            filters.update(args[0])
        elif len(args) >= 1 and isinstance(args[0], str):
            filters["event_type"] = args[0]

        filters.update(kwargs)

        if "source" in filters and "source_module" not in filters:
            filters["source_module"] = filters.pop("source")

        if "start_date" in filters and "since" not in filters:
            filters["since"] = filters.pop("start_date")

        if "start_time" in filters and "since" not in filters:
            filters["since"] = filters.pop("start_time")

        if "from_ts" in filters and "since" not in filters:
            filters["since"] = filters.pop("from_ts")

        if "end_date" in filters and "until" not in filters:
            filters["until"] = filters.pop("end_date")

        if "end_time" in filters and "until" not in filters:
            filters["until"] = filters.pop("end_time")

        if "to_ts" in filters and "until" not in filters:
            filters["until"] = filters.pop("to_ts")

        if "token" in filters and "token_mint" not in filters:
            filters["token_mint"] = filters.pop("token")

        if "mint" in filters and "token_mint" not in filters:
            filters["token_mint"] = filters.pop("mint")

        if "address" in filters and "token_mint" not in filters:
            filters["token_mint"] = filters.pop("address")

        if "days" in filters and "since" not in filters:
            try:
                filters["since"] = _utc_now() - timedelta(days=int(filters.pop("days")))
            except Exception:
                filters.pop("days", None)

        event_type = filters.get("event_type")
        event_types = None

        if isinstance(event_type, (list, tuple, set)):
            event_types = set(str(x) for x in event_type)
            filters["event_type"] = None

        try:
            limit = int(filters.get("limit", 1000) or 1000)
        except Exception:
            limit = 1000

        events = self.query_events(
            event_type=filters.get("event_type"),
            source_module=filters.get("source_module"),
            token_mint=filters.get("token_mint"),
            since=filters.get("since"),
            until=filters.get("until"),
            limit=limit,
            ascending=bool(filters.get("ascending", False)),
        )

        if event_types:
            events = [
                event for event in events
                if str(event.get("event_type")) in event_types
            ]

        return events


    def get_events(self, *args: Any, **kwargs: Any) -> List[JsonDict]:
        return self.query_events(*args, **kwargs)

    def get_recent_events(self, limit: int = 200) -> List[JsonDict]:
        return self.query_events(limit=limit)

    def count_events(
        self,
        event_type: Optional[str] = None,
        since: Optional[Any] = None,
        until: Optional[Any] = None,
    ) -> int:
        where: List[str] = []
        params: List[Any] = []

        if event_type:
            where.append("event_type = ?")
            params.append(event_type)

        if since:
            where.append("timestamp >= ?")
            params.append(_to_iso(since))

        if until:
            where.append("timestamp < ?")
            params.append(_to_iso(until))

        sql = "SELECT COUNT(*) AS c FROM events"

        if where:
            sql += " WHERE " + " AND ".join(where)

        with self._lock:
            with self._connect() as conn:
                row = conn.execute(sql, params).fetchone()

        if not row:
            return 0

        return int(row["c"] or 0)

    def get_events_between(
        self,
        start_date: Any,
        end_date: Any,
        limit_per_day: int = 5000,
    ) -> List[JsonDict]:
        """
        Corrigé : utilise timedelta(days=1)
        au lieu de manipuler current.day + 1.
        """

        if isinstance(start_date, datetime):
            current = start_date.date()
        elif isinstance(start_date, date):
            current = start_date
        else:
            current = datetime.fromisoformat(str(start_date)).date()

        if isinstance(end_date, datetime):
            last = end_date.date()
        elif isinstance(end_date, date):
            last = end_date
        else:
            last = datetime.fromisoformat(str(end_date)).date()

        results: List[JsonDict] = []

        while current <= last:
            day_start = datetime.combine(current, time.min, tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)

            results.extend(
                self.query_events(
                    since=day_start,
                    until=day_end,
                    limit=limit_per_day,
                    ascending=True,
                )
            )

            current = current + timedelta(days=1)

        return results

    def aggregate_daily_stats(self, days: int = 7) -> JsonDict:
        since = _utc_now() - timedelta(days=max(1, int(days)))
        events = self.query_events(since=since, limit=10000, ascending=True)

        stats: JsonDict = {
            "days": days,
            "total_events": len(events),
            "by_type": {},
            "by_source": {},
            "alerts": 0,
            "detections": 0,
            "paper_trades": 0,
            "avg_score": None,
        }

        scores: List[float] = []

        for event in events:
            event_type = event.get("event_type") or "unknown"
            source_module = event.get("source_module") or "unknown"

            stats["by_type"][event_type] = stats["by_type"].get(event_type, 0) + 1
            stats["by_source"][source_module] = stats["by_source"].get(source_module, 0) + 1

            if event_type in ("alert", "telegram_alert", "token_alert"):
                stats["alerts"] += 1

            if event_type in ("detection", "token_detected", "new_token"):
                stats["detections"] += 1

            if event_type in (
                "paper_trade",
                "simulation",
                "sim_trade",
                "sim_buy",
                "sim_sell",
                "paper_trade_outcome",
            ):
                stats["paper_trades"] += 1

            score = _safe_float(event.get("score"))

            if score is not None:
                scores.append(score)

        if scores:
            stats["avg_score"] = sum(scores) / len(scores)

        return stats

    def export_jsonl(self, output_path: Union[str, Path], limit: int = 10000) -> str:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        events = self.query_events(limit=limit, ascending=True)

        with path.open("w", encoding="utf-8") as f:
            for event in events:
                f.write(json.dumps(event, ensure_ascii=False, default=_json_default) + "\n")

        return str(path)

    def purge_old_events(self, days: int = 90) -> int:
        cutoff = _to_iso(_utc_now() - timedelta(days=max(1, int(days))))

        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM events WHERE timestamp < ?;",
                    (cutoff,),
                )
                deleted = cursor.rowcount or 0

        return int(deleted)

    def close(self) -> None:
        pass


_EVENT_STORE: Optional[EventStore] = None
_EVENT_STORE_LOCK = threading.RLock()


def get_event_store() -> EventStore:
    global _EVENT_STORE

    with _EVENT_STORE_LOCK:
        if _EVENT_STORE is None:
            _EVENT_STORE = EventStore()

        return _EVENT_STORE


def log_event(*args: Any, **kwargs: Any) -> str:
    """
    Logger global ultra-compatible.

    Cette signature est volontairement :

        def log_event(*args, **kwargs)

    Donc ces appels fonctionnent :

        log_event("detection", "early_detector", token_mint="...")
        log_event(event_type="detection", source_module="early_detector")
        log_event("orchestrator_started", "evolution_orchestrator", event_type="system")

    L'ancien bug venait d'une signature du type :

        def log_event(event_type, source, **kwargs)

    qui cassait quand event_type était envoyé deux fois.
    """

    try:
        event = BotEvent(*args, **kwargs)
        return get_event_store().append(event)

    except Exception as exc:
        # Filet de sécurité absolu.
        # L'Event Store ne doit jamais stopper MemeSniper.
        try:
            fallback = BotEvent(
                "event_store_error",
                "event_store",
                error=str(exc),
                original_args=[str(x) for x in args],
                original_kwargs={str(k): str(v) for k, v in kwargs.items()},
            )
            return get_event_store().append(fallback)
        except Exception:
            return "event_store_failed"


def record_event(*args: Any, **kwargs: Any) -> str:
    return log_event(*args, **kwargs)


def append_event(*args: Any, **kwargs: Any) -> str:
    return log_event(*args, **kwargs)


__all__ = [
    "BotEvent",
    "EventStore",
    "get_event_store",
    "log_event",
    "record_event",
    "append_event",
]