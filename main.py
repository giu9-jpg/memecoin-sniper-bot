# main.py — v13.1 FINAL
# Bot Sniper Memecoin Solana - ULTIMATE EDITION
# ═══════════════════════════════════════════════
# v13.1 FIX :
# - Pas d'ajout auto au sell tracker (fini le spam)
# - Nouvelle commande /clearpositions pour tout nettoyer
# - Position tracker manuel uniquement via /watch <mint>

import asyncio
import gc
import time
import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()

from utils.logger import logger
from utils.config_loader import load_config

from modules.pump_portal_ws        import PumpPortalWebSocket
from modules.pump_fun_monitor      import PumpFunMonitor
from modules.token_analyzer        import TokenAnalyzer
from modules.alert_sender          import AlertSender
from modules.whale_tracker         import WhaleTracker
from modules.position_tracker      import PositionTracker
from modules.market_context        import MarketContext
from modules.alpha_tracker         import AlphaTracker
from modules.performance_tracker   import PerformanceTracker
from modules.early_detector        import EarlyDetector
from modules.whale_inflow          import WhaleInflowTracker
from modules.twitter_tracker       import TwitterTracker
from modules.token_safety          import TokenSafety
from modules.dashboard_v2          import DashboardServerV2
from modules.raydium_monitor       import RadyiumMonitor
from modules.momentum_detector     import MomentumDetector
from modules.ml_scorer             import MLScorer
from modules.bull_run_analyzer     import BullRunAnalyzer
from modules.backtester            import Backtester
from modules.backtester_v2         import BacktesterV2
from modules.sell_signal_generator import SellSignalGenerator
from modules.chart_screenshot      import ChartScreenshot
from modules.wallet_discovery      import WalletDiscovery
from modules.auto_optimizer        import AutoOptimizer
from modules.portfolio_tracker     import PortfolioTracker
from modules.dump_detector         import DumpDetector
from modules.whale_sell_tracker    import WhaleSellTracker
from modules.csv_exporter          import CSVExporter
from modules.watchlist             import Watchlist
from modules.admin_security        import AdminSecurity
from modules.social_score          import SocialScore

from config.alpha_wallets        import (
    ALPHA_WALLETS,
    get_all_wallets,
    get_copy_threshold,
)

from config.alpha_accounts       import (
    ALPHA_ACCOUNTS,
    get_all_accounts as get_all_twitter_accounts,
)


POLLING_INTERVAL     = 30
HEALTH_CHECK_EVERY   = 300
POSITION_CHECK_EVERY = 60
MARKET_CHECK_EVERY   = 180
ALPHA_CHECK_EVERY    = 300
COPY_TRADING_EVERY   = 180
TWITTER_CHECK_EVERY  = 300
STATS_EVERY          = 86400
MEMORY_CLEANUP_EVERY = 1800
COMMAND_POLL_EVERY   = 2
MIN_SCORE            = 7.5


class MemeSniper:

    def __init__(self):
        self.config = load_config()

        self.market_context  = MarketContext()
        self.alpha_tracker   = AlphaTracker()
        self.perf_tracker    = PerformanceTracker()
        self.early_detector  = EarlyDetector()
        self.whale_inflow    = WhaleInflowTracker()
        self.twitter_tracker = TwitterTracker()
        self.token_safety    = TokenSafety(self.config.solana_rpc_url)
        self.ml_scorer       = MLScorer()

        self.bull_analyzer     = BullRunAnalyzer()
        self.backtester        = Backtester(self.bull_analyzer)
        self.backtester_v2     = BacktesterV2(self.bull_analyzer)
        self.chart_screenshot  = ChartScreenshot()
        self.wallet_discovery  = WalletDiscovery(self.bull_analyzer)

        self.portfolio_tracker = PortfolioTracker()
        self.admin_security    = AdminSecurity()
        self.social_score      = SocialScore()

        self.sell_generator = SellSignalGenerator(
            alert_callback=self.handle_sell_signal
        )
        self.sell_alerts_sent = 0

        self.dump_detector = DumpDetector(
            alert_callback=self.handle_dump_signal
        )
        self.dump_alerts_sent = 0

        self.whale_sell_tracker = WhaleSellTracker(
            alert_callback=self.handle_whale_sell_signal,
            alpha_wallets=get_all_wallets(),
        )
        self.whale_sell_alerts_sent = 0

        self.watchlist = Watchlist(
            alert_callback=self.handle_watch_triggered
        )
        self.watchlist_alerts_sent = 0

        self.analyzer = TokenAnalyzer(
            alpha_tracker=self.alpha_tracker,
            early_detector=self.early_detector,
            whale_inflow=self.whale_inflow,
        )

        self.alert_sender = AlertSender(
            market_context=self.market_context
        )

        self.auto_optimizer = AutoOptimizer(
            ml_scorer=self.ml_scorer,
            bull_analyzer=self.bull_analyzer,
            alert_sender=self.alert_sender,
        )

        self.csv_exporter = CSVExporter(
            bot=self,
            alert_sender=self.alert_sender,
            perf_tracker=self.perf_tracker,
            bull_analyzer=self.bull_analyzer,
            portfolio_tracker=self.portfolio_tracker,
            ml_scorer=self.ml_scorer,
            wallet_discovery=self.wallet_discovery,
        )

        self.whale_tracker    = WhaleTracker()
        self.pump_monitor     = PumpFunMonitor()
        self.raydium_monitor  = RadyiumMonitor()

        self.momentum_detector = MomentumDetector(
            alert_callback=self.handle_momentum_token
        )
        self.momentum_alerts = 0

        self.position_tracker = PositionTracker(
            alert_sender=self.alert_sender
        )

        self.ws_client = PumpPortalWebSocket(
            token_callback=self.handle_new_token_ws
        )

        self.dashboard = None
        if self.config.dashboard.enabled:
            self.dashboard = DashboardServerV2(
                bot=self,
                host=self.config.dashboard.host,
                port=self.config.dashboard.port,
            )

        self.http_session = None
        self.alerted_tokens = {}
        self.processing_tokens = set()
        self.paused = False
        self.ws_active        = False
        self.start_time       = time.time()
        self.tokens_analyzed  = 0
        self.alerts_sent      = 0
        self.copy_trades      = 0
        self.twitter_signals  = 0
        self.raydium_tokens   = 0
        self.max_alerted      = 500
        self.telegram_offset = 0

    async def run(self):
        self.http_session = aiohttp.ClientSession()

        modules_to_start = [
            ("TokenSafety v1.2",       self.token_safety),
            ("RadyiumMonitor",         self.raydium_monitor),
            ("MomentumDetector v1.2",  self.momentum_detector),
            ("BullRunAnalyzer",        self.bull_analyzer),
            ("SellSignalGenerator",    self.sell_generator),
            ("ChartScreenshot",        self.chart_screenshot),
            ("WalletDiscovery",        self.wallet_discovery),
            ("AutoOptimizer",          self.auto_optimizer),
            ("PortfolioTracker",       self.portfolio_tracker),
            ("DumpDetector",           self.dump_detector),
            ("WhaleSellTracker",       self.whale_sell_tracker),
            ("CSVExporter",            self.csv_exporter),
            ("Watchlist",              self.watchlist),
            ("AdminSecurity",          self.admin_security),
            ("SocialScore",            self.social_score),
        ]

        for name, module in modules_to_start:
            try:
                await module.start()
                logger.info(f"✅ {name} : ACTIF")
            except Exception as e:
                logger.error(f"❌ {name} : {e}")

        total_wallets = len(get_all_wallets())
        t1  = len(ALPHA_WALLETS.get("TIER1",   []))
        t15 = len(ALPHA_WALLETS.get("TIER1_5", []))
        t2  = len(ALPHA_WALLETS.get("TIER2",   []))

        twitter_count = len(get_all_twitter_accounts())
        t1_tw = len(ALPHA_ACCOUNTS.get("TIER1", []))
        t2_tw = len(ALPHA_ACCOUNTS.get("TIER2", []))
        t3_tw = len(ALPHA_ACCOUNTS.get("TIER3", []))

        ml_stats = self.ml_scorer.get_stats()
        opt_config = self.auto_optimizer.get_current_config()

        logger.info("🚀 MemeSniper v13.1 FINAL démarré !")
        logger.info(f"   Score min : {opt_config.get('min_score', MIN_SCORE)}/10")
        logger.info(f"   Alpha Wallets : {total_wallets} (T1:{t1} T1.5:{t15} T2:{t2})")
        logger.info(f"   Twitter : {twitter_count} (T1:{t1_tw} T2:{t2_tw} T3:{t3_tw})")
        logger.info(f"   ML : {ml_stats.get('trades', 0)} trades")

        if self.dashboard:
            logger.info(
                f"   Dashboard v2 : http://{self.config.dashboard.host}:"
                f"{self.config.dashboard.port}"
            )

        logger.info(f"   Trading Auto : DÉSACTIVÉ")

        try:
            await self.market_context.fetch_market_data()
            sig = self.market_context.get_market_signal()
            logger.info(
                f"   📊 Marché : {sig['regime']} | "
                f"BTC {sig['btc_change_24h']:+.1f}% | "
                f"FG {sig['fear_greed']}"
            )
        except Exception as e:
            logger.warning(f"   ⚠️ Market : {e}")

        try:
            stats = self.perf_tracker.get_stats()
            logger.info(
                f"   📈 Historique : {stats['total_alerts']} alertes | "
                f"WR : {stats['win_rate']}%"
            )
        except Exception:
            pass

        try:
            await self.alert_sender.send_startup_message()
        except Exception as e:
            logger.warning(f"   ⚠️ Startup Telegram : {e}")

        try:
            await self._init_telegram_offset()
        except Exception as e:
            logger.warning(f"   ⚠️ Init offset : {e}")

        logger.info("   ⚙️  Lancement des boucles...")

        tasks = [
            self._run_websocket(),
            self._run_polling_fallback(),
            self._run_raydium_monitor(),
            self._run_whale_tracker(),
            self._run_health_check(),
            self._run_position_tracker(),
            self._run_market_updater(),
            self._run_alpha_updater(),
            self._run_stats_reporter(),
            self._run_memory_cleanup(),
            self._run_alpha_copy_trading(),
            self._run_twitter_tracker(),
            self._run_command_listener(),
        ]

        if self.dashboard:
            tasks.append(self.dashboard.start())

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_websocket(self):
        try:
            self.ws_active = True
            logger.info("[WS] Démarrage PumpPortal...")
            await self.ws_client.start()
        except asyncio.CancelledError:
            logger.info("[WS] Annulé")
        except Exception as e:
            logger.error(f"[WS] Erreur : {e}")
        finally:
            self.ws_active = False

    async def _run_polling_fallback(self):
        logger.info(f"[POLLING] Actif ({POLLING_INTERVAL}s)")
        while True:
            try:
                tokens = await self.pump_monitor.get_new_tokens()
                for token in tokens:
                    await self.handle_new_token_polling(token)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[POLLING] {e}")
            await asyncio.sleep(POLLING_INTERVAL)

    async def _run_raydium_monitor(self):
        await asyncio.sleep(30)
        logger.info("[RAYDIUM] Multi-DEX démarré")
        try:
            await self.raydium_monitor.monitor_loop(
                callback=self.handle_new_token_raydium
            )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[RAYDIUM] {e}")

    async def _run_market_updater(self):
        logger.info(f"[MARKET] Actif ({MARKET_CHECK_EVERY}s)")
        while True:
            await asyncio.sleep(MARKET_CHECK_EVERY)
            try:
                await self.market_context.fetch_market_data()
                sig = self.market_context.get_market_signal()
                logger.info(
                    f"[MARKET] {sig['regime']} | "
                    f"BTC {sig['btc_change_24h']:+.1f}% | "
                    f"FG {sig['fear_greed']}"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MARKET] {e}")

    async def _run_alpha_updater(self):
        logger.info(f"[ALPHA] Actif ({ALPHA_CHECK_EVERY}s)")
        await asyncio.sleep(60)
        while True:
            try:
                await self.alpha_tracker.check_alpha_wallets()
                logger.info(f"[ALPHA] {len(self.alpha_tracker.token_buyers)} token(s)")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ALPHA] {e}")
            await asyncio.sleep(ALPHA_CHECK_EVERY)

    async def _run_alpha_copy_trading(self):
        logger.info(f"[COPY] Actif ({COPY_TRADING_EVERY}s)")
        await asyncio.sleep(120)
        while True:
            try:
                async def on_alpha_buy(token, wallet, tier):
                    self.copy_trades += 1
                    tier_str = tier or "UNKNOWN"
                    logger.info(f"[COPY] {tier_str} {wallet[:8]}... → {token[:8]}...")
                    if self.dashboard:
                        self.dashboard.add_event(f"Copy: {tier_str} {wallet[:8]}...")
                    if token not in self.alerted_tokens:
                        await self._analyze_and_alert(token, source=f"copy_{tier_str}")

                await self.alpha_tracker.check_new_alpha_buys(callback=on_alpha_buy)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[COPY] {e}")
            await asyncio.sleep(COPY_TRADING_EVERY)

    async def _run_twitter_tracker(self):
        logger.info(f"[TWITTER] Actif ({TWITTER_CHECK_EVERY}s)")
        await asyncio.sleep(180)
        while True:
            try:
                async def on_twitter_signal(signal):
                    self.twitter_signals += 1
                    tier = signal.get("tier", "UNKNOWN")
                    username = signal.get("username", "?")
                    addrs = signal.get("addresses", [])
                    logger.info(f"[TWITTER] {tier} @{username} → CA:{len(addrs)}")
                    if self.dashboard:
                        self.dashboard.add_event(f"Twitter {tier}: @{username}")
                    for address in addrs:
                        if address not in self.alerted_tokens:
                            await self._analyze_and_alert(address, source=f"twitter_{tier}")

                await self.twitter_tracker.check_all_accounts(callback=on_twitter_signal)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TWITTER] {e}")
            await asyncio.sleep(TWITTER_CHECK_EVERY)

    async def _run_whale_tracker(self):
        logger.info("[WHALE] Actif (60s)")
        while True:
            try:
                signals = await self.whale_tracker.check_whales()
                for signal in signals:
                    addr = signal.get("token_address", "")
                    if not addr or addr in self.alerted_tokens:
                        continue
                    label = signal.get("whale_label", "?")
                    amt = signal.get("amount_usd", 0)
                    logger.info(f"[WHALE] {label} → {addr[:8]}... (${amt:,.0f})")
                    if self.dashboard:
                        self.dashboard.add_event(f"Whale: {label} ${amt:,.0f}")
                    await self._analyze_and_alert(addr, source="whale")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WHALE] {e}")
            await asyncio.sleep(60)

    async def _run_position_tracker(self):
        logger.info(f"[POSITIONS] Actif ({POSITION_CHECK_EVERY}s)")
        await asyncio.sleep(30)
        while True:
            try:
                await self.position_tracker.check_all_positions()
                await self.portfolio_tracker.update_positions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[POSITIONS] {e}")
            await asyncio.sleep(POSITION_CHECK_EVERY)

    async def _run_stats_reporter(self):
        logger.info("[STATS] Actif 24h silencieux si aucune activite")
        await asyncio.sleep(STATS_EVERY)

        last_alerts = 0
        last_trades = 0

        while True:
            try:
                stats = self.perf_tracker.get_stats()
                current_alerts = stats.get("total_alerts", 0)
                current_trades = stats.get("wins", 0) + stats.get("losses", 0)

                delta_alerts = current_alerts - last_alerts
                delta_trades = current_trades - last_trades

                has_activity = (delta_alerts > 0) or (delta_trades > 0)

                if has_activity:
                    stats_msg = self.perf_tracker.get_summary_message()
                    delta_header = (
                        f"📊 *ACTIVITE 24H*\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"🎯 Nouvelles alertes : `{delta_alerts}`\n"
                        f"📋 Nouveaux trades : `{delta_trades}`\n\n"
                    )
                    full_msg = delta_header + stats_msg
                    await self.alert_sender._send_telegram(full_msg, buttons=None)
                    logger.info(f"[STATS] Rapport 24h envoye (+{delta_alerts} alertes)")
                else:
                    logger.info("[STATS] Rapport ignore aucune activite")

                last_alerts = current_alerts
                last_trades = current_trades

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[STATS] {e}")

            await asyncio.sleep(STATS_EVERY)

    async def _run_memory_cleanup(self):
        logger.info(f"[MEMORY] Actif ({MEMORY_CLEANUP_EVERY}s)")
        await asyncio.sleep(600)
        while True:
            try:
                self.alpha_tracker.cleanup_old_data()
                self.early_detector.cleanup_old()
                self.whale_inflow.cleanup_cache()
                self.twitter_tracker.cleanup_old_data()
                self._trim_alerted_tokens()
                collected = gc.collect()

                wd_stats = self.wallet_discovery.get_stats()
                wl_stats = self.watchlist.get_stats()

                logger.info(
                    f"[MEMORY] alerted={len(self.alerted_tokens)} | "
                    f"proc={len(self.processing_tokens)} | "
                    f"bulls={len(self.bull_analyzer.bulls)} | "
                    f"pos={self.sell_generator.get_positions_count()} | "
                    f"disco={wd_stats['wallets_tracked']} | "
                    f"watch={wl_stats['active_watches']} | "
                    f"gc={collected}"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MEMORY] {e}")
            await asyncio.sleep(MEMORY_CLEANUP_EVERY)

    async def _run_health_check(self):
        logger.info(f"[HEALTH] Actif ({HEALTH_CHECK_EVERY}s)")
        await asyncio.sleep(60)
        while True:
            try:
                uptime = int((time.time() - self.start_time) / 60)
                ws = "✅" if self.ws_active else "❌"
                pause = "⏸ PAUSE" if self.paused else "▶️ ACTIF"

                try:
                    regime = self.market_context.get_market_signal()["regime"]
                except Exception:
                    regime = "N/A"

                ml = self.ml_scorer.get_stats()
                sell = self.sell_generator.get_stats()
                wd = self.wallet_discovery.get_stats()
                opt = self.auto_optimizer.get_stats()
                port = self.portfolio_tracker.get_portfolio_summary()
                wl = self.watchlist.get_stats()

                logger.info(
                    f"[HEALTH] {pause} | Up:{uptime}min | WS:{ws} | "
                    f"Anal:{self.tokens_analyzed} | Alrt:{self.alerts_sent} | "
                    f"Copy:{self.copy_trades} | Tw:{self.twitter_signals} | "
                    f"Rd:{self.raydium_tokens} | Mom:{self.momentum_alerts} | "
                    f"Bulls:{len(self.bull_analyzer.bulls)} | "
                    f"Sells:{sell['positions_open']}p/{sell['total_signals']}s | "
                    f"Dump:{self.dump_alerts_sent} | "
                    f"WSell:{self.whale_sell_alerts_sent} | "
                    f"Watch:{wl['active_watches']}/{self.watchlist_alerts_sent} | "
                    f"Port:{port['open_positions']}p | "
                    f"Wl:{wd['wallets_tracked']}/{wd['candidates_ready']}c | "
                    f"Opt:{opt['total_optimizations']} | "
                    f"ML:{ml.get('trades', 0)} | Mkt:{regime}"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[HEALTH] {e}")
            await asyncio.sleep(HEALTH_CHECK_EVERY)

    async def _init_telegram_offset(self):
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        try:
            async with self.http_session.get(
                url, params={"timeout": 1},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    updates = data.get("result", [])
                    if updates:
                        self.telegram_offset = updates[-1]["update_id"] + 1
                        logger.info(f"[CMD] Offset : {self.telegram_offset}")
        except Exception:
            pass

    async def _run_command_listener(self):
        logger.info(f"[CMD] Actif ({COMMAND_POLL_EVERY}s)")
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        if not token or not chat_id:
            logger.warning("[CMD] Credentials manquants")
            return

        url = f"https://api.telegram.org/bot{token}/getUpdates"

        while True:
            try:
                async with self.http_session.get(
                    url,
                    params={"offset": self.telegram_offset, "timeout": 20},
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for update in data.get("result", []):
                            self.telegram_offset = update["update_id"] + 1
                            msg = update.get("message", {})
                            text = msg.get("text", "").strip()
                            chat = str(msg.get("chat", {}).get("id", ""))

                            if not self.admin_security.is_authorized(chat):
                                continue

                            if text.startswith("/"):
                                await self._handle_command(text, chat)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[CMD] {e}")
                await asyncio.sleep(5)
            await asyncio.sleep(COMMAND_POLL_EVERY)

    async def _handle_command(self, text: str, user_id: str = None):
        text_lower = text.lower().strip()
        logger.info(f"[CMD] {text}")

        if user_id:
            rl = self.admin_security.check_rate_limit(user_id, text_lower)
            if not rl["allowed"]:
                await self._send_reply(f"🔒 {rl['reason']}")
                return

        if user_id and self.admin_security.needs_confirmation(text_lower):
            conf = self.admin_security.request_confirmation(user_id, text_lower)
            if not conf["confirmed"]:
                await self._send_reply(conf["message"])
                return

        if user_id:
            self.admin_security.register_command(user_id, text_lower)

        cmd_args = {
            "/check ":         self._cmd_check,
            "/win ":           self._cmd_win,
            "/loss ":          self._cmd_loss,
            "/backtest ":      self._cmd_backtest,
            "/watch ":         self._cmd_watch_position,
            "/close ":         self._cmd_close,
            "/buy ":           self._cmd_buy,
            "/sell ":          self._cmd_sell,
            "/watchmc ":       self._cmd_watchmc,
            "/watchpump ":     self._cmd_watchpump,
            "/watchdrop ":     self._cmd_watchdrop,
            "/unwatch ":       self._cmd_unwatch,
            "/social ":        self._cmd_social,
            "/strategy ":      self._cmd_strategy,
        }

        for prefix, handler in cmd_args.items():
            if text_lower.startswith(prefix):
                await handler(text[len(prefix):].strip())
                return

        routes = {
            "/status":         self._cmd_status,
            "/stats":          self._cmd_stats,
            "/alertes":        self._cmd_alertes,
            "/mlstats":        self._cmd_mlstats,
            "/bullrun":        self._cmd_bullrun,
            "/backtest":       self._cmd_backtest,
            "/positions":      self._cmd_positions,
            "/clearpositions": self._cmd_clear_positions,
            "/wallets":        self._cmd_wallets,
            "/candidates":     self._cmd_candidates,
            "/optimize":       self._cmd_optimize,
            "/portfolio":      self._cmd_portfolio,
            "/pnl":            self._cmd_pnl,
            "/trades":         self._cmd_trades,
            "/watchlist":      self._cmd_watchlist,
            "/compare":        self._cmd_compare_strategies,
            "/strategies":     self._cmd_list_strategies,
            "/report":         self._cmd_report,
            "/admin":          self._cmd_admin,
            "/pause":          self._cmd_pause,
            "/resume":         self._cmd_resume,
            "/help":           self._cmd_help,
            "/start":          self._cmd_help,
        }

        handler = routes.get(text_lower)
        if handler:
            try:
                await handler()
            except Exception as e:
                logger.error(f"[CMD] {text}: {e}")
                await self._send_reply(f"❌ {e}")
        else:
            await self._send_reply(
                f"❓ Commande inconnue: `{self._esc(text)}`\n"
                f"Tape /help"
            )

    async def _cmd_status(self):
        uptime = int(time.time() - self.start_time)
        h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60

        try:
            regime = self.market_context.get_market_signal()["regime"]
            btc = self.market_context.get_market_signal()["btc_change_24h"]
        except Exception:
            regime, btc = "N/A", 0

        ml = self.ml_scorer.get_stats()
        n_bulls = len(self.bull_analyzer.bulls)
        sell = self.sell_generator.get_stats()
        wd = self.wallet_discovery.get_stats()
        opt = self.auto_optimizer.get_stats()
        port = self.portfolio_tracker.get_portfolio_summary()
        wl = self.watchlist.get_stats()

        pause_str = "⏸ EN PAUSE" if self.paused else "▶️ Actif"
        ws_str = "✅ Actif" if self.ws_active else "❌ Inactif"

        msg = (
            f"🤖 *MemeSniper v13\\.1 FINAL*\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"⏱ Uptime: `{h}h {m}m {s}s`\n"
            f"🔄 État: *{self._esc(pause_str)}*\n"
            f"📡 WebSocket: {ws_str}\n\n"
            f"🎯 *Modules :*\n"
            f"🛡️ Safety v1\\.2 \\| 🔥 Momentum v1\\.2\n"
            f"🎯 Bulls: `{n_bulls}` \\| 💰 Sells: `{sell['positions_open']}`\n"
            f"📸 Charts \\| 🔍 Wallets: `{wd['wallets_tracked']}`\n"
            f"🎯 Optim: `{opt['total_optimizations']}`\n"
            f"💼 Portfolio: `{port['open_positions']}` pos\n"
            f"📉 Dump: `{self.dump_alerts_sent}`\n"
            f"🐋 WSell: `{self.whale_sell_alerts_sent}`\n"
            f"🔔 Watch: `{wl['active_watches']}`\n"
            f"🧠 ML: `{ml.get('trades', 0)}` trades\n\n"
            f"📊 *Activité :*\n"
            f"  Analysés: `{self.tokens_analyzed}`\n"
            f"  Alertes: `{self.alerts_sent}`\n"
            f"  Sell: `{self.sell_alerts_sent}`\n"
            f"  Copy: `{self.copy_trades}`\n"
            f"  Twitter: `{self.twitter_signals}`\n"
            f"  Raydium: `{self.raydium_tokens}`\n"
            f"  Momentum: `{self.momentum_alerts}`\n\n"
            f"🌍 Marché: *{self._esc(regime)}* \\(BTC `{btc:+.1f}%`\\)"
        )
        await self._send_reply(msg)

    async def _cmd_stats(self):
        try:
            stats = self.perf_tracker.get_stats()
            msg = (
                f"📈 *Performance*\n━━━━━━━━━━━━━━\n\n"
                f"Total: `{stats.get('total_alerts', 0)}`\n"
                f"WR: `{stats.get('win_rate', 0):.1f}%`\n"
                f"Wins: `{stats.get('wins', 0)}` ✅\n"
                f"Losses: `{stats.get('losses', 0)}` ❌\n\n"
                f"💎 *Par tier :*\n"
                f"  Ultimate: `{stats.get('ultimate', 0)}`\n"
                f"  Strong: `{stats.get('strong', 0)}`\n"
                f"  Good: `{stats.get('good', 0)}`\n"
                f"  Normal: `{stats.get('normal', 0)}`"
            )
            await self._send_reply(msg)
        except Exception as e:
            await self._send_reply(f"❌ {self._esc(str(e))}")

    async def _cmd_alertes(self):
        if not self.alerted_tokens:
            await self._send_reply("📭 Aucune alerte")
            return

        sorted_alerts = sorted(
            self.alerted_tokens.items(),
            key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0,
            reverse=True
        )[:10]

        lines = ["📋 *10 dernières alertes :*\n━━━━━━━━━━━━━━\n"]
        for i, (mint, ts) in enumerate(sorted_alerts, 1):
            if isinstance(ts, (int, float)):
                age = (time.time() - ts) / 60
                if age < 60:
                    age_str = f"{age:.0f}min"
                elif age < 1440:
                    age_str = f"{age/60:.1f}h"
                else:
                    age_str = f"{age/1440:.1f}j"
            else:
                age_str = "?"
            short = f"{mint[:8]}\\.\\.\\.{mint[-4:]}"
            lines.append(f"`{i}\\.` `{short}` \\- {age_str}")
        await self._send_reply("\n".join(lines))

    async def _cmd_check(self, mint: str):
        if not mint or len(mint) < 32:
            await self._send_reply("❌ Format: `/check <mint>`")
            return
        await self._send_reply(f"🔍 Analyse `{self._esc(mint[:16])}\\.\\.\\.`")
        try:
            safety = await self.token_safety.full_safety_check(mint)
            summary = self.token_safety.summary(safety)
            await self._send_reply(
                f"🛡️ *Résultat:*\n```\n{self._esc(summary)}\n```"
            )
        except Exception as e:
            await self._send_reply(f"❌ {self._esc(str(e))}")

    async def _cmd_win(self, args: str):
        parts = args.split()
        name = parts[0] if parts else "?"
        try:
            pnl = float(parts[1]) if len(parts) > 1 else 100.0
        except ValueError:
            pnl = 100.0
        self.ml_scorer.record_result(token_name=name, is_win=True, pnl_pct=pnl)
        stats = self.ml_scorer.get_stats()
        await self._send_reply(
            f"✅ *WIN* `{self._esc(name)}` `\\+{pnl:.0f}%`\n"
            f"🧠 ML: {stats['trades']} trades | WR: {stats.get('win_rate', 0):.0f}%"
        )

    async def _cmd_loss(self, args: str):
        parts = args.split()
        name = parts[0] if parts else "?"
        try:
            pnl = float(parts[1]) if len(parts) > 1 else -30.0
        except ValueError:
            pnl = -30.0
        if pnl > 0:
            pnl = -pnl
        self.ml_scorer.record_result(token_name=name, is_win=False, pnl_pct=pnl)
        stats = self.ml_scorer.get_stats()
        await self._send_reply(
            f"❌ *LOSS* `{self._esc(name)}` `{pnl:.0f}%`\n"
            f"🧠 ML: {stats['trades']} trades | WR: {stats.get('win_rate', 0):.0f}%"
        )

    async def _cmd_mlstats(self):
        stats = self.ml_scorer.get_stats()
        if not stats.get("ready"):
            msg = (
                f"🧠 *ML Scorer*\n━━━━━━━━━━━━━━\n\n"
                f"Trades: `{stats.get('trades', 0)}/5`\n"
                f"État: ⏳ Apprentissage\n\n"
                f"💡 `/win TOKEN 250` | `/loss TOKEN 35`"
            )
        else:
            msg = (
                f"🧠 *ML Scorer*\n━━━━━━━━━━━━━━\n\n"
                f"Trades: `{stats['trades']}`\n"
                f"Wins: `{stats['wins']}` ✅\n"
                f"Losses: `{stats['losses']}` ❌\n"
                f"WR: `{stats['win_rate']:.1f}%`\n"
                f"PnL moy: `{stats['avg_pnl']:+.1f}%`\n"
                f"Features: `{stats['features']}`"
            )
        await self._send_reply(msg)

    async def _cmd_bullrun(self):
        stats = self.bull_analyzer.get_stats(days=7)
        if stats["total"] == 0:
            await self._send_reply(
                f"🎯 *Bull Analyzer*\n\n"
                f"{self._esc(stats.get('message', ''))}\n"
                f"Scans: `{self.bull_analyzer.tokens_scanned}`"
            )
            return

        lines = [
            f"🎯 *BULL RUN ANALYZER*",
            f"━━━━━━━━━━━━━━",
            f"",
            f"📊 Bulls \\(7j\\): *{stats['total']}*",
            f"📈 Gain moyen: *\\+{stats['avg_gain']:.0f}%*",
        ]

        if stats.get("hours"):
            lines.append("\n⏰ *TOP HEURES :*")
            for h, c in stats["hours"][:3]:
                pct = round(c / stats["total"] * 100)
                lines.append(f"  `{h:02d}h`: {c} \\({pct}%\\)")

        if stats.get("top_5"):
            lines.append("\n🏆 *TOP 5 :*")
            for i, b in enumerate(stats["top_5"], 1):
                lines.append(
                    f"  `{i}\\.` ${self._esc(b['symbol'])} \\+{b['change_24h']:.0f}%"
                )

        recos = self.bull_analyzer.get_recommendations()
        if recos:
            lines.append("\n🧠 *RECOS :*")
            for r in recos[:3]:
                lines.append(f"  • {self._esc(r)}")

        await self._send_reply("\n".join(lines))

    async def _cmd_backtest(self, args: str = ""):
        parts = args.split() if args else []
        min_liq = 5_000
        days = 30
        try:
            if len(parts) >= 1:
                min_liq = int(parts[0])
            if len(parts) >= 2:
                days = int(parts[1])
        except ValueError:
            await self._send_reply("❌ `/backtest [liq] [days]`")
            return

        configs = [
            {"name": "Actuel", "min_liquidity": 5_000, "min_volume": 100_000, "min_buy_ratio": 55, "days": days},
            {"name": "Custom", "min_liquidity": min_liq, "min_volume": 100_000, "min_buy_ratio": 55, "days": days},
            {"name": "Aggressif", "min_liquidity": 1_000, "min_volume": 50_000, "min_buy_ratio": 50, "days": days},
        ]

        results = self.backtester.compare_configs(configs)

        if results[0].get("total_bulls", 0) == 0:
            await self._send_reply(
                f"📊 *BACKTEST*\n\n{self._esc(results[0].get('message', ''))}"
            )
            return

        lines = [
            f"📊 *BACKTEST HISTORIQUE*",
            f"━━━━━━━━━━━━━━",
            f"Période: `{days}j`",
            f"Bulls: `{results[0]['total_bulls']}`",
            "",
        ]

        for res in results:
            liq = res.get("params", {}).get("min_liquidity", 0)
            lines.append(f"━━━━━━━━━━━━━━")
            lines.append(f"🎯 *{self._esc(res['name'])}* \\(liq ≥ ${liq/1000:.0f}K\\)")
            lines.append(f"  Alertes: `{res['would_alert']}`/`{res['total_bulls']}`")
            lines.append(f"  Hit rate: `{res['hit_rate']:.1f}%`")
            lines.append(f"  Gain moy: `\\+{res['avg_gain']:.0f}%`")

        await self._send_reply("\n".join(lines))

    async def _cmd_strategy(self, args: str):
        parts = args.split()
        strat_name = parts[0].upper() if parts else "BALANCED"
        try:
            days = int(parts[1]) if len(parts) > 1 else 30
        except ValueError:
            days = 30

        result = self.backtester_v2.simulate_strategy(
            strategy_name=strat_name, days=days, entry_amount=10,
        )

        if result.get("total_trades", 0) == 0:
            await self._send_reply(
                f"📊 *{self._esc(strat_name)}*\n\n"
                f"{self._esc(result.get('message', 'Pas de données'))}"
            )
            return

        msg = (
            f"📊 *STRATÉGIE : {self._esc(result['strategy_name'])}*\n"
            f"━━━━━━━━━━━━━━\n"
            f"_{self._esc(result['strategy_desc'])}_\n\n"
            f"🎯 Trades: `{result['total_trades']}`\n"
            f"✅ Wins: `{result['wins']}` \\| ❌ Losses: `{result['losses']}`\n"
            f"📈 WR: `{result['win_rate']:.1f}%`\n\n"
            f"💰 *Résultats :*\n"
            f"  Investi: `{result['total_invested']:.0f}€`\n"
            f"  PnL: `{result['total_pnl_eur']:+.0f}€`\n"
            f"  ROI: `{result['roi_pct']:+.1f}%`\n\n"
            f"🎯 TPs: TP1:{result['tp_hits']['TP1']} \\| "
            f"TP2:{result['tp_hits']['TP2']} \\| "
            f"TP3:{result['tp_hits']['TP3']} \\| "
            f"TP4:{result['tp_hits']['TP4']}\n"
            f"🛑 SL: `{result['sl_hits']}`"
        )
        await self._send_reply(msg)

    async def _cmd_compare_strategies(self):
        result = self.backtester_v2.compare_strategies(days=30)

        if "error" in result:
            await self._send_reply(f"📊 {self._esc(result['error'])}")
            return

        lines = [
            f"📊 *COMPARAISON STRATÉGIES*",
            f"━━━━━━━━━━━━━━",
            f"Période: `{result['period_days']}j`",
            "",
        ]

        for res in result["results"]:
            if res.get("total_trades", 0) == 0:
                continue
            lines.append(f"━━━━━━━━━━━━━━")
            lines.append(f"🎯 *{self._esc(res['strategy_name'])}*")
            lines.append(f"  Trades: `{res['total_trades']}` \\| WR: `{res['win_rate']:.0f}%`")
            lines.append(f"  ROI: `{res['roi_pct']:+.1f}%` \\| PnL: `{res['total_pnl_eur']:+.0f}€`")

        lines.append("")
        lines.append(f"🏆 Meilleur ROI: *{self._esc(result['best_by_roi'])}*")
        lines.append(f"🎯 Meilleur WR: *{self._esc(result['best_by_winrate'])}*")

        await self._send_reply("\n".join(lines))

    async def _cmd_list_strategies(self):
        strats = self.backtester_v2.get_available_strategies()

        lines = [
            f"📊 *STRATÉGIES DISPONIBLES*",
            f"━━━━━━━━━━━━━━",
            "",
        ]

        for name, info in strats.items():
            lines.append(f"🎯 *{name}*")
            lines.append(f"  {self._esc(info['description'])}")
            lines.append(f"  TPs: `{info['tp_count']}` \\| SL: `{info['sl_pct']}%`")
            lines.append("")

        lines.append(f"💡 `/strategy NAME [days]`")
        lines.append(f"💡 `/compare` pour comparer")

        await self._send_reply("\n".join(lines))

    async def _cmd_buy(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            await self._send_reply(
                "❌ `/buy SYMBOL AMOUNT [MINT]`\n"
                "Ex: `/buy PEPE 50`"
            )
            return

        symbol = parts[0].upper()
        try:
            amount = float(parts[1])
        except ValueError:
            await self._send_reply("❌ Montant invalide")
            return

        mint = parts[2] if len(parts) > 2 else None

        result = await self.portfolio_tracker.add_buy(
            symbol=symbol, amount_eur=amount, mint=mint
        )

        if result["success"]:
            pos = result["position"]
            await self._send_reply(
                f"✅ *ACHAT*\n\n"
                f"Token: `${self._esc(symbol)}`\n"
                f"Montant: `{amount:.2f}€`\n"
                f"MC: `${pos.get('entry_mc', 0)/1000:.0f}K`"
            )
        else:
            await self._send_reply(f"❌ {self._esc(result.get('error', 'Erreur'))}")

    async def _cmd_sell(self, args: str):
        parts = args.split()
        if not parts:
            await self._send_reply("❌ `/sell SYMBOL [PNL_PCT]`")
            return

        symbol = parts[0].upper()
        pnl = None
        try:
            if len(parts) > 1:
                pnl = float(parts[1])
        except ValueError:
            pass

        result = await self.portfolio_tracker.add_sell(symbol=symbol, pnl_pct=pnl)

        if result["success"]:
            trade = result["trade"]
            pnl_emoji = "🚀" if trade["pnl_pct"] > 0 else "💀"
            await self._send_reply(
                f"{pnl_emoji} *VENTE*\n\n"
                f"Token: `${self._esc(symbol)}`\n"
                f"PnL: `{trade['pnl_pct']:+.1f}%`\n"
                f"Gain: `{trade['pnl_eur']:+.2f}€`\n"
                f"Durée: `{trade['duration_min']:.0f}min`"
            )

            self.ml_scorer.record_result(
                token_name=symbol,
                is_win=(trade['pnl_pct'] > 0),
                pnl_pct=trade['pnl_pct'],
            )
        else:
            await self._send_reply(f"❌ {self._esc(result.get('error', 'Erreur'))}")

    async def _cmd_portfolio(self):
        summary = self.portfolio_tracker.get_portfolio_summary()
        positions = self.portfolio_tracker.get_all_positions()

        if summary["open_positions"] == 0 and summary["total_trades"] == 0:
            await self._send_reply(
                f"💼 *Portfolio vide*\n\n"
                f"💡 `/buy SYMBOL AMOUNT`\n"
                f"💡 `/sell SYMBOL [PNL]`"
            )
            return

        lines = [
            f"💼 *PORTFOLIO*",
            f"━━━━━━━━━━━━━━",
            f"",
            f"📊 Positions: `{summary['open_positions']}`",
            f"💰 Investi: `{summary['total_invested']:.0f}€`",
            f"📈 PnL réalisé: `{summary['total_pnl']:+.0f}€`",
            f"📈 PnL non\\-réalisé: `{summary['total_open_pnl_eur']:+.0f}€`",
            f"🎯 Trades totaux: `{summary['total_trades']}`",
        ]

        if positions:
            lines.append("\n━━━━━━━━━━━━━━")
            lines.append("💎 *POSITIONS :*")
            for pos in positions[:10]:
                sym = self._esc(pos['symbol'])
                amt = pos['amount_eur']
                pnl = pos.get('current_pnl', 0)
                emoji = "🚀" if pnl > 0 else "📉" if pnl < 0 else "➡️"
                lines.append(f"  {emoji} `${sym}`: {amt:.0f}€ \\({pnl:+.0f}%\\)")

        await self._send_reply("\n".join(lines))

    async def _cmd_pnl(self):
        pnl = self.portfolio_tracker.get_pnl_by_period()

        def fmt(v):
            return f"`{v:+.2f}€`" if v != 0 else "`0€`"

        msg = (
            f"📊 *PnL PAR PÉRIODE*\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"📅 *Aujourd'hui :* {fmt(pnl['pnl_day'])}\n"
            f"   W/L: `{pnl['wins_day']}`/`{pnl['losses_day']}`\n\n"
            f"📅 *7 jours :* {fmt(pnl['pnl_week'])}\n"
            f"   W/L: `{pnl['wins_week']}`/`{pnl['losses_week']}`\n\n"
            f"📅 *30 jours :* {fmt(pnl['pnl_month'])}\n\n"
            f"🌍 *All\\-time :* {fmt(pnl['pnl_all'])}\n"
            f"   W/L: `{pnl['wins_all']}`/`{pnl['losses_all']}`\n"
            f"   WR: `{pnl['win_rate_all']:.1f}%`"
        )
        await self._send_reply(msg)

    async def _cmd_trades(self):
        trades = self.portfolio_tracker.get_all_trades(limit=15)

        if not trades:
            await self._send_reply("📭 Aucun trade")
            return

        lines = [
            f"📋 *DERNIERS TRADES*",
            f"━━━━━━━━━━━━━━",
            "",
        ]

        for t in trades:
            sym = self._esc(t['symbol'])
            pnl_pct = t['pnl_pct']
            pnl_eur = t['pnl_eur']
            emoji = "🚀" if pnl_pct > 0 else "💀"
            lines.append(f"{emoji} `${sym}` `{pnl_pct:+.0f}%` \\({pnl_eur:+.2f}€\\)")

        await self._send_reply("\n".join(lines))

    async def _cmd_watchmc(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            await self._send_reply("❌ `/watchmc SYMBOL TARGET`\nEx: `/watchmc PEPE 500K`")
            return

        symbol = parts[0]
        target_str = parts[1].upper()

        try:
            if target_str.endswith("K"):
                target = float(target_str[:-1]) * 1000
            elif target_str.endswith("M"):
                target = float(target_str[:-1]) * 1_000_000
            else:
                target = float(target_str)
        except ValueError:
            await self._send_reply("❌ Target invalide")
            return

        result = await self.watchlist.add_watch(
            symbol_or_mint=symbol, alert_type="MC_TARGET", target=target,
        )

        if result["success"]:
            await self._send_reply(
                f"🔔 *Watch MC ajoutée*\n"
                f"`${self._esc(symbol)}` → `${target/1000:.0f}K`"
            )
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_watchpump(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            await self._send_reply("❌ `/watchpump SYMBOL PCT`")
            return

        symbol = parts[0]
        try:
            pct = float(parts[1])
        except ValueError:
            await self._send_reply("❌ % invalide")
            return

        result = await self.watchlist.add_watch(
            symbol_or_mint=symbol, alert_type="PUMP", target=pct,
        )

        if result["success"]:
            await self._send_reply(
                f"🔔 *Watch pump*\n"
                f"`${self._esc(symbol)}` → `\\+{pct:.0f}%`"
            )
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_watchdrop(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            await self._send_reply("❌ `/watchdrop SYMBOL PCT`")
            return

        symbol = parts[0]
        try:
            pct = float(parts[1])
        except ValueError:
            await self._send_reply("❌ % invalide")
            return

        result = await self.watchlist.add_watch(
            symbol_or_mint=symbol, alert_type="DROP", target=pct,
        )

        if result["success"]:
            await self._send_reply(
                f"🔔 *Watch drop*\n"
                f"`${self._esc(symbol)}` → `\\-{pct:.0f}%`"
            )
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_unwatch(self, args: str):
        parts = args.split()
        if not parts:
            await self._send_reply("❌ `/unwatch SYMBOL [TYPE]`")
            return

        symbol = parts[0]
        alert_type = parts[1].upper() if len(parts) > 1 else None

        result = self.watchlist.remove_watch(symbol, alert_type)

        if result["success"]:
            await self._send_reply(f"✅ {result['removed']} watch\\(s\\) supprimée\\(s\\)")
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_watchlist(self):
        watches = self.watchlist.get_all_watches()
        stats = self.watchlist.get_stats()

        if not watches:
            await self._send_reply(
                f"🔔 *Watchlist vide*\n\n"
                f"💡 `/watchmc SYMBOL 500K`\n"
                f"💡 `/watchpump SYMBOL 100`\n"
                f"💡 `/watchdrop SYMBOL 30`"
            )
            return

        lines = [
            f"🔔 *WATCHLIST*",
            f"━━━━━━━━━━━━━━",
            f"Actives: `{stats['active_watches']}`",
            f"Déclenchées: `{stats['triggered_watches']}`",
            "",
        ]

        for w in watches[:15]:
            type_emoji = {
                "MC_TARGET": "🎯", "PUMP": "🚀", "DROP": "📉",
                "PRICE": "💰", "VOLUME": "📊",
            }.get(w["type"], "🔔")

            lines.append(
                f"{type_emoji} `${self._esc(w['symbol'])}` "
                f"{self._esc(w['type'])} `{w['target']}`"
            )

        await self._send_reply("\n".join(lines))

    async def _cmd_positions(self):
        positions = self.sell_generator.get_positions()
        if not positions:
            await self._send_reply(
                f"💰 *Positions vides*\n\n"
                f"💡 `/watch <mint>` pour surveiller\n"
                f"un token que tu as acheté"
            )
            return

        lines = [f"💰 *POSITIONS SURVEILLÉES*", f"━━━━━━━━━━━━━━", ""]
        for i, (mint, pos) in enumerate(list(positions.items())[:10], 1):
            elapsed = (time.time() - pos["entry_time"]) / 60
            elapsed_str = f"{elapsed:.0f}min" if elapsed < 60 else f"{elapsed/60:.1f}h"
            lines.append(f"━━━━━━━━━━━━━━")
            lines.append(f"`{i}\\.` *${self._esc(pos['symbol'])}*")
            lines.append(f"  Entry MC: `${pos['entry_mc']/1000:.0f}K`")
            lines.append(f"  Max gain: `\\+{pos['max_gain']:.0f}%`")
            lines.append(f"  TPs: `{len(pos['tp_triggered'])}/4`")
            lines.append(f"  Ouvert: `{elapsed_str}`")

        lines.append("")
        lines.append("💡 `/close SYM` ou `/clearpositions`")

        await self._send_reply("\n".join(lines))

    async def _cmd_clear_positions(self):
        """Ferme TOUTES les positions surveillées d'un coup"""
        count = self.sell_generator.clear_all_positions()
        await self._send_reply(
            f"✅ *{count} positions supprimées*\n\n"
            f"Le sell tracker est vide\\.\n"
            f"Utilise `/watch <mint>` pour surveiller\n"
            f"les tokens que tu achètes vraiment\\."
        )

    async def _cmd_watch_position(self, mint: str):
        if not mint or len(mint) < 32:
            await self._send_reply("❌ `/watch <mint>`")
            return
        try:
            data = await self.sell_generator._fetch_token_data(mint)
            if not data or data.get("price", 0) == 0:
                await self._send_reply("❌ Token non trouvé")
                return
            self.sell_generator.add_position(
                mint=mint, symbol="?",
                entry_price=data["price"],
                entry_mc=data["market_cap"],
                entry_liquidity=data["liquidity"],
                entry_buy_ratio=data["buy_ratio"],
                entry_volume_1h=data["volume_1h"],
                source="manual",
            )
            await self._send_reply(
                f"✅ *Position ajoutée*\n"
                f"MC: `${data['market_cap']/1000:.0f}K`"
            )
        except Exception as e:
            await self._send_reply(f"❌ {self._esc(str(e))}")

    async def _cmd_close(self, symbol_or_mint: str):
        if not symbol_or_mint:
            await self._send_reply("❌ `/close SYMBOL`")
            return
        positions = self.sell_generator.get_positions()
        target_mint = None
        if symbol_or_mint in positions:
            target_mint = symbol_or_mint
        else:
            for mint, pos in positions.items():
                if pos["symbol"].upper() == symbol_or_mint.upper():
                    target_mint = mint
                    break
        if not target_mint:
            await self._send_reply(f"❌ Position introuvable")
            return
        pos = positions[target_mint]
        self.sell_generator.remove_position(target_mint)
        await self._send_reply(
            f"✅ *Position fermée*\n"
            f"${self._esc(pos['symbol'])} \\| max `\\+{pos['max_gain']:.0f}%`"
        )

    async def _cmd_wallets(self):
        stats = self.wallet_discovery.get_stats()
        await self._send_reply(
            f"🔍 *WALLET DISCOVERY*\n━━━━━━━━━━━━━━\n\n"
            f"Trackés: `{stats['wallets_tracked']}`\n"
            f"Bulls analysés: `{stats['bulls_analyzed']}`\n"
            f"Candidats: `{stats['candidates_ready']}`\n\n"
            f"💡 `/candidates` pour voir top"
        )

    async def _cmd_candidates(self):
        candidates = self.wallet_discovery.get_top_candidates(10)
        if not candidates:
            await self._send_reply(
                f"🔍 *Candidats vides*\n\n"
                f"Besoin de 3\\+ bulls et 60%\\+ WR"
            )
            return
        lines = [f"🔍 *TOP {len(candidates)} CANDIDATS*", f"━━━━━━━━━━━━━━", ""]
        for i, c in enumerate(candidates, 1):
            short = c["wallet"][:8] + "\\.\\.\\." + c["wallet"][-4:]
            lines.append(f"`{i}\\.` `{short}`")
            lines.append(f"  Bulls: `{c['bulls_hit']}` \\| WR: `{c['win_rate']:.0f}%`")
            lines.append(f"  Avg gain: `\\+{c['avg_gain']:.0f}%`\n")
        await self._send_reply("\n".join(lines))

    async def _cmd_optimize(self):
        stats = self.auto_optimizer.get_stats()
        config = self.auto_optimizer.get_current_config()
        lines = [
            f"🎯 *AUTO\\-OPTIMIZER*",
            f"━━━━━━━━━━━━━━",
            f"Optimisations: `{stats['total_optimizations']}`\n",
            f"⚙️ *Config :*",
        ]
        for k, v in config.items():
            lines.append(f"  {self._esc(k)}: `{v}`")
        await self._send_reply("\n".join(lines))

    async def _cmd_social(self, args: str):
        parts = args.split()
        if not parts:
            await self._send_reply("❌ `/social SYMBOL [MINT]`")
            return

        symbol = parts[0].upper()
        mint = parts[1] if len(parts) > 1 else None

        await self._send_reply(f"🐦 Analyse `${self._esc(symbol)}`\\.\\.\\.")

        result = await self.social_score.analyze_token(symbol, mint)
        emoji = self.social_score.get_score_emoji(result["score"])

        lines = [
            f"🐦 *SOCIAL SCORE*",
            f"━━━━━━━━━━━━━━",
            f"",
            f"{emoji} *${self._esc(symbol)}*",
            f"",
            f"📊 Score: *`{result['score']}/100`* \\({self._esc(result['level'])}\\)",
            f"",
            f"📈 Mentions 1h: `{result['mentions_1h']}`",
            f"📈 Mentions 24h: `{result['mentions_24h']}`",
            f"👥 Utilisateurs: `{result['unique_users']}`",
            f"",
            f"✅ Positif: `{result['sentiment_pos']}%`",
            f"❌ Négatif: `{result['sentiment_neg']}%`",
            f"",
            f"⚡ Vélocité: `{result['velocity']:.1f}x`",
            f"🗑️ Spam: `{result['spam_ratio']}%`",
        ]

        if result["trending"]:
            lines.append(f"🔥 *TRENDING !*")

        if result["influencers"]:
            lines.append(f"\n👥 *INFLUENCEURS :*")
            for inf in result["influencers"]:
                lines.append(f"  Tier {inf['tier']}: @{self._esc(inf['username'])}")

        await self._send_reply("\n".join(lines))

    async def _cmd_report(self):
        await self._send_reply("📊 Génération du rapport\\.\\.\\.")
        try:
            await self.csv_exporter.force_daily_report()
            await self._send_reply("✅ Rapport envoyé")
        except Exception as e:
            await self._send_reply(f"❌ {self._esc(str(e))}")

    async def _cmd_admin(self):
        stats = self.admin_security.get_stats()
        admins = self.admin_security.get_authorized_admins()

        lines = [
            f"🔐 *ADMIN SECURITY*",
            f"━━━━━━━━━━━━━━",
            f"",
            f"Admins: `{stats['authorized_admins']}`",
            f"Commandes: `{stats['total_commands']}`",
            f"Blacklistés: `{stats['blacklisted']}`",
            f"Violations: `{stats['total_violations']}`",
            f"",
            f"👥 *Admins :*",
        ]

        for admin in admins:
            lines.append(f"  `{admin}`")

        await self._send_reply("\n".join(lines))

    async def _cmd_pause(self):
        self.paused = True
        await self._send_reply("⏸ *Bot en pause*")
        if self.dashboard:
            self.dashboard.add_event("Bot en pause")

    async def _cmd_resume(self):
        self.paused = False
        await self._send_reply("▶️ *Bot repris*")
        if self.dashboard:
            self.dashboard.add_event("Bot repris")

    async def _cmd_help(self):
        msg = (
            "🤖 *MemeSniper v13\\.1 FINAL*\n"
            "━━━━━━━━━━━━━━\n\n"
            "📊 *Info :*\n"
            "/status /stats /alertes\n"
            "/bullrun /backtest\n\n"
            "💼 *Portfolio :*\n"
            "/buy `SYM AMT` /sell `SYM [PNL]`\n"
            "/portfolio /pnl /trades\n\n"
            "🔔 *Watchlist :*\n"
            "/watchmc `SYM 500K`\n"
            "/watchpump `SYM 100`\n"
            "/watchdrop `SYM 30`\n"
            "/unwatch `SYM` /watchlist\n\n"
            "💰 *Sell Signals :*\n"
            "/positions /watch `MINT`\n"
            "/close `SYM` /clearpositions\n\n"
            "📊 *Stratégies :*\n"
            "/strategies /strategy `NAME`\n"
            "/compare\n\n"
            "🔍 *Discovery :*\n"
            "/wallets /candidates /optimize\n\n"
            "🐦 *Social :*\n"
            "/social `SYMBOL`\n\n"
            "🔍 *Analyse :*\n"
            "/check `MINT`\n\n"
            "🧠 *ML :*\n"
            "/win `SYM PCT` /loss `SYM PCT`\n"
            "/mlstats\n\n"
            "🔐 *Système :*\n"
            "/report /admin\n"
            "/pause /resume /help"
        )
        await self._send_reply(msg)

    async def _send_reply(self, text: str):
        await self.alert_sender._send_telegram(text)

    def _esc(self, text: str) -> str:
        special = r'_*[]()~`>#+-=|{}.!'
        return "".join(f"\\{c}" if c in special else c for c in str(text))

    async def handle_new_token_ws(self, token_data: dict):
        if self.paused:
            return
        address = token_data.get("address", "")
        if not address or address in self.alerted_tokens:
            return
        if address in self.processing_tokens:
            return
        symbol = token_data.get("symbol", "???")
        logger.info(f"[WS] 🆕 {symbol} ({address[:8]}...)")
        if self.dashboard:
            self.dashboard.add_event(f"Nouveau: {symbol}")
        await asyncio.sleep(45)
        await self._analyze_and_alert(address, source="websocket")

    async def handle_new_token_polling(self, token: dict):
        if self.paused:
            return
        address = (
            token.get("tokenAddress")
            or token.get("address")
            or token.get("baseToken", {}).get("address", "")
        )
        if not address or address in self.alerted_tokens:
            return
        if address in self.processing_tokens:
            return
        await self._analyze_and_alert(address, source="polling")

    async def handle_new_token_raydium(self, token_data: dict):
        if self.paused:
            return
        address = token_data.get("address", "") or token_data.get("mint", "")
        if not address or address in self.alerted_tokens:
            return
        if address in self.processing_tokens:
            return
        source = token_data.get("source", "raydium")
        symbol = token_data.get("symbol", "?")
        liq = token_data.get("liquidity", 0)
        self.raydium_tokens += 1
        logger.info(f"[RAYDIUM] {symbol} | Liq: ${liq:,.0f}")
        if self.dashboard:
            self.dashboard.add_event(f"Raydium: {symbol}")
        await self._analyze_and_alert(address, source=f"raydium_{source}")

    async def handle_momentum_token(self, token_data: dict):
        try:
            if self.paused:
                return
            mint = token_data["mint"]
            symbol = token_data["symbol"]
            pct = token_data["trigger_pct"]
            trigger = token_data["trigger"]
            quality = token_data.get("quality_score", 0)

            safety = await self.token_safety.full_safety_check(mint)
            if not safety.get("safe") and safety.get("score", 0) < 3:
                return

            emoji = "🔥🔥🔥" if pct >= 500 else "🔥🔥" if pct >= 200 else "🔥"
            msg = (
                f"{emoji} *MOMENTUM* {emoji}\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💎 *${self._esc(symbol)}*\n"
                f"📈 *\\+{pct:.0f}%* en {self._esc(trigger)}\n"
                f"💎 Quality: `{quality}/100`\n"
                f"💰 MC: `${token_data['market_cap']/1000:.0f}K`\n"
                f"💧 Liq: `${token_data['liquidity']/1000:.0f}K`\n\n"
                f"⚠️ *DYOR*\n`{mint}`"
            )
            buttons = {"inline_keyboard": [[
                {"text": "🚀 Photon", "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"},
                {"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"},
            ]]}
            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.momentum_alerts += 1
            if self.dashboard:
                self.dashboard.add_event(f"🔥 MOMENTUM ${symbol} +{pct:.0f}%")
        except Exception as e:
            logger.error(f"Momentum handler : {e}")

    async def handle_sell_signal(self, signal_data: dict):
        try:
            symbol = signal_data["symbol"]
            mint = signal_data["mint"]
            pnl = signal_data["pnl_pct"]
            signals = signal_data["signals"]
            confidence = signal_data["confidence"]

            has_sl = any(s["type"] == "SL" for s in signals)
            emoji = "🚨🚨🚨" if has_sl else "⚠️"

            msg = (
                f"{emoji} *SELL SIGNAL*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💎 *${self._esc(symbol)}*\n"
                f"📊 PnL: `{pnl:+.0f}%`\n"
                f"🛡️ Confiance: `{confidence}/100`\n\n"
                f"⚠️ *Signaux :*\n"
            )
            for sig in signals[:3]:
                msg += f"  • {self._esc(sig['message'])}\n"
            msg += f"\n`{mint}`"

            buttons = {"inline_keyboard": [[
                {"text": "💱 Jupiter", "url": f"https://jup.ag/swap/{mint}-SOL"},
                {"text": "💱 Photon", "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"},
            ]]}

            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.sell_alerts_sent += 1
            if self.dashboard:
                self.dashboard.add_event(f"💰 SELL ${symbol} PnL {pnl:+.0f}%")
        except Exception as e:
            logger.error(f"Sell handler : {e}")

    async def handle_dump_signal(self, dump_data: dict):
        try:
            symbol = dump_data["symbol"]
            mint = dump_data["mint"]
            pct = dump_data["trigger_pct"]
            trigger = dump_data["trigger"]
            severity = dump_data["severity"]

            emoji_map = {
                "COLLAPSE": "💀💀💀", "MAJOR_DUMP": "📉📉",
                "PANIC_SELL": "😱", "CRASH": "📉",
            }
            emoji = emoji_map.get(severity, "📉")

            msg = (
                f"{emoji} *DUMP DETECTED*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💎 *${self._esc(symbol)}*\n"
                f"📉 *{pct:.0f}%* en {self._esc(trigger)}\n"
                f"⚠️ Sévérité: *{self._esc(severity)}*\n"
                f"🟢 Buy ratio: `{dump_data['buy_ratio_1h']}%`\n"
                f"💰 MC: `${dump_data['market_cap']/1000:.0f}K`\n\n"
                f"`{mint}`"
            )

            buttons = {"inline_keyboard": [[
                {"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"},
            ]]}

            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.dump_alerts_sent += 1

            if self.dashboard:
                self.dashboard.add_event(f"📉 DUMP ${symbol} {pct:.0f}%")
        except Exception as e:
            logger.error(f"Dump handler : {e}")

    async def handle_whale_sell_signal(self, sell_data: dict):
        try:
            symbol = sell_data["symbol"]
            mint = sell_data["mint"]
            amount = sell_data["amount_usd"]
            severity = sell_data["severity"]
            is_alpha = sell_data.get("is_alpha", False)
            cascade = sell_data.get("cascade", False)

            emoji = "🐋🚨" if severity == "GIGA_SELL" else "🐋"

            msg = (
                f"{emoji} *WHALE SELL*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💎 *${self._esc(symbol)}*\n"
                f"💸 Montant: `${amount:,.0f}`\n"
                f"⚠️ Type: *{self._esc(severity)}*\n"
            )
            if is_alpha:
                msg += f"🐋 *ALPHA WALLET !*\n"
            if cascade:
                msg += f"🌊 *CASCADE ({sell_data['cascade_count']})*\n"

            msg += (
                f"\n📊 PnL 5m: `{sell_data['change_5m']:+.1f}%`\n"
                f"🟢 Buy ratio: `{sell_data['buy_ratio']}%`\n\n"
                f"`{mint}`"
            )

            buttons = {"inline_keyboard": [[
                {"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"},
            ]]}

            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.whale_sell_alerts_sent += 1

            if self.dashboard:
                self.dashboard.add_event(f"🐋 WHALE SELL ${symbol} ${amount:,.0f}")
        except Exception as e:
            logger.error(f"Whale sell handler : {e}")

    async def handle_watch_triggered(self, alert_data: dict):
        try:
            watch = alert_data["watch"]
            current = alert_data["current"]
            symbol = alert_data["symbol"]
            mint = alert_data["mint"]

            type_emoji = {
                "MC_TARGET": "🎯", "PUMP": "🚀", "DROP": "📉",
                "PRICE": "💰", "VOLUME": "📊",
            }.get(watch["type"], "🔔")

            msg = (
                f"{type_emoji} *WATCHLIST ALERT*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"💎 *${self._esc(symbol)}*\n"
                f"Type: *{self._esc(watch['type'])}*\n"
                f"Cible: `{watch['target']}`\n\n"
                f"💰 Prix: `${current.get('price', 0):.8f}`\n"
                f"💵 MC: `${current.get('market_cap', 0)/1000:.0f}K`\n"
                f"📊 Vol 24h: `${current.get('volume_24h', 0)/1000:.0f}K`\n\n"
                f"`{mint}`"
            )

            buttons = {"inline_keyboard": [[
                {"text": "🚀 Photon", "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"},
                {"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"},
            ]]}

            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.watchlist_alerts_sent += 1

            if self.dashboard:
                self.dashboard.add_event(f"🔔 WATCH ${symbol} {watch['type']}")
        except Exception as e:
            logger.error(f"Watch handler : {e}")

    async def _analyze_and_alert(self, address: str, source: str):
        if self.paused:
            return
        if not address or not isinstance(address, str):
            return
        if address in self.alerted_tokens:
            return
        if address in self.processing_tokens:
            return

        self.processing_tokens.add(address)

        try:
            self.tokens_analyzed += 1

            analysis = await self.analyzer.analyze_token(address)
            if not analysis:
                return

            safety = await self.token_safety.full_safety_check(address)
            if self.dashboard:
                self.dashboard.record_safety(safety)

            if not safety.get("safe", True):
                reason = safety.get("reasons", ["Unknown"])[0]
                logger.warning(f"🚫 SAFETY {address[:8]}... {reason}")
                if self.dashboard:
                    self.dashboard.add_event(f"🚫 {reason[:40]}")
                return

            analysis["safety"] = safety
            score = float(analysis.get("score", 0))
            symbol = analysis.get("symbol", "???")

            twitter_signal = self.twitter_tracker.get_token_twitter_signal(address)
            if not twitter_signal and symbol and symbol != "???":
                twitter_signal = self.twitter_tracker.get_symbol_twitter_signal(symbol)

            if twitter_signal:
                score = min(10.0, score + float(twitter_signal.get("bonus", 0)))
                analysis["score"] = score
                analysis["twitter_signal"] = twitter_signal

            ml_features = self.ml_scorer.extract_features(analysis, analysis, safety)
            ml_bonus = self.ml_scorer.get_ml_bonus(ml_features)
            if ml_bonus != 0.0:
                score = round(max(0.0, min(10.0, score + ml_bonus)), 2)
                analysis["score"] = score
                analysis["ml_bonus"] = ml_bonus
                analysis["ml_features"] = ml_features

            logger.info(
                f"[SCORE] {symbol} {score:.1f}/10 | "
                f"Safety:{safety.get('score', '?')}/10 | src:{source}"
            )

            min_score = self.auto_optimizer.get_min_score()
            if source.startswith("twitter_"):
                if "TIER1" in source:
                    min_score = 6.0
                elif "TIER2" in source:
                    min_score = 6.5
                elif "TIER3" in source:
                    min_score = 7.0
            elif source.startswith("copy_"):
                copy_wallets = analysis.get("alpha_wallet_list", [])
                if copy_wallets:
                    min_score = min([get_copy_threshold(w) for w in copy_wallets])
                else:
                    if "TIER1_5" in source:
                        min_score = 6.0
                    elif "TIER1" in source:
                        min_score = 5.5
                    elif "TIER2" in source:
                        min_score = 6.5

            if score < min_score:
                return

            decision = self.alert_sender.decision_eng.decide(analysis)
            if decision["action"] == "IGNORE":
                logger.info(
                    f"[DECISION] {symbol} IGNORÉ : "
                    f"{decision.get('reason', 'raison inconnue')}"
                )
                return

            chart_url = None
            try:
                chart_url = await self.chart_screenshot.get_chart_url(address)
            except Exception:
                pass

            sent = await self.alert_sender.send_alert(
                analysis, decision=decision, chart_url=chart_url
            )

            if sent:
                self.alerted_tokens[address] = time.time()
                self.alerts_sent += 1
                self._trim_alerted_tokens()
                self.perf_tracker.record_alert(analysis, decision)

                if decision["action"] == "ACHÈTE":
                    self.position_tracker.add_position(
                        analysis, decision, decision["amount_eur"]
                    )
                    # v13.1 : PLUS d'ajout auto au sell tracker
                    # Utilise /watch <mint> manuellement si tu achètes vraiment

                logger.info(f"[ALERT] ✅ {symbol} {score:.1f}/10 → {decision['action']}")
                if self.dashboard:
                    self.dashboard.add_event(
                        f"🚨 {decision['tier']}: {symbol} {score:.1f}/10"
                    )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[ANALYZE] {address[:8]}: {e}", exc_info=True)
        finally:
            self.processing_tokens.discard(address)

    def _trim_alerted_tokens(self):
        if len(self.alerted_tokens) <= self.max_alerted:
            return
        newest = dict(sorted(
            self.alerted_tokens.items(),
            key=lambda x: x[1], reverse=True
        )[:250])
        self.alerted_tokens = newest


async def cleanup_all(bot: MemeSniper):
    logger.info("[CLEANUP] 🛑 Arrêt en cours...")

    try:
        bot.perf_tracker.flush()
    except Exception as e:
        logger.error(f"[CLEANUP] perf: {e}")

    modules_to_stop = [
        ("WebSocket",         bot.ws_client),
        ("TokenSafety",       bot.token_safety),
        ("RadyiumMonitor",    bot.raydium_monitor),
        ("MomentumDetector",  bot.momentum_detector),
        ("BullAnalyzer",      bot.bull_analyzer),
        ("SellGenerator",     bot.sell_generator),
        ("ChartScreenshot",   bot.chart_screenshot),
        ("WalletDiscovery",   bot.wallet_discovery),
        ("AutoOptimizer",     bot.auto_optimizer),
        ("PortfolioTracker",  bot.portfolio_tracker),
        ("DumpDetector",      bot.dump_detector),
        ("WhaleSellTracker",  bot.whale_sell_tracker),
        ("CSVExporter",       bot.csv_exporter),
        ("Watchlist",         bot.watchlist),
        ("AdminSecurity",     bot.admin_security),
        ("SocialScore",       bot.social_score),
        ("Dashboard",         bot.dashboard),
    ]

    for name, module in modules_to_stop:
        if module is None:
            continue
        try:
            if hasattr(module, "stop"):
                await module.stop()
                logger.info(f"[CLEANUP] ✅ {name}")
        except Exception as e:
            logger.error(f"[CLEANUP] {name}: {e}")

    try:
        if bot.http_session and not bot.http_session.closed:
            await bot.http_session.close()
    except Exception:
        pass

    try:
        if hasattr(bot.pump_monitor, "close"):
            await bot.pump_monitor.close()
    except Exception:
        pass

    modules_to_close = [
        bot.analyzer, bot.alert_sender, bot.position_tracker,
        bot.market_context, bot.alpha_tracker, bot.early_detector,
        bot.whale_inflow, bot.twitter_tracker, bot.whale_tracker,
    ]
    for module in modules_to_close:
        try:
            if hasattr(module, "close"):
                await module.close()
        except Exception:
            pass

    logger.info("[CLEANUP] 🎉 Arrêt complet")


if __name__ == "__main__":
    bot = MemeSniper()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("👋 Bot arrêté (Ctrl+C)")
        asyncio.run(cleanup_all(bot))
    except Exception as e:
        logger.error(f"💥 Erreur fatale : {e}", exc_info=True)
        asyncio.run(cleanup_all(bot))