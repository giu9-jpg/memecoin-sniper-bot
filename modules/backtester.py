# modules/backtester.py v1.0
"""
Backtester - Simule tes réglages sur les bulls passés
Permet de tester des paramètres SANS attendre des jours.
"""

from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("backtester")


class Backtester:

    def __init__(self, bull_analyzer):
        """
        bull_analyzer : instance de BullRunAnalyzer
                        pour accéder aux bulls détectés
        """
        self.bull_analyzer = bull_analyzer

    def backtest(
        self,
        min_score: float = 7.5,
        min_liquidity: int = 5_000,
        min_volume: int = 100_000,
        min_buy_ratio: float = 55,
        max_mc: int = 20_000_000,
        days: int = 30,
    ) -> dict:
        """
        Simule les réglages sur les bulls historiques.

        Retourne :
          - total_bulls : nombre de bulls dans la période
          - would_alert : combien auraient déclenché une alerte
          - hit_rate    : % de bulls qui auraient été alertés
          - avg_gain    : gain moyen des bulls alertés
          - top_5       : les 5 meilleurs bulls qu'on aurait catchés
          - missed_5    : les 5 meilleurs bulls qu'on aurait ratés
        """
        bulls = self.bull_analyzer.bulls

        if not bulls:
            return {
                "total_bulls":  0,
                "would_alert":  0,
                "hit_rate":     0,
                "avg_gain":     0,
                "message":      "Pas encore de bulls dans l'historique",
            }

        # Filtre par période
        import time
        cutoff = time.time() - (days * 86400)
        recent = []
        for b in bulls:
            try:
                dt = datetime.fromisoformat(b["detected_at"])
                if dt.timestamp() >= cutoff:
                    recent.append(b)
            except Exception:
                continue

        if not recent:
            return {
                "total_bulls":  0,
                "would_alert":  0,
                "hit_rate":     0,
                "avg_gain":     0,
                "message":      f"Pas de bulls dans les {days} derniers jours",
            }

        # Simulation
        would_alert   = []
        would_miss    = []

        for bull in recent:
            passes = self._check_bull(
                bull,
                min_liquidity=min_liquidity,
                min_volume=min_volume,
                min_buy_ratio=min_buy_ratio,
                max_mc=max_mc,
            )

            if passes:
                would_alert.append(bull)
            else:
                would_miss.append(bull)

        total = len(recent)
        alerted = len(would_alert)

        if alerted > 0:
            avg_gain = sum(b["change_24h"] for b in would_alert) / alerted
        else:
            avg_gain = 0

        # Top 5 catches (les meilleurs qu'on aurait pris)
        top_5 = sorted(
            would_alert,
            key=lambda x: x["change_24h"],
            reverse=True
        )[:5]

        # Top 5 misses (les meilleurs qu'on aurait ratés)
        missed_5 = sorted(
            would_miss,
            key=lambda x: x["change_24h"],
            reverse=True
        )[:5]

        return {
            "total_bulls":  total,
            "would_alert":  alerted,
            "would_miss":   len(would_miss),
            "hit_rate":     round(alerted / total * 100, 1) if total > 0 else 0,
            "avg_gain":     round(avg_gain, 0),
            "top_5":        top_5,
            "missed_5":     missed_5,
            "params": {
                "min_score":     min_score,
                "min_liquidity": min_liquidity,
                "min_volume":    min_volume,
                "min_buy_ratio": min_buy_ratio,
                "max_mc":        max_mc,
                "days":          days,
            }
        }

    def _check_bull(
        self,
        bull: dict,
        min_liquidity: int,
        min_volume: int,
        min_buy_ratio: float,
        max_mc: int,
    ) -> bool:
        """Vérifie si un bull aurait passé les filtres"""

        # Filtre liquidité
        if bull.get("liquidity", 0) < min_liquidity:
            return False

        # Filtre volume
        if bull.get("volume_24h", 0) < min_volume:
            return False

        # Filtre buy ratio
        if bull.get("buy_ratio_1h", 0) < min_buy_ratio:
            return False

        # Filtre MC max
        if bull.get("market_cap", 0) > max_mc:
            return False

        return True

    def compare_configs(self, configs: list) -> list:
        """
        Compare plusieurs configurations.

        Exemple :
          configs = [
              {"name": "Actuel",    "min_liquidity": 5_000},
              {"name": "Aggressif", "min_liquidity": 1_000},
              {"name": "Safe",      "min_liquidity": 20_000},
          ]
        """
        results = []
        for cfg in configs:
            name = cfg.pop("name", "Config")
            res = self.backtest(**cfg)
            res["name"] = name
            results.append(res)

        return results