"""
MemeSniper v14.1-EVOLUTION
Performance Analyzer winners/losers

Objectifs :
- Analyse data/simulations.json et data/performance.json
- Compare winners vs losers
- Identifie les grosses pertes
- Génère des recommandations concrètes
- Alimente le dashboard v14.1
- Aucun trading réel
"""

from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


JsonDict = Dict[str, Any]


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


def _safe_float(
    value: Any,
    default: float = 0.0,
) -> float:
    try:
        if value is None or value == "":
            return default

        return float(str(value).replace(",", "."))

    except Exception:
        return default


def _load_json(
    path: Path,
    default: Any,
) -> Any:
    try:
        if not path.exists():
            return default

        return json.loads(
            path.read_text(encoding="utf-8")
        )

    except Exception:
        return default


def _avg(values: List[float]) -> float:
    return round(statistics.mean(values), 4) if values else 0.0


def _median(values: List[float]) -> float:
    return round(statistics.median(values), 4) if values else 0.0


@dataclass
class AnalyzerConfig:
    simulations_path: Path = field(
        default_factory=lambda: _data_dir() / "simulations.json"
    )

    performance_path: Path = field(
        default_factory=lambda: _data_dir() / "performance.json"
    )

    output_path: Path = field(
        default_factory=lambda: (
            _data_dir()
            / "evolution"
            / "performance_report.json"
        )
    )


class PerformanceAnalyzer:
    def __init__(
        self,
        config: Optional[AnalyzerConfig] = None,
    ) -> None:
        self.config = config or AnalyzerConfig()

        self.config.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _load(self) -> tuple[list[JsonDict], JsonDict]:
        simulations = _load_json(
            self.config.simulations_path,
            {},
        )

        performance = _load_json(
            self.config.performance_path,
            {},
        )

        history = (
            simulations.get("history", [])
            if isinstance(simulations, dict)
            else []
        )

        if not isinstance(history, list):
            history = []

        if not isinstance(performance, dict):
            performance = {}

        return history, performance

    def _join_rows(self) -> List[JsonDict]:
        history, performance = self._load()

        rows: List[JsonDict] = []

        for trade in history:
            if not isinstance(trade, dict):
                continue

            if not trade.get("closed"):
                continue

            mint = (
                trade.get("mint")
                or trade.get("token_mint")
                or ""
            )

            perf = (
                performance.get(mint, {})
                if isinstance(performance, dict)
                else {}
            )

            if not isinstance(perf, dict):
                perf = {}

            row = {
                "mint": mint,
                "symbol": (
                    trade.get("symbol")
                    or perf.get("symbol")
                    or "?"
                ),
                "pnl_pct": _safe_float(
                    trade.get("pnl_pct")
                ),
                "pnl_eur": _safe_float(
                    trade.get("pnl_eur")
                ),
                "duration_min": _safe_float(
                    trade.get("duration_min")
                ),
                "exit_reason": trade.get(
                    "exit_reason",
                    "unknown",
                ),
                "alert_score": _safe_float(
                    trade.get(
                        "alert_score",
                        perf.get("score", 0),
                    )
                ),
                "alert_tier": trade.get(
                    "alert_tier",
                    perf.get("tier", "?"),
                ),
                "entry_mc": _safe_float(
                    trade.get(
                        "entry_mc",
                        perf.get("market_cap", 0),
                    )
                ),
                "entry_price": _safe_float(
                    trade.get(
                        "entry_price",
                        perf.get("price_entry", 0),
                    )
                ),
                "max_gain_pct": _safe_float(
                    trade.get("max_gain_pct")
                ),
                "min_loss_pct": _safe_float(
                    trade.get("min_loss_pct")
                ),
                "score": _safe_float(
                    perf.get(
                        "score",
                        trade.get("alert_score", 0),
                    )
                ),
                "market_cap": _safe_float(
                    perf.get(
                        "market_cap",
                        trade.get("entry_mc", 0),
                    )
                ),
                "liquidity": _safe_float(
                    perf.get("liquidity", 0)
                ),
                "volume_5m": _safe_float(
                    perf.get("volume_5m", 0)
                ),
                "volume_1h": _safe_float(
                    perf.get("volume_1h", 0)
                ),
                "age_minutes": _safe_float(
                    perf.get("age_minutes", 0)
                ),
                "vol_accel": _safe_float(
                    perf.get("vol_accel", 0)
                ),
                "ratio_5m": _safe_float(
                    perf.get("ratio_5m", 0)
                ),
                "alpha_wallets": _safe_float(
                    perf.get("alpha_wallets", 0)
                ),
                "smart_count": _safe_float(
                    perf.get("smart_count", 0)
                ),
                "has_critical": bool(
                    perf.get("has_critical", False)
                ),
            }

            rows.append(row)

        return rows

    def _profile(
        self,
        rows: List[JsonDict],
    ) -> JsonDict:
        fields = [
            "alert_score",
            "score",
            "market_cap",
            "liquidity",
            "volume_5m",
            "volume_1h",
            "age_minutes",
            "vol_accel",
            "ratio_5m",
            "alpha_wallets",
            "smart_count",
            "duration_min",
        ]

        result: JsonDict = {
            "count": len(rows),
        }

        for field in fields:
            values = [
                _safe_float(row.get(field))
                for row in rows
                if row.get(field) is not None
            ]

            result[field] = {
                "avg": _avg(values),
                "median": _median(values),
            }

        return result

    def analyze(
        self,
        save: bool = True,
    ) -> JsonDict:
        rows = self._join_rows()

        closed = len(rows)

        wins = [
            row
            for row in rows
            if row["pnl_pct"] > 0
        ]

        losses = [
            row
            for row in rows
            if row["pnl_pct"] <= 0
        ]

        big_losses = [
            row
            for row in rows
            if row["pnl_pct"] <= -30
        ]

        rug_like_losses = [
            row
            for row in rows
            if row["pnl_pct"] <= -70
        ]

        total_invested = closed * 10.0

        total_pnl = sum(
            row["pnl_eur"]
            for row in rows
        )

        roi = (
            total_pnl / total_invested * 100
            if total_invested
            else 0.0
        )

        win_rate = (
            len(wins) / closed * 100
            if closed
            else 0.0
        )

        by_tier: JsonDict = {}
        by_reason: JsonDict = {}

        for row in rows:
            tier = row.get("alert_tier") or "?"
            reason = row.get("exit_reason") or "unknown"

            for bucket, key in (
                (by_tier, tier),
                (by_reason, reason),
            ):
                bucket.setdefault(
                    key,
                    {
                        "count": 0,
                        "pnl_eur": 0.0,
                        "wins": 0,
                    },
                )

                bucket[key]["count"] += 1
                bucket[key]["pnl_eur"] += row["pnl_eur"]

                if row["pnl_pct"] > 0:
                    bucket[key]["wins"] += 1

        for bucket in (by_tier, by_reason):
            for value in bucket.values():
                value["pnl_eur"] = round(
                    value["pnl_eur"],
                    2,
                )

                value["win_rate"] = round(
                    value["wins"]
                    / max(value["count"], 1)
                    * 100,
                    1,
                )

        recommendations: List[str] = []

        if win_rate < 35:
            recommendations.append(
                "Baisser MAX_ALERTS_PER_HOUR à 8-10 et garder MIN_SCORE ≥ 8.0."
            )

        if roi < 0:
            recommendations.append(
                "Ne pas activer le trading réel : ROI paper encore négatif."
            )

        if len(rug_like_losses) >= 1:
            recommendations.append(
                "Activer stop-loss simulateur plus rapide et emergency exit liquidité/prix indisponible."
            )

        if big_losses:
            med_liq_loss = _median(
                [
                    row["liquidity"]
                    for row in big_losses
                    if row["liquidity"] > 0
                ]
            )

            if med_liq_loss and med_liq_loss < 20000:
                recommendations.append(
                    "Durcir filtre liquidité : éviter alertes non-alpha sous 15-20k$ de liquidité."
                )

            recommendations.append(
                "Ajouter filtre conviction : score 10 seul ne suffit pas si conviction/alpha=0."
            )

        if closed < 150:
            recommendations.append(
                "Continuer paper trading jusqu'à 150-200 trades avant auto-buy réel."
            )

        report: JsonDict = {
            "generated_at": time.time(),
            "summary": {
                "closed": closed,
                "wins": len(wins),
                "losses": len(losses),
                "big_losses": len(big_losses),
                "rug_like_losses": len(rug_like_losses),
                "win_rate": round(win_rate, 1),
                "total_pnl_eur": round(total_pnl, 2),
                "roi_pct": round(roi, 1),
            },
            "profiles": {
                "wins": self._profile(wins),
                "losses": self._profile(losses),
                "big_losses": self._profile(big_losses),
            },
            "by_tier": by_tier,
            "by_reason": by_reason,
            "best_trades": sorted(
                rows,
                key=lambda row: row["pnl_pct"],
                reverse=True,
            )[:10],
            "worst_trades": sorted(
                rows,
                key=lambda row: row["pnl_pct"],
            )[:10],
            "recommendations": recommendations,
            "paper_trading_only": True,
            "auto_trading": False,
        }

        if save:
            self.config.output_path.write_text(
                json.dumps(
                    report,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        return report

    def get_status(self) -> JsonDict:
        report = self.analyze(save=False)

        return {
            "summary": report.get("summary", {}),
            "recommendations": (
                report.get("recommendations", [])[:5]
            ),
            "output_path": str(self.config.output_path),
        }


_ANALYZER: Optional[PerformanceAnalyzer] = None


def get_performance_analyzer() -> PerformanceAnalyzer:
    global _ANALYZER

    if _ANALYZER is None:
        _ANALYZER = PerformanceAnalyzer()

    return _ANALYZER


__all__ = [
    "AnalyzerConfig",
    "PerformanceAnalyzer",
    "get_performance_analyzer",
]