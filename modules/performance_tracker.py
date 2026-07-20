# modules/performance_tracker.py — v7.1 FIXED FINAL
# FIX : get_stats() retourne les bonnes clés pour main.py _cmd_stats()
#       tier_stats exposé + raccourcis "ultimate/strong/good/normal"

import json
import os
import time
from utils.logger import logger

DB_FILE              = "data/performance.json"
MAX_TRADES_IN_MEMORY = 1000


class PerformanceTracker:

    def __init__(self):
        os.makedirs("data", exist_ok=True)
        self.trades       = self._load()
        self._dirty_count = 0
        self._save_every  = 10
        logger.info(
            f"[PERF] {len(self.trades)} trades chargés"
        )

    def record_alert(self, token_data: dict, decision: dict):
        """Enregistre chaque alerte envoyée."""
        address = token_data.get("address", "")
        if not address:
            return

        if address in self.trades:
            return

        self.trades[address] = {
            "address":        address,
            "symbol":         token_data.get("symbol", "???"),
            "name":           token_data.get("name", "Unknown"),
            "timestamp":      time.time(),
            "age_minutes":    token_data.get("age_minutes", 0),
            "score":          token_data.get("score", 0),
            "tier":           decision.get("tier", ""),
            "smart_count":    token_data.get("smart_count", 0),
            "has_critical":   token_data.get("has_critical", False),
            "price_entry":    token_data.get("price_usd", 0),
            "market_cap":     token_data.get("market_cap", 0),
            "liquidity":      token_data.get("liquidity", 0),
            "volume_5m":      token_data.get("volume_5m", 0),
            "volume_1h":      token_data.get("volume_1h", 0),
            "momentum":       token_data.get("momentum_signal", ""),
            "vol_accel":      token_data.get("vol_acceleration", 0),
            "ratio_5m":       token_data.get("ratio_buy_5m", 0),
            "alpha_wallets":  token_data.get("alpha_wallets", 0),
            "amount_eur":     decision.get("amount_eur", 0),
            "tp_levels":      decision.get("tp_levels", []),
            "sl_pct":         decision.get("sl_pct", 0),
            "price_1h":       None,
            "price_6h":       None,
            "price_24h":      None,
            "multiplier_1h":  None,
            "multiplier_24h": None,
            "result":         None,
            "profit_eur":     None,
        }

        self._dirty_count += 1
        if self._dirty_count >= self._save_every:
            self._save()
            self._dirty_count = 0

        self._cleanup_memory()

        logger.info(
            f"[PERF] 📝 {token_data.get('symbol')} enregistré "
            f"(score {token_data.get('score')}/10 | "
            f"tier {decision.get('tier')})"
        )

    def update_result(
        self,
        address:       str,
        current_price: float,
        timeframe:     str = "1h",
    ):
        """Met à jour le résultat d'un trade."""
        if address not in self.trades:
            return

        trade  = self.trades[address]
        entry  = trade.get("price_entry", 0)
        amount = trade.get("amount_eur", 0)

        if not entry or entry == 0:
            return

        multiplier = current_price / entry
        profit_eur = round(amount * multiplier - amount, 2)

        if timeframe == "1h":
            trade["price_1h"]      = current_price
            trade["multiplier_1h"] = round(multiplier, 3)
        elif timeframe == "6h":
            trade["price_6h"] = current_price
        elif timeframe == "24h":
            trade["price_24h"]      = current_price
            trade["multiplier_24h"] = round(multiplier, 3)
            trade["profit_eur"]     = profit_eur

            if multiplier >= 2.0:
                trade["result"] = "WIN"
            elif multiplier < 0.65:
                trade["result"] = "LOSS"
            else:
                trade["result"] = "NEUTRAL"

        self._save()

    def get_stats(self) -> dict:
        """
        Calcule les statistiques globales.
        FIX : expose tier_stats ET raccourcis directs pour main.py.
        """
        all_trades = list(self.trades.values())

        if not all_trades:
            return self._empty_stats()

        closed  = [t for t in all_trades if t.get("result")]
        wins    = [t for t in closed if t["result"] == "WIN"]
        losses  = [t for t in closed if t["result"] == "LOSS"]
        neutral = [t for t in closed if t["result"] == "NEUTRAL"]

        win_rate = (
            round(len(wins) / len(closed) * 100, 1) if closed else 0.0
        )
        avg_mult = (
            round(
                sum(t.get("multiplier_24h", 1) or 1 for t in wins)
                / len(wins), 2,
            )
            if wins else 0.0
        )
        total_profit = sum(t.get("profit_eur") or 0 for t in closed)
        best = max(
            (t.get("multiplier_24h") or 0 for t in closed), default=0
        )

        # Stats par tier
        tier_stats = {}
        for tier in ["ULTIMATE", "STRONG", "GOOD", "NORMAL"]:
            tier_trades = [t for t in closed if t.get("tier") == tier]
            tier_wins   = [t for t in tier_trades if t["result"] == "WIN"]
            tier_stats[tier] = {
                "total": len(tier_trades),
                "wins":  len(tier_wins),
                "rate":  (
                    round(len(tier_wins) / len(tier_trades) * 100, 1)
                    if tier_trades else 0.0
                ),
            }

        return {
            "total_alerts":   len(all_trades),
            "closed_trades":  len(closed),
            "wins":           len(wins),
            "losses":         len(losses),
            "neutral":        len(neutral),
            "win_rate":       win_rate,
            "avg_multiplier": avg_mult,
            "total_profit":   round(total_profit, 2),
            "best_trade":     round(best, 2),
            "tier_stats":     tier_stats,
            # FIX : raccourcis directs pour _cmd_stats() dans main.py
            "ultimate":       tier_stats["ULTIMATE"]["total"],
            "strong":         tier_stats["STRONG"]["total"],
            "good":           tier_stats["GOOD"]["total"],
            "normal":         tier_stats["NORMAL"]["total"],
        }

    def _empty_stats(self) -> dict:
        tier_stats = {
            tier: {"total": 0, "wins": 0, "rate": 0.0}
            for tier in ["ULTIMATE", "STRONG", "GOOD", "NORMAL"]
        }
        return {
            "total_alerts":   0,
            "closed_trades":  0,
            "wins":           0,
            "losses":         0,
            "neutral":        0,
            "win_rate":       0.0,
            "avg_multiplier": 0.0,
            "total_profit":   0.0,
            "best_trade":     0.0,
            "tier_stats":     tier_stats,
            "ultimate":       0,
            "strong":         0,
            "good":           0,
            "normal":         0,
        }

    def get_summary_message(self) -> str:
        """Message Telegram rapport."""
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
            tier_lines = "  Aucun trade fermé\n"

        profit_emoji = "📈" if s["total_profit"] >= 0 else "📉"
        win_rate_str = (
            f"{s['win_rate']:.1f}%"
            if s["closed_trades"] > 0 else "N/A"
        )
        avg_mult_str = (
            f"x{s['avg_multiplier']:.2f}"
            if s["avg_multiplier"] > 0 else "N/A"
        )
        best_str = (
            f"x{s['best_trade']:.2f}"
            if s["best_trade"] > 0 else "N/A"
        )

        return (
            f"📊 *PERFORMANCE BOT v7.1*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 Alertes totales : *{s['total_alerts']}*\n"
            f"📋 Trades fermés   : *{s['closed_trades']}*\n"
            f"✅ Wins            : *{s['wins']}*\n"
            f"❌ Losses          : *{s['losses']}*\n"
            f"⚪ Neutres         : *{s['neutral']}*\n"
            f"📈 Win rate        : *{win_rate_str}*\n"
            f"🚀 Mult moyen      : *{avg_mult_str}*\n"
            f"🏆 Meilleur trade  : *{best_str}*\n"
            f"{profit_emoji} Profit total : "
            f"*{s['total_profit']:+.1f}€*\n\n"
            f"📊 *PAR TIER :*\n"
            f"{tier_lines}"
        )

    def _cleanup_memory(self):
        if len(self.trades) <= MAX_TRADES_IN_MEMORY:
            return

        all_items     = list(self.trades.items())
        open_trades   = [(k, v) for k, v in all_items if not v.get("result")]
        closed_trades = [(k, v) for k, v in all_items if v.get("result")]
        closed_trades.sort(key=lambda x: x[1].get("timestamp", 0))

        keep_closed = max(0, MAX_TRADES_IN_MEMORY - len(open_trades) - 100)
        kept_closed = closed_trades[-keep_closed:] if keep_closed > 0 else []
        self.trades  = dict(open_trades + kept_closed)

    def flush(self):
        """Force la sauvegarde (appelé au shutdown)."""
        if self._dirty_count > 0:
            self._save()
            self._dirty_count = 0
            logger.info("[PERF] 💾 Sauvegarde forcée")

    def _load(self) -> dict:
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return {}
                return data
        except FileNotFoundError:
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"[PERF] JSON corrompu: {e} → reset")
            self._backup_corrupted()
            return {}
        except Exception as e:
            logger.error(f"[PERF] Erreur load: {e}")
            return {}

    def _save(self):
        try:
            tmp_file = DB_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.trades, f, indent=2, ensure_ascii=False)
            os.replace(tmp_file, DB_FILE)
        except Exception as e:
            logger.error(f"[PERF] Erreur save: {e}")

    def _backup_corrupted(self):
        try:
            if os.path.exists(DB_FILE):
                backup = DB_FILE.replace(
                    ".json",
                    f"_corrupted_{int(time.time())}.json",
                )
                os.rename(DB_FILE, backup)
        except Exception:
            pass