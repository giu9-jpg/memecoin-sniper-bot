# modules/backtester_v2.py v2.0
"""
Backtester v2 - Simulation réaliste
Simule des stratégies complètes avec :
  - Entry price
  - Multiple TP levels (partial sells)
  - Stop Loss
  - Calcul PnL final
  - Comparaison stratégies

Utilise l'historique des bulls détectés (BullRunAnalyzer).
"""

from datetime import datetime, timezone
import time
from utils.logger import get_logger

logger = get_logger("backtester_v2")


class BacktesterV2:

    # ════════════════════════════════════════
    # STRATÉGIES PRÉ-DÉFINIES
    # ════════════════════════════════════════

    STRATEGIES = {
        "CONSERVATIVE": {
            "name": "Conservative",
            "description": "Sécurise vite, petits gains stables",
            "tp_levels": [
                {"multiplier": 1.5, "sell_pct": 40},
                {"multiplier": 2.0, "sell_pct": 30},
                {"multiplier": 3.0, "sell_pct": 20},
                {"multiplier": 5.0, "sell_pct": 10},
            ],
            "sl_pct": -20,
        },
        "BALANCED": {
            "name": "Balanced",
            "description": "Équilibre risque/reward",
            "tp_levels": [
                {"multiplier": 2.0, "sell_pct": 25},
                {"multiplier": 3.5, "sell_pct": 25},
                {"multiplier": 6.0, "sell_pct": 25},
                {"multiplier": 10.0, "sell_pct": 25},
            ],
            "sl_pct": -30,
        },
        "AGGRESSIVE": {
            "name": "Aggressive",
            "description": "Va chercher les moonshots",
            "tp_levels": [
                {"multiplier": 3.0, "sell_pct": 20},
                {"multiplier": 5.0, "sell_pct": 20},
                {"multiplier": 10.0, "sell_pct": 30},
                {"multiplier": 25.0, "sell_pct": 30},
            ],
            "sl_pct": -40,
        },
        "MOONSHOT": {
            "name": "Moonshot",
            "description": "All-in sur les x100",
            "tp_levels": [
                {"multiplier": 5.0, "sell_pct": 20},
                {"multiplier": 20.0, "sell_pct": 30},
                {"multiplier": 50.0, "sell_pct": 30},
                {"multiplier": 100.0, "sell_pct": 20},
            ],
            "sl_pct": -50,
        },
    }

    def __init__(self, bull_analyzer):
        """
        bull_analyzer : instance de BullRunAnalyzer
        """
        self.bull_analyzer = bull_analyzer

    # ════════════════════════════════════════
    # SIMULATION D'UNE STRATÉGIE
    # ════════════════════════════════════════

    def simulate_strategy(
        self,
        strategy_name: str = "BALANCED",
        min_liquidity: int = 5_000,
        min_volume: int = 100_000,
        min_buy_ratio: float = 55,
        entry_amount: float = 10,  # Montant en € par trade
        days: int = 30,
    ) -> dict:
        """
        Simule une stratégie sur les bulls historiques.

        Retourne :
          - total_trades
          - wins / losses
          - win_rate
          - total_pnl_eur
          - roi_pct
          - avg_gain
          - best_trade / worst_trade
          - detailed_trades
        """
        strategy = self.STRATEGIES.get(strategy_name.upper())
        if not strategy:
            return {"error": f"Stratégie {strategy_name} inconnue"}

        bulls = self.bull_analyzer.bulls

        if not bulls:
            return {
                "total_trades": 0,
                "message": "Pas de bulls dans l'historique",
            }

        # Filtre par période
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
                "total_trades": 0,
                "message": f"Pas de bulls dans les {days} derniers jours",
            }

        # Filtres qualité
        filtered = []
        for bull in recent:
            if bull.get("liquidity", 0) < min_liquidity:
                continue
            if bull.get("volume_24h", 0) < min_volume:
                continue
            if bull.get("buy_ratio_1h", 0) < min_buy_ratio:
                continue
            filtered.append(bull)

        if not filtered:
            return {
                "total_trades": 0,
                "message": "Aucun bull ne passe les filtres",
            }

        # Simulation trade par trade
        detailed_trades = []
        total_pnl_eur = 0
        wins = 0
        losses = 0

        for bull in filtered:
            trade_result = self._simulate_single_trade(
                bull=bull,
                strategy=strategy,
                entry_amount=entry_amount,
            )
            detailed_trades.append(trade_result)
            total_pnl_eur += trade_result["pnl_eur"]

            if trade_result["pnl_eur"] > 0:
                wins += 1
            else:
                losses += 1

        total_trades = len(detailed_trades)
        total_invested = total_trades * entry_amount
        roi_pct = (total_pnl_eur / total_invested * 100) if total_invested > 0 else 0
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        avg_pnl_pct = sum(t["pnl_pct"] for t in detailed_trades) / total_trades if total_trades > 0 else 0

        # Best & worst
        best = max(detailed_trades, key=lambda x: x["pnl_pct"])
        worst = min(detailed_trades, key=lambda x: x["pnl_pct"])

        # Détail des TP touchés
        tp_hits = {"TP1": 0, "TP2": 0, "TP3": 0, "TP4": 0}
        sl_hits = 0
        for t in detailed_trades:
            for tp in t.get("tps_hit", []):
                tp_hits[tp] = tp_hits.get(tp, 0) + 1
            if t.get("sl_hit"):
                sl_hits += 1

        return {
            "strategy_name":    strategy["name"],
            "strategy_desc":    strategy["description"],
            "total_trades":     total_trades,
            "wins":             wins,
            "losses":           losses,
            "win_rate":         round(win_rate, 1),
            "total_invested":   round(total_invested, 2),
            "total_pnl_eur":    round(total_pnl_eur, 2),
            "roi_pct":          round(roi_pct, 1),
            "avg_pnl_pct":      round(avg_pnl_pct, 1),
            "best_trade":       best,
            "worst_trade":      worst,
            "tp_hits":          tp_hits,
            "sl_hits":          sl_hits,
            "detailed_trades":  detailed_trades[:20],  # Sample
            "params": {
                "min_liquidity":  min_liquidity,
                "min_volume":     min_volume,
                "min_buy_ratio":  min_buy_ratio,
                "entry_amount":   entry_amount,
                "days":           days,
            },
        }

    def _simulate_single_trade(
        self,
        bull: dict,
        strategy: dict,
        entry_amount: float,
    ) -> dict:
        """
        Simule un trade unique avec la stratégie donnée.

        Logique :
          - Entry au prix estimé de démarrage (mc_estimated_start)
          - Vise le peak (change_24h max)
          - Calcule combien de TPs auraient été touchés
          - Applique SL si drop trop important
        """
        symbol = bull.get("symbol", "?")
        mint = bull.get("mint", "")
        peak_gain_pct = bull.get("change_24h", 0)  # Gain max atteint

        # Estimation drawdown (chute depuis peak)
        # Approximation basée sur les données du bull
        change_5m = bull.get("change_5m", 0) or 0
        change_1h = bull.get("change_1h", 0) or 0
        change_6h = bull.get("change_6h", 0) or 0

        # Si le token est déjà en train de dumper au moment du snapshot
        current_drawdown_pct = 0
        if change_5m < 0 and change_1h < 0:
            current_drawdown_pct = min(change_5m, change_1h)

        # Simulation des TPs
        tps_hit = []
        remaining_pct = 100  # % de la position encore ouverte
        realized_pnl_pct = 0  # PnL réalisé par les TPs

        for i, tp in enumerate(strategy["tp_levels"], 1):
            tp_gain_pct = (tp["multiplier"] - 1) * 100

            if peak_gain_pct >= tp_gain_pct:
                # TP touché
                tps_hit.append(f"TP{i}")
                sold_pct = tp["sell_pct"]
                realized_pnl_pct += (sold_pct / 100) * tp_gain_pct
                remaining_pct -= sold_pct

        # Simulation SL sur la position restante
        sl_hit = False
        sl_loss_pct = 0

        if remaining_pct > 0 and current_drawdown_pct <= strategy["sl_pct"]:
            sl_hit = True
            sl_loss_pct = (remaining_pct / 100) * strategy["sl_pct"]

        # Si pas de SL ni de TP4, on estime qu'on garde la position au peak
        # (approximation : on prend un pourcentage du peak)
        if remaining_pct > 0 and not sl_hit:
            # On considère qu'on sort à 50% du peak si pas de TP touché
            # ou au peak si TP touchés
            if tps_hit:
                # Reste vendu au peak (simplification)
                realized_pnl_pct += (remaining_pct / 100) * peak_gain_pct * 0.7
            else:
                # Pas de TP touché, exit à 30% du peak
                realized_pnl_pct += (remaining_pct / 100) * peak_gain_pct * 0.3

        # PnL final en euros
        final_pnl_pct = realized_pnl_pct + sl_loss_pct
        pnl_eur = entry_amount * (final_pnl_pct / 100)

        return {
            "symbol":         symbol,
            "mint":           mint,
            "peak_gain":      peak_gain_pct,
            "entry_amount":   entry_amount,
            "pnl_pct":        round(final_pnl_pct, 1),
            "pnl_eur":        round(pnl_eur, 2),
            "tps_hit":        tps_hit,
            "sl_hit":         sl_hit,
            "sl_loss_pct":    round(sl_loss_pct, 1),
            "remaining_pct":  remaining_pct,
        }

    # ════════════════════════════════════════
    # COMPARAISON DE STRATÉGIES
    # ════════════════════════════════════════

    def compare_strategies(
        self,
        strategies: list = None,
        entry_amount: float = 10,
        days: int = 30,
    ) -> dict:
        """Compare plusieurs stratégies"""
        if strategies is None:
            strategies = ["CONSERVATIVE", "BALANCED", "AGGRESSIVE", "MOONSHOT"]

        results = []
        for strat_name in strategies:
            result = self.simulate_strategy(
                strategy_name=strat_name,
                entry_amount=entry_amount,
                days=days,
            )
            results.append(result)

        # Trouve la meilleure par ROI
        valid_results = [r for r in results if r.get("total_trades", 0) > 0]

        if not valid_results:
            return {
                "error": "Pas assez de données pour comparer",
                "results": results,
            }

        best_by_roi = max(valid_results, key=lambda x: x.get("roi_pct", 0))
        best_by_winrate = max(valid_results, key=lambda x: x.get("win_rate", 0))

        return {
            "results": results,
            "best_by_roi": best_by_roi["strategy_name"],
            "best_by_winrate": best_by_winrate["strategy_name"],
            "period_days": days,
            "entry_amount": entry_amount,
        }

    # ════════════════════════════════════════
    # STRATÉGIE CUSTOM
    # ════════════════════════════════════════

    def simulate_custom(
        self,
        tp_levels: list,
        sl_pct: float,
        entry_amount: float = 10,
        days: int = 30,
        strategy_name: str = "CUSTOM",
    ) -> dict:
        """
        Simule une stratégie personnalisée.

        Exemple :
          tp_levels = [
              {"multiplier": 2, "sell_pct": 50},
              {"multiplier": 5, "sell_pct": 50},
          ]
          sl_pct = -25
        """
        # Ajoute temporairement la stratégie custom
        self.STRATEGIES["CUSTOM"] = {
            "name": strategy_name,
            "description": "Stratégie personnalisée",
            "tp_levels": tp_levels,
            "sl_pct": sl_pct,
        }

        result = self.simulate_strategy(
            strategy_name="CUSTOM",
            entry_amount=entry_amount,
            days=days,
        )

        return result

    def get_available_strategies(self) -> dict:
        """Retourne la liste des stratégies disponibles"""
        return {
            name: {
                "description": s["description"],
                "tp_count": len(s["tp_levels"]),
                "sl_pct": s["sl_pct"],
            }
            for name, s in self.STRATEGIES.items()
            if name != "CUSTOM"
        }