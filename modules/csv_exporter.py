# modules/csv_exporter.py v1.1
"""
CSV Exporter + Rapports quotidiens
Fix v1.1 : Lecture correcte des statistiques du bot
"""

import asyncio
import csv
import os
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("csv_exporter")


class CSVExporter:

    EXPORT_DIR = "data/exports"
    DAILY_REPORT_INTERVAL = 86400

    def __init__(
        self,
        bot=None,
        alert_sender=None,
        perf_tracker=None,
        bull_analyzer=None,
        portfolio_tracker=None,
        ml_scorer=None,
        wallet_discovery=None,
    ):
        self.bot               = bot
        self.alert_sender      = alert_sender
        self.perf_tracker      = perf_tracker
        self.bull_analyzer     = bull_analyzer
        self.portfolio_tracker = portfolio_tracker
        self.ml_scorer         = ml_scorer
        self.wallet_discovery  = wallet_discovery

        self.running = False
        self.last_daily_report = 0

        self.yesterday_snapshot = {
            "alerts_sent":     0,
            "tokens_analyzed": 0,
            "momentum_alerts": 0,
            "sell_alerts":     0,
            "bulls_detected":  0,
        }

        self.total_reports_sent = 0
        self.total_exports = 0

        os.makedirs(self.EXPORT_DIR, exist_ok=True)

    async def start(self):
        self.running = True
        logger.info("📊 CSVExporter démarré (rapport quotidien)")
        asyncio.create_task(self._daily_report_loop())

    async def stop(self):
        self.running = False
        logger.info("📊 CSVExporter arrêté")

    async def _daily_report_loop(self):
        await asyncio.sleep(3600)  # Attend 1h pour le 1er rapport
        while self.running:
            try:
                await self._generate_daily_report()
                await self._export_all_csv()
            except Exception as e:
                logger.error(f"Daily report error : {e}")
            await asyncio.sleep(self.DAILY_REPORT_INTERVAL)

    async def _generate_daily_report(self):
        try:
            if not self.alert_sender:
                return

            bot_stats = self._get_bot_stats()

            delta_alerts   = bot_stats.get("alerts_sent", 0) - self.yesterday_snapshot["alerts_sent"]
            delta_analyzed = bot_stats.get("tokens_analyzed", 0) - self.yesterday_snapshot["tokens_analyzed"]
            delta_momentum = bot_stats.get("momentum_alerts", 0) - self.yesterday_snapshot["momentum_alerts"]
            delta_sells    = bot_stats.get("sell_alerts", 0) - self.yesterday_snapshot["sell_alerts"]

            bulls_data = self.bull_analyzer.get_stats(days=1) if self.bull_analyzer else {}
            ml_data = self.ml_scorer.get_stats() if self.ml_scorer else {}
            
            portfolio_data = {}
            pnl_data = {}
            if self.portfolio_tracker:
                portfolio_data = self.portfolio_tracker.get_portfolio_summary()
                pnl_data = self.portfolio_tracker.get_pnl_by_period()

            wd_data = self.wallet_discovery.get_stats() if self.wallet_discovery else {}

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

            if bulls_data.get("total", 0) > 0:
                lines.append("🎯 *BULLS DÉTECTÉS \\(24h\\) :*")
                lines.append(f"  Total : `{bulls_data['total']}`")
                lines.append(f"  Gain moyen : `\\+{bulls_data.get('avg_gain', 0):.0f}%`")
                if bulls_data.get("top_5"):
                    top1 = bulls_data["top_5"][0]
                    lines.append(f"  🏆 Meilleur : ${self._esc(top1['symbol'])} \\+{top1['change_24h']:.0f}%")
                lines.append("")

            if portfolio_data.get("total_trades", 0) > 0:
                pnl_day = pnl_data.get("pnl_day", 0)
                pnl_emoji = "📈" if pnl_day >= 0 else "📉"
                pnl_sign = "\\+" if pnl_day >= 0 else ""

                lines.append("💼 *PORTFOLIO :*")
                lines.append(f"  {pnl_emoji} PnL 24h : `{pnl_sign}{pnl_day:.2f}€`")
                lines.append(f"  Pos ouvertes : `{portfolio_data['open_positions']}`")
                lines.append(f"  W/L : `{pnl_data.get('wins_day', 0)}`/`{pnl_data.get('losses_day', 0)}`")
                lines.append("")

            if ml_data.get("trades", 0) > 0:
                lines.append("🧠 *MACHINE LEARNING :*")
                lines.append(f"  Total trades : `{ml_data['trades']}`")
                lines.append(f"  Win rate : `{ml_data.get('win_rate', 0):.1f}%`")
                lines.append(f"  PnL moyen : `{ml_data.get('avg_pnl', 0):+.0f}%`")
                lines.append("")

            if wd_data.get("wallets_tracked", 0) > 0:
                lines.append("🔍 *WALLET DISCOVERY :*")
                lines.append(f"  Wallets trackés : `{wd_data['wallets_tracked']}`")
                lines.append(f"  Candidats : `{wd_data['candidates_ready']}`")
                lines.append("")

            lines.append("━━━━━━━━━━━━━━")
            lines.append("📁 *CSV EXPORTÉS :*")
            lines.append("`data/exports/`")
            lines.append(f"⏰ Prochain rapport dans 24h")

            msg = "\n".join(lines)
            await self.alert_sender._send_telegram(msg)

            self.yesterday_snapshot = {
                "alerts_sent":     bot_stats.get("alerts_sent", 0),
                "tokens_analyzed": bot_stats.get("tokens_analyzed", 0),
                "momentum_alerts": bot_stats.get("momentum_alerts", 0),
                "sell_alerts":     bot_stats.get("sell_alerts", 0),
                "bulls_detected":  bulls_data.get("total", 0),
            }

            self.total_reports_sent += 1
            self.last_daily_report = time.time()

        except Exception as e:
            logger.error(f"Generate daily report error : {e}", exc_info=True)

    def _get_bot_stats(self) -> dict:
        if not self.bot:
            return {}
        return {
            "alerts_sent": getattr(self.bot, "alerts_sent", 0),
            "tokens_analyzed": getattr(self.bot, "tokens_analyzed", 0),
            "momentum_alerts": getattr(self.bot, "momentum_alerts", 0),
            "sell_alerts": getattr(self.bot, "sell_alerts_sent", 0),
        }

    async def _export_all_csv(self):
        try:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            await self.export_bulls_csv(date_str)
            await self.export_trades_csv(date_str)
            await self.export_portfolio_csv(date_str)
            await self.export_ml_csv(date_str)
            await self.export_candidates_csv(date_str)
            logger.info(f"📊 Exports CSV terminés pour {date_str}")
        except Exception as e:
            logger.error(f"Export all CSV error : {e}")

    async def export_bulls_csv(self, date_str: str = None) -> str:
        try:
            if not self.bull_analyzer or not self.bull_analyzer.bulls:
                return None
            date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            filepath = os.path.join(self.EXPORT_DIR, f"bulls_{date_str}.csv")
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(self.bull_analyzer.bulls[0].keys()), extrasaction="ignore")
                writer.writeheader()
                for bull in self.bull_analyzer.bulls:
                    writer.writerow(bull)
            return filepath
        except Exception:
            return None

    async def export_trades_csv(self, date_str: str = None) -> str:
        try:
            if not self.portfolio_tracker or not self.portfolio_tracker.trades_history:
                return None
            date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            filepath = os.path.join(self.EXPORT_DIR, f"trades_{date_str}.csv")
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(self.portfolio_tracker.trades_history[0].keys()), extrasaction="ignore")
                writer.writeheader()
                for trade in self.portfolio_tracker.trades_history:
                    writer.writerow(trade)
            return filepath
        except Exception:
            return None

    async def export_portfolio_csv(self, date_str: str = None) -> str:
        try:
            if not self.portfolio_tracker:
                return None
            positions = self.portfolio_tracker.get_all_positions()
            if not positions:
                return None
            date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            filepath = os.path.join(self.EXPORT_DIR, f"portfolio_{date_str}.csv")
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(positions[0].keys()), extrasaction="ignore")
                writer.writeheader()
                for pos in positions:
                    writer.writerow(pos)
            return filepath
        except Exception:
            return None

    async def export_ml_csv(self, date_str: str = None) -> str:
        try:
            if not self.ml_scorer:
                return None
            trades = getattr(self.ml_scorer, "trades_history", None)
            if not trades:
                return None
            date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            filepath = os.path.join(self.EXPORT_DIR, f"ml_data_{date_str}.csv")
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(trades[0].keys()), extrasaction="ignore")
                writer.writeheader()
                for t in trades:
                    writer.writerow(t)
            return filepath
        except Exception:
            return None

    async def export_candidates_csv(self, date_str: str = None) -> str:
        try:
            if not self.wallet_discovery:
                return None
            candidates = self.wallet_discovery.get_top_candidates(50)
            if not candidates:
                return None
            date_str = date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d")
            filepath = os.path.join(self.EXPORT_DIR, f"wallet_candidates_{date_str}.csv")
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(candidates[0].keys()), extrasaction="ignore")
                writer.writeheader()
                for c in candidates:
                    writer.writerow(c)
            return filepath
        except Exception:
            return None

    def _esc(self, text: str) -> str:
        special = r'_*[]()~`>#+-=|{}.!'
        return "".join(f"\\{c}" if c in special else c for c in str(text))

    async def force_daily_report(self):
        await self._generate_daily_report()
        await self._export_all_csv()

    def get_stats(self) -> dict:
        return {
            "reports_sent":       self.total_reports_sent,
            "total_exports":      self.total_exports,
            "last_report":        self.last_daily_report,
        }