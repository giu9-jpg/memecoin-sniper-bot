# modules/performance_tracker.py — v7.1 FIXED
# Corrections :
# - Ne pas écraser un trade existant
# - Sauvegarde différée (toutes les 10 écritures)
# - Nettoyage mémoire automatique
# - get_stats() robuste même sans trades
# - get_summary_message() ne crashe plus si vide

import json
import os
import time
from utils.logger import logger


DB_FILE  = "data/performance.json"
MAX_TRADES_IN_MEMORY = 1000   # au-delà, on purge les plus vieux


class PerformanceTracker:

    def __init__(self):
        os.makedirs("data", exist_ok=True)
        self.trades        = self._load()
        self._dirty_count  = 0          # compteur écritures en attente
        self._save_every   = 10         # sauvegarde tous les 10 nouveaux trades
        logger.info(
            f"[PERF] {len(self.trades)} trades chargés depuis l'historique"
        )

    # ═══════════════════════════════════════════════════
    # ENREGISTREMENT
    # ═══════════════════════════════════════════════════

    def record_alert(self, token_data: dict, decision: dict):
        """
        Enregistre chaque alerte envoyée.
        FIX : ne jamais écraser un trade déjà existant.
        FIX : sauvegarde différée pour éviter I/O trop fréquent.
        """
        address = token_data.get("address", "")
        if not address:
            return

        # ── FIX : ne pas écraser un trade existant ────
        if address in self.trades:
            logger.debug(
                f"[PERF] {token_data.get('symbol')} déjà enregistré, "
                f"skip"
            )
            return

        self.trades[address] = {
            # Identité
            "address":        address,
            "symbol":         token_data.get("symbol", "???"),
            "name":           token_data.get("name", "Unknown"),
            "timestamp":      time.time(),

            # Métriques au moment de l'alerte
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

            # Décision
            "amount_eur":     decision.get("amount_eur", 0),
            "tp_levels":      decision.get("tp_levels", []),
            "sl_pct":         decision.get("sl_pct", 0),

            # Résultats — remplis plus tard par update_result()
            "price_1h":       None,
            "price_6h":       None,
            "price_24h":      None,
            "multiplier_1h":  None,
            "multiplier_24h": None,
            "result":         None,
            "profit_eur":     None,
        }

        # ── FIX : sauvegarde différée ──────────────────
        self._dirty_count += 1
        if self._dirty_count >= self._save_every:
            self._save()
            self._dirty_count = 0

        # ── Nettoyage mémoire si trop de trades ────────
        self._cleanup_memory()

        logger.info(
            f"[PERF] 📝 {token_data.get('symbol')} enregistré "
            f"(score {token_data.get('score')}/10 | "
            f"tier {decision.get('tier')})"
        )

    # ═══════════════════════════════════════════════════
    # MISE À JOUR RÉSULTAT
    # ═══════════════════════════════════════════════════

    def update_result(
        self,
        address:       str,
        current_price: float,
        timeframe:     str = "1h",
    ):
        """Met à jour le résultat d'un trade après x heures."""
        if address not in self.trades:
            return

        trade      = self.trades[address]
        entry      = trade.get("price_entry", 0)
        amount_eur = trade.get("amount_eur", 0)

        # ── FIX : protection division par zéro ────────
        if not entry or entry == 0:
            logger.debug(f"[PERF] Prix entrée = 0 pour {address[:8]}, skip")
            return

        multiplier = current_price / entry
        profit_eur = round(amount_eur * multiplier - amount_eur, 2)

        if timeframe == "1h":
            trade["price_1h"]      = current_price
            trade["multiplier_1h"] = round(multiplier, 3)

        elif timeframe == "6h":
            trade["price_6h"] = current_price

        elif timeframe == "24h":
            trade["price_24h"]      = current_price
            trade["multiplier_24h"] = round(multiplier, 3)
            trade["profit_eur"]     = profit_eur

            # ── Décision WIN / LOSS / NEUTRAL ─────────
            if multiplier >= 2.0:
                trade["result"] = "WIN"
                logger.info(
                    f"[PERF] 🏆 WIN {trade['symbol']} : "
                    f"x{multiplier:.2f} (+{profit_eur}€)"
                )
            elif multiplier < 0.65:
                trade["result"] = "LOSS"
                logger.info(
                    f"[PERF] 💀 LOSS {trade['symbol']} : "
                    f"x{multiplier:.2f} ({profit_eur}€)"
                )
            else:
                trade["result"] = "NEUTRAL"
                logger.info(
                    f"[PERF] ⚪ NEUTRAL {trade['symbol']} : "
                    f"x{multiplier:.2f} ({profit_eur}€)"
                )

        # Sauvegarde immédiate sur update (important)
        self._save()

    # ═══════════════════════════════════════════════════
    # STATISTIQUES
    # ═══════════════════════════════════════════════════

    def get_stats(self) -> dict:
        """
        Calcule les statistiques globales.
        FIX : toujours retourner un dict valide même si vide.
        """
        all_trades = list(self.trades.values())

        # ── FIX : protection si aucun trade ───────────
        if not all_trades:
            return self._empty_stats()

        closed  = [t for t in all_trades if t.get("result")]
        wins    = [t for t in closed if t["result"] == "WIN"]
        losses  = [t for t in closed if t["result"] == "LOSS"]
        neutral = [t for t in closed if t["result"] == "NEUTRAL"]

        win_rate = (
            round(len(wins) / len(closed) * 100, 1)
            if closed else 0.0
        )

        avg_mult = (
            round(
                sum(t.get("multiplier_24h", 1) or 1 for t in wins)
                / len(wins),
                2,
            )
            if wins else 0.0
        )

        # ── FIX : protection None dans profit ─────────
        total_profit = sum(
            t.get("profit_eur") or 0
            for t in closed
        )

        best = max(
            (t.get("multiplier_24h") or 0 for t in closed),
            default=0,
        )

        # ── Stats par tier ────────────────────────────
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
        }

    def _empty_stats(self) -> dict:
        """Stats vides pour éviter les crashes au démarrage."""
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
            "tier_stats": {
                tier: {"total": 0, "wins": 0, "rate": 0.0}
                for tier in ["ULTIMATE", "STRONG", "GOOD", "NORMAL"]
            },
        }

    # ═══════════════════════════════════════════════════
    # MESSAGE RAPPORT
    # ═══════════════════════════════════════════════════

    def get_summary_message(self) -> str:
        """
        Message Telegram rapport.
        FIX : ne crashe plus si aucun trade.
        """
        s = self.get_stats()

        # ── Lignes par tier ───────────────────────────
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

        # ── FIX : win_rate affiché proprement ─────────
        win_rate_str = (
            f"{s['win_rate']:.1f}%"
            if s["closed_trades"] > 0
            else "N/A"
        )

        avg_mult_str = (
            f"x{s['avg_multiplier']:.2f}"
            if s["avg_multiplier"] > 0
            else "N/A"
        )

        best_str = (
            f"x{s['best_trade']:.2f}"
            if s["best_trade"] > 0
            else "N/A"
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
            f"{profit_emoji} Profit total     : "
            f"*{s['total_profit']:+.1f}€*\n\n"
            f"📊 *PAR TIER :*\n"
            f"{tier_lines}"
        )

    # ═══════════════════════════════════════════════════
    # NETTOYAGE MÉMOIRE
    # ═══════════════════════════════════════════════════

    def _cleanup_memory(self):
        """
        FIX : évite la croissance infinie de self.trades.
        Garde les MAX_TRADES_IN_MEMORY trades les plus récents.
        Priorité : garder les trades non fermés (en cours).
        """
        if len(self.trades) <= MAX_TRADES_IN_MEMORY:
            return

        all_items = list(self.trades.items())

        # Sépare ouverts et fermés
        open_trades   = [(k, v) for k, v in all_items if not v.get("result")]
        closed_trades = [(k, v) for k, v in all_items if v.get("result")]

        # Trie les fermés par timestamp (les plus vieux d'abord)
        closed_trades.sort(key=lambda x: x[1].get("timestamp", 0))

        # Nombre de fermés à garder
        keep_closed = max(
            0,
            MAX_TRADES_IN_MEMORY - len(open_trades) - 100
        )

        kept_closed = closed_trades[-keep_closed:] if keep_closed > 0 else []

        self.trades = dict(open_trades + kept_closed)

        logger.info(
            f"[PERF] 🧹 Nettoyage : "
            f"{len(open_trades)} ouverts + "
            f"{len(kept_closed)} fermés gardés"
        )

    # ═══════════════════════════════════════════════════
    # SAUVEGARDE FORCÉE
    # ═══════════════════════════════════════════════════

    def flush(self):
        """Forcer la sauvegarde (appelé au shutdown)."""
        if self._dirty_count > 0:
            self._save()
            self._dirty_count = 0
            logger.info("[PERF] 💾 Sauvegarde forcée")

    # ═══════════════════════════════════════════════════
    # I/O JSON
    # ═══════════════════════════════════════════════════

    def _load(self) -> dict:
        """Charge les trades depuis le fichier JSON."""
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # ── FIX : vérifie que c'est bien un dict ──
                if not isinstance(data, dict):
                    logger.warning("[PERF] Fichier corrompu, reset")
                    return {}
                return data
        except FileNotFoundError:
            logger.info("[PERF] Pas d'historique, démarrage à zéro")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"[PERF] JSON corrompu: {e} → reset")
            # Backup du fichier corrompu
            self._backup_corrupted()
            return {}
        except Exception as e:
            logger.error(f"[PERF] Erreur load: {e}")
            return {}

    def _save(self):
        """Sauvegarde les trades dans le fichier JSON."""
        try:
            # Écriture atomique via fichier temp
            tmp_file = DB_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.trades, f, indent=2, ensure_ascii=False)
            # Remplace l'original seulement si l'écriture a réussi
            os.replace(tmp_file, DB_FILE)
        except Exception as e:
            logger.error(f"[PERF] Erreur save: {e}")

    def _backup_corrupted(self):
        """Sauvegarde le fichier JSON corrompu avant reset."""
        try:
            if os.path.exists(DB_FILE):
                backup = DB_FILE.replace(".json", f"_corrupted_{int(time.time())}.json")
                os.rename(DB_FILE, backup)
                logger.warning(f"[PERF] Backup corrompu : {backup}")
        except Exception:
            pass