# modules/csv_exporter.py v1.0
"""
CSV Exporter + Rapports quotidiens
- Export CSV de toutes les données (alerts, bulls, trades, portfolio)
- Rapport quotidien automatique envoyé sur Telegram
- Statistiques journalières / hebdomadaires

Fichiers générés dans data/exports/ :
  - alerts_YYYY-MM-DD.csv
  - bulls_YYYY-MM-DD.csv
  - trades_YYYY-MM-DD.csv
  - portfolio_YYYY-MM-DD.csv
  - dump_alerts_YYYY-MM-DD.csv
"""

import asyncio
import csv
import os
import time
from datetime import datetime, timezone, timedelta
from utils.logger import get_logger

logger = get_logger("csv_exporter")


class CSVExporter:

    EXPORT_DIR = "data/exports"

    # Cycle rapport quotidien (24h)
    DAILY_REPORT_INTERVAL = 86400

    def __init__(
        self,
        alert_sender=None,
        perf_tracker=None,
        bull_analyzer=None,
        portfolio_tracker=None,
        ml_scorer=None,
        wallet_discovery=None,
    ):
        self.alert_sender      = alert_sender
        self.perf_tracker      = perf_tracker
        self.bull_analyzer     = bull_analyzer
        self.portfolio_tracker = portfolio_tracker
        self.ml_scorer         = ml_scorer
        self.wallet_discovery  = wallet_discovery

        self.running = False

        # Tracking pour rapports
        self.last_daily_report = 0

        # Snapshot du jour précédent (pour deltas)
        self.yesterday_snapshot = {
            "alerts_sent":     0,
            "tokens_analyzed": 0,
            "momentum_alerts": 0,
            "sell_alerts":     0,
            "bulls_detected":  0,
        }

        # Stats
        self.total_reports_sent = 0
        self.total_exports = 0

        os.makedirs(self.EXPORT_DIR, exist_ok=True)

    async def start(self):
        """Démarre le reporter quotidien"""
        self.running = True
        logger.info(
            f"📊 CSVExporter démarré "
            f"(rapport quotidien toutes les 24h)"
        )
        asyncio.create_task(self._daily_report_loop())

    async def stop(self):
        """Arrêt propre"""
        self.running = False
        logger.info("📊 CSVExporter arrêté")

    # ════════════════════════════════════════
    # BOUCLE RAPPORT QUOTIDIEN
    # ════════════════════════════════════════

    async def _daily_report_loop(self):
        """Envoie un rapport quotidien à minuit UTC"""
        # Attente initiale (1h avant premier rapport)
        await asyncio.sleep(3600)

        while self.running:
            try:
                await self._generate_daily_report()
                await self._export_all_csv()
            except Exception as e:
                logger.error(f"Daily report error : {e}")

            await asyncio.sleep(self.DAILY_REPORT_INTERVAL)

    async def _generate_daily_report(self):
        """Génère et envoie le rapport quotidien Telegram"""
        try:
            if not self.alert_sender:
                logger.warning("Pas d'alert_sender pour le rapport")
                return

            # Récupère les stats
            bot = self._get_bot_stats()

            # Calcule les deltas
            delta_alerts   = bot.get("alerts_sent", 0) - self.yesterday_snapshot["alerts_sent"]
            delta_analyzed = bot.get("tokens_analyzed", 0) - self.yesterday_snapshot["tokens_analyzed"]
            delta_momentum = bot.get("momentum_alerts", 0) - self.yesterday_snapshot["momentum_alerts"]
            delta_sells    = bot.get("sell_alerts", 0) - self.yesterday_snapshot["sell_alerts"]

            # Bulls
            bulls_data = {}
            if self.bull_analyzer:
                bulls_data = self.bull_analyzer.get_stats(days=1)

            # ML stats
            ml_data = {}
            if self.ml_scorer:
                ml_data = self.ml_scorer.get_stats()

            # Portfolio
            portfolio_data = {}
            pnl_data = {}
            if self.portfolio_tracker:
                portfolio_data = self.portfolio_tracker.get_portfolio_summary()
                pnl_data = self.portfolio_tracker.get_pnl_by_period()

            # Wallet discovery
            wd_data = {}
            if self.wallet_discovery:
                wd_data = self.wallet_discovery.get_stats()

            # Construction du message
            date_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

            lines = [
                "📊 *RAPPORT QUOTIDIEN*",
                f"📅 `{date_str}`",
                "━━━━━━━━━━━━━━",
                "",
                "🤖 *ACTIVITÉ 24H :*",
                f"  Tokens analysés : `{delta_analyzed:,}`",
                f"  Alertes envoyées : `{delta_alerts}`",
                f"  Alertes momentum : `{delta_momentum}`",
                f"  Sell alerts : `{delta_sells}`",
                "",
            ]

            # Section Bulls
            if bulls_data.get("total", 0) > 0:
                lines.append("🎯 *BULLS DÉTECTÉS \\(24h\\) :*")
                lines.append(f"  Total : `{bulls_data['total']}`")
                lines.append(f"  Gain moyen : `\\+{bulls_data.get('avg_gain', 0):.0f}%`")

                if bulls_data.get("top_5"):
                    top1 = bulls_data["top_5"][0]
                    lines.append(
                        f"  🏆 Meilleur : ${self._esc(top1['symbol'])} "
                        f"\\+{top1['change_24h']:.0f}%"
                    )
                lines.append("")

            # Section Portfolio
            if portfolio_data.get("total_trades", 0) > 0:
                pnl_day = pnl_data.get("pnl_day", 0)
                pnl_emoji = "📈" if pnl_day >= 0 else "📉"
                pnl_sign = "\\+" if pnl_day >= 0 else ""

                lines.append("💼 *PORTFOLIO :*")
                lines.append(
                    f"  {pnl_emoji} PnL 24h : "
                    f"`{pnl_sign}{pnl_day:.2f}€`"
                )
                lines.append(
                    f"  Positions ouvertes : `{portfolio_data['open_positions']}`"
                )
                lines.append(
                    f"  Wins/Losses : `{pnl_data.get('wins_day', 0)}`/`{pnl_data.get('losses_day', 0)}`"
                )
                lines.append("")

            # Section ML
            if ml_data.get("trades", 0) > 0:
                lines.append("🧠 *MACHINE LEARNING :*")
                lines.append(f"  Total trades : `{ml_data['trades']}`")
                lines.append(f"  Win rate : `{ml_data.get('win_rate', 0):.1f}%`")
                lines.append(f"  PnL moyen : `{ml_data.get('avg_pnl', 0):+.0f}%`")
                lines.append("")

            # Section Wallet Discovery
            if wd_data.get("wallets_tracked", 0) > 0:
                lines.append("🔍 *WALLET DISCOVERY :*")
                lines.append(f"  Wallets trackés : `{wd_data['wallets_tracked']}`")
                lines.append(f"  Candidats : `{wd_data['candidates_ready']}`")
                lines.append("")

            # Fichiers exportés
            lines.append("━━━━━━━━━━━━━━")
            lines.append("📁 *CSV EXPORTÉS :*")
            lines.append("`data/exports/`")
            lines.append("  • alerts\\_YYYY\\-MM\\-DD\\.csv")
            lines.append("  • bulls\\_YYYY\\-MM\\-DD\\.csv")
            lines.append("  • trades\\_YYYY\\-MM\\-DD\\.csv")
            lines.append("  • portfolio\\_YYYY\\-MM\\-DD\\.csv")
            lines.append("")
            lines.append(f"⏰ Prochain rapport dans 24h")

            msg = "\n".join(lines)

            await self.alert_sender._send_telegram(msg)

            # Mise à jour du snapshot
            self.yesterday_snapshot = {
                "alerts_sent":     bot.get("alerts_sent", 0),
                "tokens_analyzed": bot.get("tokens_analyzed", 0),
                "momentum_alerts": bot.get("momentum_alerts", 0),
                "sell_alerts":     bot.get("sell_alerts", 0),
                "bulls_detected":  bulls_data.get("total", 0),
            }

            self.total_reports_sent += 1
            self.last_daily_report = time.time()

            logger.info(
                f"📊 Rapport quotidien envoyé "
                f"(#{self.total_reports_sent})"
            )

        except Exception as e:
            logger.error(f"Generate daily report error : {e}", exc_info=True)

    def _get_bot_stats(self) -> dict:
        """Récupère les stats globales du bot"""
        if not self.perf_tracker:
            return {}
        try:
            return self.perf_tracker.get_stats() or {}
        except Exception:
            return {}

    # ════════════════════════════════════════
    # EXPORTS CSV
    # ════════════════════════════════════════

    async def _export_all_csv(self):
        """Exporte tous les CSVs de la journée"""
        try:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            # Export bulls
            await self.export_bulls_csv(date_str)

            # Export trades
            await self.export_trades_csv(date_str)

            # Export portfolio
            await self.export_portfolio_csv(date_str)

            # Export ML data
            await self.export_ml_csv(date_str)

            # Export wallet candidates
            await self.export_candidates_csv(date_str)

            logger.info(f"📊 Exports CSV terminés pour {date_str}")

        except Exception as e:
            logger.error(f"Export all CSV error : {e}")

    async def export_bulls_csv(self, date_str: str = None) -> str:
        """Exporte les bulls détectés"""
        try:
            if not self.bull_analyzer:
                return None

            if date_str is None:
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            filepath = os.path.join(
                self.EXPORT_DIR, f"bulls_{date_str}.csv"
            )

            bulls = self.bull_analyzer.bulls
            if not bulls:
                return None

            with open(filepath, "w", newline="", encoding="utf-8") as f:
                fieldnames = [
                    "detected_at", "symbol", "name", "mint",
                    "change_24h", "change_6h", "change_1h",
                    "market_cap", "liquidity", "volume_24h",
                    "buys_1h", "sells_1h", "buy_ratio_1h",
                    "hour_utc", "day_of_week", "age_hours",
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for bull in bulls:
                    writer.writerow(bull)

            self.total_exports += 1
            logger.info(f"📊 Bulls exportés : {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Export bulls error : {e}")
            return None

    async def export_trades_csv(self, date_str: str = None) -> str:
        """Exporte l'historique des trades"""
        try:
            if not self.portfolio_tracker:
                return None

            if date_str is None:
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            filepath = os.path.join(
                self.EXPORT_DIR, f"trades_{date_str}.csv"
            )

            trades = self.portfolio_tracker.trades_history
            if not trades:
                return None

            with open(filepath, "w", newline="", encoding="utf-8") as f:
                fieldnames = [
                    "sell_date", "symbol", "mint",
                    "amount_eur", "pnl_pct", "pnl_eur",
                    "final_eur", "duration_min",
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for trade in trades:
                    writer.writerow(trade)

            self.total_exports += 1
            logger.info(f"📊 Trades exportés : {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Export trades error : {e}")
            return None

    async def export_portfolio_csv(self, date_str: str = None) -> str:
        """Exporte les positions ouvertes"""
        try:
            if not self.portfolio_tracker:
                return None

            if date_str is None:
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            filepath = os.path.join(
                self.EXPORT_DIR, f"portfolio_{date_str}.csv"
            )

            positions = self.portfolio_tracker.get_all_positions()
            if not positions:
                return None

            with open(filepath, "w", newline="", encoding="utf-8") as f:
                fieldnames = [
                    "entry_date", "symbol", "mint",
                    "amount_eur", "entry_price", "current_price",
                    "current_pnl", "entry_mc",
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for pos in positions:
                    writer.writerow(pos)

            self.total_exports += 1
            logger.info(f"📊 Portfolio exporté : {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Export portfolio error : {e}")
            return None

    async def export_ml_csv(self, date_str: str = None) -> str:
        """Exporte les données ML"""
        try:
            if not self.ml_scorer:
                return None

            if date_str is None:
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            filepath = os.path.join(
                self.EXPORT_DIR, f"ml_data_{date_str}.csv"
            )

            # Récupère l'historique ML (si disponible)
            trades = getattr(self.ml_scorer, "trades_history", None)
            if not trades:
                return None

            with open(filepath, "w", newline="", encoding="utf-8") as f:
                fieldnames = [
                    "timestamp", "token_name", "is_win", "pnl_pct",
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for t in trades:
                    writer.writerow(t)

            self.total_exports += 1
            logger.info(f"📊 ML data exportée : {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Export ML error : {e}")
            return None

    async def export_candidates_csv(self, date_str: str = None) -> str:
        """Exporte les candidats alpha wallets"""
        try:
            if not self.wallet_discovery:
                return None

            if date_str is None:
                date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

            filepath = os.path.join(
                self.EXPORT_DIR, f"wallet_candidates_{date_str}.csv"
            )

            candidates = self.wallet_discovery.get_top_candidates(50)
            if not candidates:
                return None

            with open(filepath, "w", newline="", encoding="utf-8") as f:
                fieldnames = [
                    "wallet", "bulls_hit", "win_rate",
                    "avg_gain", "score", "first_seen",
                ]
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                for c in candidates:
                    writer.writerow(c)

            self.total_exports += 1
            logger.info(f"📊 Candidates exportés : {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Export candidates error : {e}")
            return None

    # ════════════════════════════════════════
    # HELPERS
    # ════════════════════════════════════════

    def _esc(self, text: str) -> str:
        """Escape MarkdownV2"""
        special = r'_*[]()~`>#+-=|{}.!'
        return "".join(
            f"\\{c}" if c in special else c
            for c in str(text)
        )

    async def force_daily_report(self):
        """Force l'envoi immédiat du rapport quotidien"""
        await self._generate_daily_report()
        await self._export_all_csv()

    def get_stats(self) -> dict:
        return {
            "reports_sent":       self.total_reports_sent,
            "total_exports":      self.total_exports,
            "last_report":        self.last_daily_report,
        }

    def list_exports(self) -> list:
        """Liste tous les fichiers CSV exportés"""
        try:
            files = os.listdir(self.EXPORT_DIR)
            return sorted(files, reverse=True)
        except Exception:
            return []