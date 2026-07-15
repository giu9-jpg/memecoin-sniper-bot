# modules/performance_tracker.py — v7.0
# Enregistre chaque alerte et mesure les performances

import json
import os
import time
from utils.logger import logger


DB_FILE = "data/performance.json"


class PerformanceTracker:

    def __init__(self):
        os.makedirs("data", exist_ok=True)
        self.trades = self._load()
        logger.info(
            f"[PERF] {len(self.trades)} trades chargés depuis l'historique"
        )

    def record_alert(self, token_data: dict, decision: dict):
        """Enregistre chaque alerte envoyée."""
        address = token_data.get("address", "")
        if not address:
            return

        self.trades[address] = {
            "address":       address,
            "symbol":        token_data.get("symbol", "???"),
            "name":          token_data.get("name", "Unknown"),
            "timestamp":     time.time(),
            "age_minutes":   token_data.get("age_minutes", 0),
            "score":         token_data.get("score", 0),
            "tier":          decision.get("tier", ""),
            "smart_count":   token_data.get("smart_count", 0),
            "has_critical":  token_data.get("has_critical", False),
            "price_entry":   token_data.get("price_usd", 0),
            "market_cap":    token_data.get("market_cap", 0),
            "liquidity":     token_data.get("liquidity", 0),
            "volume_5m":     token_data.get("volume_5m", 0),
            "volume_1h":     token_data.get("volume_1h", 0),
            "momentum":      token_data.get("momentum_signal", ""),
            "vol_accel":     token_data.get("vol_acceleration", 0),
            "ratio_5m":      token_data.get("ratio_buy_5m", 0),
            "alpha_wallets": token_data.get("alpha_wallets", 0),
            "amount_eur":    decision.get("amount_eur", 0),
            "tp_levels":     decision.get("tp_levels", []),
            "sl_pct":        decision.get("sl_pct", 0),
            "price_1h":       None,
            "price_6h":       None,
            "price_24h":      None,
            "multiplier_1h":  None,
            "multiplier_24h": None,
            "result":         None,
            "profit_eur":     None,
        }
        self._save()
        logger.info(
            f"[PERF] 📝 {token_data.get('symbol')} enregistré "
            f"(score {token_data.get('score')}/10)"
        )

    def update_result(
        self,
        address:       str,
        current_price: float,
        timeframe:     str = "1h"
    ):
        if address not in self.trades:
            return

        trade      = self.trades[address]
        entry      = trade.get("price_entry", 0)
        amount_eur = trade.get("amount_eur", 0)

        if not entry or entry == 0:
            return

        multiplier = current_price / entry

        if timeframe == "1h":
            trade["price_1h"]      = current_price
            trade["multiplier_1h"] = round(multiplier, 3)

        elif timeframe == "24h":
            trade["price_24h"]      = current_price
            trade["multiplier_24h"] = round(multiplier, 3)

            if multiplier >= 2.0:
                trade["result"]     = "WIN"
                trade["profit_eur"] = round(
                    amount_eur * multiplier - amount_eur, 2
                )
                logger.info(
                    f"[PERF] 🏆 WIN {trade['symbol']} : "
                    f"x{multiplier:.2f} (+{trade['profit_eur']}€)"
                )
            elif multiplier < 0.65:
                trade["result"]     = "LOSS"
                trade["profit_eur"] = round(
                    amount_eur * multiplier - amount_eur, 2
                )
                logger.info(
                    f"[PERF] 💀 LOSS {trade['symbol']} : "
                    f"x{multiplier:.2f} ({trade['profit_eur']}€)"
                )
            else:
                trade["result"]     = "NEUTRAL"
                trade["profit_eur"] = round(
                    amount_eur * multiplier - amount_eur, 2
                )

        self._save()

    def get_stats(self) -> dict:
        all_trades = list(self.trades.values())
        closed     = [t for t in all_trades if t.get("result")]
        wins       = [t for t in closed if t["result"] == "WIN"]
        losses     = [t for t in closed if t["result"] == "LOSS"]
        neutral    = [t for t in closed if t["result"] == "NEUTRAL"]

        win_rate = (
            len(wins) / len(closed) * 100
            if closed else 0
        )

        avg_mult = (
            sum(t.get("multiplier_24h", 1) or 1 for t in wins) / len(wins)
            if wins else 0
        )

        total_profit = sum(
            t.get("profit_eur", 0) or 0
            for t in closed
        )

        best = max(
            (t.get("multiplier_24h", 0) or 0 for t in closed),
            default=0
        )

        tier_stats = {}
        for tier in ["ULTIMATE", "STRONG", "GOOD", "NORMAL"]:
            tier_trades = [t for t in closed if t.get("tier") == tier]
            tier_wins   = [t for t in tier_trades if t["result"] == "WIN"]
            tier_stats[tier] = {
                "total": len(tier_trades),
                "wins":  len(tier_wins),
                "rate":  (
                    len(tier_wins) / len(tier_trades) * 100
                    if tier_trades else 0
                ),
            }

        return {
            "total_alerts":   len(all_trades),
            "closed_trades":  len(closed),
            "wins":           len(wins),
            "losses":         len(losses),
            "neutral":        len(neutral),
            "win_rate":       round(win_rate, 1),
            "avg_multiplier": round(avg_mult, 2),
            "total_profit":   round(total_profit, 2),
            "best_trade":     round(best, 2),
            "tier_stats":     tier_stats,
        }

    def get_summary_message(self) -> str:
        s = self.get_stats()

        tier_lines = ""
        for tier, data in s["tier_stats"].items():
            if data["total"] > 0:
                emoji = {
                    "ULTIMATE": "💎",
                    "STRONG":   "🔥",
                    "GOOD":     "✅",
                    "NORMAL":   "📊",
                }.get(tier, "⚪")
                tier_lines += (
                    f"  {emoji} {tier}: "
                    f"{data['wins']}/{data['total']} "
                    f"({data['rate']:.0f}%)\n"
                )

        if not tier_lines:
            tier_lines = "  Aucun trade fermé pour l'instant\n"

        profit_emoji = "📈" if s["total_profit"] >= 0 else "📉"

        return (
            f"📊 *PERFORMANCE BOT v7.0*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Alertes totales : {s['total_alerts']}\n"
            f"📋 Trades fermés   : {s['closed_trades']}\n"
            f"✅ Wins            : {s['wins']}\n"
            f"❌ Losses          : {s['losses']}\n"
            f"⚪ Neutres         : {s['neutral']}\n"
            f"📈 Win rate        : *{s['win_rate']}%*\n"
            f"🚀 Mult moyen      : *x{s['avg_multiplier']}*\n"
            f"🏆 Meilleur trade  : *x{s['best_trade']}*\n"
            f"{profit_emoji} Profit total     : *{s['total_profit']:+.1f}€*\n\n"
            f"📊 *PAR TIER :*\n"
            f"{tier_lines}"
        )

    def _load(self) -> dict:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logger.error(f"[PERF] Erreur load: {e}")
            return {}

    def _save(self):
        try:
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(self.trades, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[PERF] Erreur save: {e}")