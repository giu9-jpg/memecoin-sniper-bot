# main.py — v12.7 FINAL
# Bot Sniper Memecoin Solana - Ultimate Edition
# ═══════════════════════════════════════════════
# ✅ TokenSafety v1.2 (fix pump.fun timing)
# ✅ Bull Run Analyzer v1.0 (apprentissage auto)
# ✅ Backtester v1.0 (simulation historique)
# ✅ Sell Signal Generator v1.0 (quand vendre)
# ✅ Chart Screenshot v1.0 (photos dans alertes) 🆕
# ✅ Copy Trading + Early Detector + Whale Inflow
# ✅ Momentum Detector v1.2
# ✅ ML Scorer + Dashboard + Multi-DEX
# ❌ PAS de trading automatique

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
from modules.dashboard             import DashboardServer
from modules.raydium_monitor       import RadyiumMonitor
from modules.momentum_detector     import MomentumDetector
from modules.ml_scorer             import MLScorer
from modules.bull_run_analyzer     import BullRunAnalyzer
from modules.backtester            import Backtester
from modules.sell_signal_generator import SellSignalGenerator
from modules.chart_screenshot      import ChartScreenshot

from config.alpha_wallets        import (
    ALPHA_WALLETS,
    get_all_wallets,
    get_copy_threshold,
)

from config.alpha_accounts       import (
    ALPHA_ACCOUNTS,
    get_all_accounts as get_all_twitter_accounts,
)


# ═══════════════════════════════════════════════════════
# CONSTANTES
# ═══════════════════════════════════════════════════════

POLLING_INTERVAL     = 30
HEALTH_CHECK_EVERY   = 300
POSITION_CHECK_EVERY = 60
MARKET_CHECK_EVERY   = 180
ALPHA_CHECK_EVERY    = 300
COPY_TRADING_EVERY   = 180
TWITTER_CHECK_EVERY  = 300
STATS_EVERY          = 3600
MEMORY_CLEANUP_EVERY = 1800
COMMAND_POLL_EVERY   = 2
MIN_SCORE            = 7.5


# ═══════════════════════════════════════════════════════
# BOT PRINCIPAL
# ═══════════════════════════════════════════════════════

class MemeSniper:

    def __init__(self):

        self.config = load_config()

        self.market_context  = MarketContext()
        self.alpha_tracker   = AlphaTracker()
        self.perf_tracker    = PerformanceTracker()
        self.early_detector  = EarlyDetector()
        self.whale_inflow    = WhaleInflowTracker()
        self.twitter_tracker = TwitterTracker()

        self.token_safety = TokenSafety(self.config.solana_rpc_url)

        self.ml_scorer = MLScorer()

        # ── Bull Run Analyzer v12.4 ───────────────────
        self.bull_analyzer = BullRunAnalyzer()

        # ── Backtester v12.5 ──────────────────────────
        self.backtester = Backtester(self.bull_analyzer)

        # ── Sell Signal Generator v12.6 ───────────────
        self.sell_generator = SellSignalGenerator(
            alert_callback=self.handle_sell_signal
        )
        self.sell_alerts_sent = 0

        # ── Chart Screenshot v12.7 ────────────────────
        self.chart_screenshot = ChartScreenshot()

        self.analyzer = TokenAnalyzer(
            alpha_tracker=self.alpha_tracker,
            early_detector=self.early_detector,
            whale_inflow=self.whale_inflow,
        )

        self.alert_sender = AlertSender(
            market_context=self.market_context
        )

        self.whale_tracker    = WhaleTracker()
        self.pump_monitor     = PumpFunMonitor()

        self.raydium_monitor = RadyiumMonitor()

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
            self.dashboard = DashboardServer(
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

    # ═══════════════════════════════════════════════════
    # DÉMARRAGE
    # ═══════════════════════════════════════════════════

    async def run(self):
        """Point d'entrée principal du bot."""

        self.http_session = aiohttp.ClientSession()

        try:
            await self.token_safety.start()
            logger.info("🛡️ TokenSafety v1.2 : ACTIF")
        except Exception as e:
            logger.error(f"❌ Impossible de démarrer TokenSafety : {e}")
            raise

        try:
            await self.raydium_monitor.start()
            logger.info("🔄 RadyiumMonitor : ACTIF")
        except Exception as e:
            logger.error(f"❌ Impossible de démarrer RadyiumMonitor : {e}")

        try:
            await self.momentum_detector.start()
            logger.info("🔥 MomentumDetector v1.2 : ACTIF")
        except Exception as e:
            logger.error(f"❌ Impossible de démarrer MomentumDetector : {e}")

        try:
            await self.bull_analyzer.start()
            logger.info("🎯 BullRunAnalyzer v1.0 : ACTIF")
        except Exception as e:
            logger.error(f"❌ Impossible de démarrer BullRunAnalyzer : {e}")

        try:
            await self.sell_generator.start()
            logger.info("💰 SellSignalGenerator v1.0 : ACTIF")
        except Exception as e:
            logger.error(f"❌ Impossible de démarrer SellSignalGenerator : {e}")

        try:
            await self.chart_screenshot.start()
            logger.info("📸 ChartScreenshot v1.0 : ACTIF")
        except Exception as e:
            logger.error(f"❌ Impossible de démarrer ChartScreenshot : {e}")

        total_wallets = len(get_all_wallets())
        t1            = len(ALPHA_WALLETS.get("TIER1",   []))
        t15           = len(ALPHA_WALLETS.get("TIER1_5", []))
        t2            = len(ALPHA_WALLETS.get("TIER2",   []))

        twitter_count = len(get_all_twitter_accounts())
        t1_tw         = len(ALPHA_ACCOUNTS.get("TIER1", []))
        t2_tw         = len(ALPHA_ACCOUNTS.get("TIER2", []))
        t3_tw         = len(ALPHA_ACCOUNTS.get("TIER3", []))

        ml_stats = self.ml_scorer.get_stats()

        logger.info("🚀 MemeSniper v12.7 FINAL démarré !")
        logger.info(f"   Score minimum      : {MIN_SCORE}/10")
        logger.info(f"   Smart Signals      : ACTIVÉS")
        logger.info(f"   Market Context     : ACTIF")
        logger.info(f"   Anti-Rug Safety    : ACTIF (v1.2)")
        logger.info(f"   Bull Analyzer      : ACTIF (v1.0)")
        logger.info(f"   Backtester         : ACTIF (v1.0)")
        logger.info(f"   Sell Signals       : ACTIF (v1.0)")
        logger.info(f"   Chart Screenshot   : ACTIF (v1.0)")
        logger.info(
            f"   Alpha Wallets      : ACTIF "
            f"({total_wallets} wallets | "
            f"T1:{t1} T1.5:{t15} T2:{t2})"
        )
        logger.info(f"   Copy Trading       : ACTIF")
        logger.info(f"   Early Detector     : ACTIF (v9.1)")
        logger.info(f"   Whale Inflow       : ACTIF (v9.2)")
        logger.info(
            f"   Twitter Tracker    : ACTIF "
            f"({twitter_count} comptes | "
            f"T1:{t1_tw} T2:{t2_tw} T3:{t3_tw})"
        )
        logger.info(f"   Performance Track  : ACTIF (v7.1)")
        logger.info(f"   Multi-Timeframe    : ACTIF")
        logger.info(f"   PumpPortal WS      : ACTIF (v2.1) + attente 45s")
        logger.info(f"   Polling Fallback   : ACTIF (v2.3)")
        logger.info(f"   Multi-DEX          : ACTIF (Raydium+Birdeye)")
        logger.info(f"   Momentum Detector  : ACTIF (v1.2 filtres avancés)")
        logger.info(
            f"   ML Scorer          : ACTIF "
            f"({ml_stats.get('trades', 0)} trades | "
            f"ready: {ml_stats.get('ready', False)})"
        )
        logger.info(f"   Commandes Telegram : ACTIF")

        if self.dashboard:
            logger.info(
                f"   Dashboard Web      : ACTIF → "
                f"http://{self.config.dashboard.host}:"
                f"{self.config.dashboard.port}"
            )
        else:
            logger.info(f"   Dashboard Web      : DÉSACTIVÉ")

        logger.info(f"   Trading Auto       : DÉSACTIVÉ")

        try:
            await self.market_context.fetch_market_data()
            sig = self.market_context.get_market_signal()
            logger.info(
                f"   📊 Marché : {sig['regime']} | "
                f"BTC {sig['btc_change_24h']:+.1f}% | "
                f"SOL {sig['sol_change_24h']:+.1f}% | "
                f"FG {sig['fear_greed']}"
            )
        except Exception as e:
            logger.warning(f"   ⚠️ Market context indisponible : {e}")

        try:
            stats = self.perf_tracker.get_stats()
            logger.info(
                f"   📈 Historique : {stats['total_alerts']} alertes | "
                f"Win rate : {stats['win_rate']}%"
            )
        except Exception as e:
            logger.warning(f"   ⚠️ Performance tracker : {e}")

        try:
            await self.alert_sender.send_startup_message()
        except Exception as e:
            logger.warning(f"   ⚠️ Message startup Telegram : {e}")

        try:
            await self._init_telegram_offset()
        except Exception as e:
            logger.warning(f"   ⚠️ Init Telegram offset : {e}")

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

    # ═══════════════════════════════════════════════════
    # BOUCLES PRINCIPALES
    # ═══════════════════════════════════════════════════

    async def _run_websocket(self):
        try:
            self.ws_active = True
            logger.info("[WS] Démarrage PumpPortal WebSocket...")
            await self.ws_client.start()
        except asyncio.CancelledError:
            logger.info("[WS] Annulé proprement")
        except Exception as e:
            logger.error(f"[WS] Erreur fatale : {e}")
        finally:
            self.ws_active = False
            logger.warning("[WS] ❌ WebSocket inactif — polling actif")

    async def _run_polling_fallback(self):
        logger.info(f"[POLLING] Backup {POLLING_INTERVAL}s actif")

        while True:
            try:
                tokens = await self.pump_monitor.get_new_tokens()
                for token in tokens:
                    await self.handle_new_token_polling(token)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[POLLING] Erreur : {e}")
            await asyncio.sleep(POLLING_INTERVAL)

    async def _run_raydium_monitor(self):
        await asyncio.sleep(30)
        logger.info("[RAYDIUM] 🔄 Multi-DEX monitor démarré")

        try:
            await self.raydium_monitor.monitor_loop(
                callback=self.handle_new_token_raydium
            )
        except asyncio.CancelledError:
            logger.info("[RAYDIUM] Annulé")
        except Exception as e:
            logger.error(f"[RAYDIUM] Erreur fatale : {e}")

    async def _run_market_updater(self):
        logger.info(f"[MARKET] Updater actif ({MARKET_CHECK_EVERY}s)")

        while True:
            await asyncio.sleep(MARKET_CHECK_EVERY)
            try:
                await self.market_context.fetch_market_data()
                sig = self.market_context.get_market_signal()
                logger.info(
                    f"[MARKET] {sig['regime']} | "
                    f"BTC {sig['btc_change_24h']:+.1f}% | "
                    f"SOL {sig['sol_change_24h']:+.1f}% | "
                    f"FG {sig['fear_greed']}"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MARKET] Erreur : {e}")

    async def _run_alpha_updater(self):
        logger.info(f"[ALPHA] Tracker actif ({ALPHA_CHECK_EVERY}s)")
        await asyncio.sleep(60)

        while True:
            try:
                await self.alpha_tracker.check_alpha_wallets()
                n = len(self.alpha_tracker.token_buyers)
                logger.info(f"[ALPHA] {n} token(s) tracké(s)")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ALPHA] Erreur : {e}")
            await asyncio.sleep(ALPHA_CHECK_EVERY)

    async def _run_alpha_copy_trading(self):
        logger.info(
            f"[COPY] 🐋 Alpha copy-trading actif "
            f"({COPY_TRADING_EVERY}s)"
        )
        await asyncio.sleep(120)

        while True:
            try:
                async def on_alpha_buy(
                    token: str, wallet: str, tier: str
                ):
                    self.copy_trades += 1
                    tier_str = tier or "UNKNOWN"

                    logger.info(
                        f"[COPY] 🚨 {tier_str} "
                        f"{wallet[:8]}... → achat {token[:8]}..."
                    )

                    if self.dashboard:
                        self.dashboard.add_event(
                            f"Copy trading: {tier_str} {wallet[:8]}..."
                        )

                    if token not in self.alerted_tokens:
                        await self._analyze_and_alert(
                            token, source=f"copy_{tier_str}",
                        )

                new_buys = await self.alpha_tracker.check_new_alpha_buys(
                    callback=on_alpha_buy
                )

                if new_buys:
                    logger.info(
                        f"[COPY] 📊 {len(new_buys)} "
                        f"nouveau(x) achat(s) alpha"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[COPY] Erreur : {e}")
            await asyncio.sleep(COPY_TRADING_EVERY)

    async def _run_twitter_tracker(self):
        logger.info(
            f"[TWITTER] 🐦 Tracker actif ({TWITTER_CHECK_EVERY}s)"
        )
        await asyncio.sleep(180)

        while True:
            try:
                async def on_twitter_signal(signal: dict):
                    self.twitter_signals += 1

                    tier     = signal.get("tier", "UNKNOWN")
                    username = signal.get("username", "?")
                    symbols  = signal.get("symbols", [])
                    addrs    = signal.get("addresses", [])

                    logger.info(
                        f"[TWITTER] 🚨 {tier} @{username} → "
                        f"CA:{len(addrs)} "
                        f"SYM:{','.join(symbols) if symbols else '-'}"
                    )

                    if self.dashboard:
                        self.dashboard.add_event(
                            f"Twitter {tier}: @{username}"
                        )

                    for address in addrs:
                        if address not in self.alerted_tokens:
                            await self._analyze_and_alert(
                                address, source=f"twitter_{tier}",
                            )

                signals = await self.twitter_tracker.check_all_accounts(
                    callback=on_twitter_signal
                )

                if signals:
                    logger.info(
                        f"[TWITTER] 📊 "
                        f"{len(signals)} nouveau(x) signal(s)"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[TWITTER] Erreur : {e}")
            await asyncio.sleep(TWITTER_CHECK_EVERY)

    async def _run_whale_tracker(self):
        logger.info("[WHALE] 🐋 Tracker démarré (60s)")

        while True:
            try:
                signals = await self.whale_tracker.check_whales()

                for signal in signals:
                    addr = signal.get("token_address", "")
                    if not addr or addr in self.alerted_tokens:
                        continue

                    label = signal.get("whale_label", "?")
                    amt   = signal.get("amount_usd", 0)

                    logger.info(
                        f"[WHALE] 🐋 {label} → "
                        f"{addr[:8]}... (${amt:,.0f})"
                    )

                    if self.dashboard:
                        self.dashboard.add_event(
                            f"Whale: {label} ${amt:,.0f}"
                        )

                    await self._analyze_and_alert(addr, source="whale")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WHALE] Erreur : {e}")
            await asyncio.sleep(60)

    async def _run_position_tracker(self):
        logger.info(
            f"[POSITIONS] Tracker actif ({POSITION_CHECK_EVERY}s)"
        )
        await asyncio.sleep(30)

        while True:
            try:
                await self.position_tracker.check_all_positions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[POSITIONS] Erreur : {e}")
            await asyncio.sleep(POSITION_CHECK_EVERY)

    async def _run_stats_reporter(self):
        logger.info(f"[STATS] Reporter actif (toutes les heures)")
        await asyncio.sleep(STATS_EVERY)

        while True:
            try:
                stats_msg = self.perf_tracker.get_summary_message()
                await self.alert_sender._send_telegram(
                    stats_msg, buttons=None
                )
                logger.info("[STATS] 📊 Rapport horaire envoyé")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[STATS] Erreur : {e}")
            await asyncio.sleep(STATS_EVERY)

    async def _run_memory_cleanup(self):
        logger.info(
            f"[MEMORY] Cleanup actif ({MEMORY_CLEANUP_EVERY}s)"
        )
        await asyncio.sleep(600)

        while True:
            try:
                self.alpha_tracker.cleanup_old_data()
                self.early_detector.cleanup_old()
                self.whale_inflow.cleanup_cache()
                self.twitter_tracker.cleanup_old_data()

                self._trim_alerted_tokens()

                collected = gc.collect()

                logger.info(
                    f"[MEMORY] 🧹 "
                    f"alerted={len(self.alerted_tokens)} | "
                    f"processing={len(self.processing_tokens)} | "
                    f"alpha_tokens="
                    f"{len(self.alpha_tracker.token_buyers)} | "
                    f"early="
                    f"{len(self.early_detector.recent_tokens)} | "
                    f"whale_cache="
                    f"{len(self.whale_inflow.cache)} | "
                    f"twitter_mentions="
                    f"{len(self.twitter_tracker.token_mentions)} | "
                    f"pump_seen="
                    f"{len(self.pump_monitor.seen_tokens)} | "
                    f"ws_seen="
                    f"{len(self.ws_client.seen_tokens)} | "
                    f"raydium_seen="
                    f"{len(self.raydium_monitor.seen_tokens)} | "
                    f"bulls={len(self.bull_analyzer.bulls)} | "
                    f"positions={self.sell_generator.get_positions_count()} | "
                    f"gc={collected}"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[MEMORY] Erreur : {e}")
            await asyncio.sleep(MEMORY_CLEANUP_EVERY)

    async def _run_health_check(self):
        logger.info(
            f"[HEALTH] Health check actif ({HEALTH_CHECK_EVERY}s)"
        )
        await asyncio.sleep(60)

        while True:
            try:
                uptime = int((time.time() - self.start_time) / 60)
                ws_status = "✅" if self.ws_active else "❌"
                pause_status = "⏸ PAUSE" if self.paused else "▶️ ACTIF"

                n_pos = len([
                    p for p in
                    self.position_tracker.positions.values()
                    if not p.get("closed")
                ])

                try:
                    sig    = self.market_context.get_market_signal()
                    regime = sig["regime"]
                except Exception:
                    regime = "N/A"

                ml_st = self.ml_scorer.get_stats()
                sell_st = self.sell_generator.get_stats()

                logger.info(
                    f"[HEALTH] "
                    f"{pause_status} | "
                    f"Uptime:{uptime}min | "
                    f"WS:{ws_status} | "
                    f"Analysés:{self.tokens_analyzed} | "
                    f"Alertes:{self.alerts_sent} | "
                    f"Copy:{self.copy_trades} | "
                    f"Twitter:{self.twitter_signals} | "
                    f"Raydium:{self.raydium_tokens} | "
                    f"Momentum:{self.momentum_alerts} | "
                    f"Bulls:{len(self.bull_analyzer.bulls)} | "
                    f"Sells:{sell_st['positions_open']}pos/{sell_st['total_signals']}sig | "
                    f"ML:{ml_st.get('trades', 0)} trades | "
                    f"Positions:{n_pos} | "
                    f"Marché:{regime} | "
                    f"Safety:✅"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[HEALTH] Erreur : {e}")
            await asyncio.sleep(HEALTH_CHECK_EVERY)

    # ═══════════════════════════════════════════════════
    # COMMANDES TELEGRAM
    # ═══════════════════════════════════════════════════

    async def _init_telegram_offset(self):
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return

        url = f"https://api.telegram.org/bot{token}/getUpdates"

        try:
            async with self.http_session.get(
                url,
                params={"timeout": 1},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    updates = data.get("result", [])
                    if updates:
                        self.telegram_offset = updates[-1]["update_id"] + 1
                        logger.info(
                            f"[CMD] Offset initialisé : "
                            f"{self.telegram_offset} "
                            f"({len(updates)} vieilles commandes ignorées)"
                        )
                    else:
                        logger.info("[CMD] Pas de vieilles commandes")
        except Exception as e:
            logger.debug(f"[CMD] Init offset error: {e}")

    async def _run_command_listener(self):
        logger.info(
            f"[CMD] 📱 Command listener actif ({COMMAND_POLL_EVERY}s)"
        )

        token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        if not token or not chat_id:
            logger.warning("[CMD] ❌ Credentials Telegram manquants")
            return

        url = f"https://api.telegram.org/bot{token}/getUpdates"

        while True:
            try:
                async with self.http_session.get(
                    url,
                    params={
                        "offset": self.telegram_offset,
                        "timeout": 20,
                    },
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        for update in data.get("result", []):
                            self.telegram_offset = update["update_id"] + 1

                            msg  = update.get("message", {})
                            text = msg.get("text", "").strip()
                            chat = str(
                                msg.get("chat", {}).get("id", "")
                            )

                            if chat != chat_id:
                                continue

                            if text.startswith("/"):
                                await self._handle_command(text)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[CMD] Listener error: {e}")
                await asyncio.sleep(5)
                continue
            await asyncio.sleep(COMMAND_POLL_EVERY)

    async def _handle_command(self, text: str):
        text_lower = text.lower().strip()

        logger.info(f"[CMD] 📥 Reçu : {text}")

        if text_lower.startswith("/check "):
            await self._cmd_check(text[7:].strip())
            return

        if text_lower.startswith("/win "):
            await self._cmd_win(text[5:].strip())
            return

        if text_lower.startswith("/loss "):
            await self._cmd_loss(text[6:].strip())
            return

        if text_lower.startswith("/backtest "):
            await self._cmd_backtest(text[10:].strip())
            return

        if text_lower.startswith("/watch "):
            await self._cmd_watch(text[7:].strip())
            return

        if text_lower.startswith("/close "):
            await self._cmd_close(text[7:].strip())
            return

        routes = {
            "/status":    self._cmd_status,
            "/stats":     self._cmd_stats,
            "/alertes":   self._cmd_alertes,
            "/mlstats":   self._cmd_mlstats,
            "/bullrun":   self._cmd_bullrun,
            "/backtest":  self._cmd_backtest,
            "/positions": self._cmd_positions,
            "/pause":     self._cmd_pause,
            "/resume":    self._cmd_resume,
            "/help":      self._cmd_help,
            "/start":     self._cmd_help,
        }

        handler = routes.get(text_lower)

        if handler:
            try:
                await handler()
            except Exception as e:
                logger.error(f"[CMD] Erreur handler {text}: {e}")
                await self._send_reply(f"❌ Erreur: {e}")
        else:
            await self._send_reply(
                f"❓ Commande inconnue: `{self._esc(text)}`\n"
                f"Tape /help pour la liste"
            )

    async def _cmd_status(self):
        uptime  = int(time.time() - self.start_time)
        h       = uptime // 3600
        m       = (uptime % 3600) // 60
        s       = uptime % 60

        ws_str    = "✅ Actif" if self.ws_active else "❌ Inactif"
        pause_str = "⏸ EN PAUSE" if self.paused else "▶️ Actif"

        try:
            sig = self.market_context.get_market_signal()
            regime = sig["regime"]
            btc = sig["btc_change_24h"]
        except Exception:
            regime = "N/A"
            btc = 0

        n_pos = len([
            p for p in self.position_tracker.positions.values()
            if not p.get("closed")
        ])

        ml_st = self.ml_scorer.get_stats()
        n_bulls = len(self.bull_analyzer.bulls)
        sell_st = self.sell_generator.get_stats()

        dash_str = ""
        if self.dashboard:
            dash_str = (
                f"\n📊 Dashboard: "
                f"http://{self.config.dashboard.host}:"
                f"{self.config.dashboard.port}\n"
            )
            dash_str = self._esc(dash_str)

        msg = (
            f"🤖 *MemeSniper v12\\.7 FINAL*\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"⏱ Uptime: `{h}h {m}m {s}s`\n"
            f"🔄 État: *{self._esc(pause_str)}*\n"
            f"📡 WebSocket: {ws_str}\n"
            f"🛡️ Anti\\-Rug: ✅ Actif \\(v1\\.2\\)\n"
            f"🔄 Multi\\-DEX: ✅ Actif\n"
            f"🔥 Momentum: ✅ Actif \\(v1\\.2\\)\n"
            f"🎯 Bull Analyzer: ✅ `{n_bulls}` bulls\n"
            f"📊 Backtester: ✅ Actif\n"
            f"💰 Sell Signals: ✅ `{sell_st['positions_open']}` positions\n"
            f"📸 Chart Photos: ✅ Actif\n"
            f"🧠 ML: {ml_st.get('trades', 0)} trades\n"
            f"{dash_str}\n"
            f"📊 *Activité:*\n"
            f"  Tokens analysés: `{self.tokens_analyzed}`\n"
            f"  Alertes envoyées: `{self.alerts_sent}`\n"
            f"  Sell alerts: `{self.sell_alerts_sent}`\n"
            f"  Copy trades: `{self.copy_trades}`\n"
            f"  Twitter signals: `{self.twitter_signals}`\n"
            f"  Raydium tokens: `{self.raydium_tokens}`\n"
            f"  Momentum alertes: `{self.momentum_alerts}`\n"
            f"  Positions ouvertes: `{n_pos}`\n\n"
            f"🌍 *Marché:*\n"
            f"  Régime: *{self._esc(regime)}*\n"
            f"  BTC 24h: `{btc:+.1f}%`\n"
        )

        await self._send_reply(msg)

    async def _cmd_stats(self):
        try:
            stats = self.perf_tracker.get_stats()

            msg = (
                f"📈 *Statistiques Performance*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"Total alertes: `{stats.get('total_alerts', 0)}`\n"
                f"Win rate: `{stats.get('win_rate', 0):.1f}%`\n"
                f"Wins: `{stats.get('wins', 0)}` ✅\n"
                f"Losses: `{stats.get('losses', 0)}` ❌\n\n"
                f"💎 *Par tier:*\n"
                f"  Ultimate: `{stats.get('ultimate', 0)}`\n"
                f"  Strong: `{stats.get('strong', 0)}`\n"
                f"  Good: `{stats.get('good', 0)}`\n"
                f"  Normal: `{stats.get('normal', 0)}`\n"
            )
            await self._send_reply(msg)
        except Exception as e:
            await self._send_reply(f"❌ Erreur stats: {self._esc(str(e))}")

    async def _cmd_alertes(self):
        if not self.alerted_tokens:
            await self._send_reply("📭 Aucune alerte envoyée encore")
            return

        sorted_alerts = sorted(
            self.alerted_tokens.items(),
            key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0,
            reverse=True
        )[:10]

        lines = ["📋 *10 dernières alertes:*\n"]
        lines.append("━━━━━━━━━━━━━━\n")

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
            lines.append(f"`{i}\\.` `{short}` \\- il y a {age_str}")

        await self._send_reply("\n".join(lines))

    async def _cmd_check(self, mint: str):
        if not mint or len(mint) < 32:
            await self._send_reply(
                "❌ Format: `/check <adresse_mint>`\n"
                "Exemple: `/check 7xKXtg2CW\\.\\.\\.`"
            )
            return

        await self._send_reply(
            f"🔍 Analyse de `{self._esc(mint[:16])}\\.\\.\\.` en cours\\.\\.\\."
        )

        try:
            safety = await self.token_safety.full_safety_check(mint)
            summary = self.token_safety.summary(safety)
            summary_esc = self._esc(summary)

            msg = (
                f"🛡️ *Résultat safety check:*\n"
                f"━━━━━━━━━━━━━━\n"
                f"```\n{summary_esc}\n```"
            )

            await self._send_reply(msg)
        except Exception as e:
            await self._send_reply(f"❌ Erreur: {self._esc(str(e))}")

    async def _cmd_win(self, args: str):
        parts = args.split()
        name  = parts[0] if parts else "?"

        try:
            pnl = float(parts[1]) if len(parts) > 1 else 100.0
        except ValueError:
            pnl = 100.0

        self.ml_scorer.record_result(
            token_name=name,
            is_win=True,
            pnl_pct=pnl,
        )

        stats = self.ml_scorer.get_stats()

        await self._send_reply(
            f"✅ *WIN enregistré \\!*\n\n"
            f"Token: `{self._esc(name)}`\n"
            f"PnL: `\\+{pnl:.0f}%`\n\n"
            f"🧠 ML: {stats['trades']} trades | "
            f"WR: {stats.get('win_rate', 0):.0f}%\n"
            f"Ready: {'✅' if stats.get('ready') else '❌ ' + str(stats.get('trades', 0)) + '/5'}"
        )

    async def _cmd_loss(self, args: str):
        parts = args.split()
        name  = parts[0] if parts else "?"

        try:
            pnl = float(parts[1]) if len(parts) > 1 else -30.0
        except ValueError:
            pnl = -30.0

        if pnl > 0:
            pnl = -pnl

        self.ml_scorer.record_result(
            token_name=name,
            is_win=False,
            pnl_pct=pnl,
        )

        stats = self.ml_scorer.get_stats()

        await self._send_reply(
            f"❌ *LOSS enregistré*\n\n"
            f"Token: `{self._esc(name)}`\n"
            f"PnL: `{pnl:.0f}%`\n\n"
            f"🧠 ML: {stats['trades']} trades | "
            f"WR: {stats.get('win_rate', 0):.0f}%\n"
            f"Ready: {'✅' if stats.get('ready') else '❌ ' + str(stats.get('trades', 0)) + '/5'}"
        )

    async def _cmd_mlstats(self):
        stats = self.ml_scorer.get_stats()

        if not stats.get("ready"):
            msg = (
                f"🧠 *ML Scorer*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"Trades enregistrés: `{stats.get('trades', 0)}`\n"
                f"État: ⏳ En apprentissage\n"
                f"Minimum requis: `5 trades`\n\n"
                f"💡 *Comment l'utiliser:*\n"
                f"  /win PEPE 250 → enregistre un \\+250%\n"
                f"  /loss DOGE 35 → enregistre un \\-35%\n\n"
                f"Après 5 trades, le ML ajuste\n"
                f"automatiquement les scores\\."
            )
        else:
            msg = (
                f"🧠 *ML Scorer — Statistiques*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"Trades: `{stats['trades']}`\n"
                f"Wins: `{stats['wins']}` ✅\n"
                f"Losses: `{stats['losses']}` ❌\n"
                f"Win Rate: `{stats['win_rate']:.1f}%`\n"
                f"PnL moyen: `{stats['avg_pnl']:+.1f}%`\n"
                f"Features apprises: `{stats['features']}`\n"
                f"État: ✅ Actif\n\n"
                f"Le ML ajuste les scores de\n"
                f"`{stats['features']}` patterns appris\\."
            )

        await self._send_reply(msg)

    async def _cmd_bullrun(self):
        """Commande /bullrun - Statistiques des bulls détectés"""
        stats = self.bull_analyzer.get_stats(days=7)

        if stats["total"] == 0:
            msg = (
                f"🎯 *Bull Run Analyzer*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"{self._esc(stats.get('message', 'Pas de données'))}\n\n"
                f"⏳ L'analyzer scanne toutes les 5 min\\.\n"
                f"Reviens dans quelques heures\\.\n\n"
                f"📊 Scans effectués: `{self.bull_analyzer.tokens_scanned}`"
            )
            await self._send_reply(msg)
            return

        lines = [
            f"🎯 *BULL RUN ANALYZER*",
            f"━━━━━━━━━━━━━━",
            f"",
            f"📊 Bulls \\(7j\\) : *{stats['total']}*",
            f"📈 Gain moyen : *\\+{stats['avg_gain']:.0f}%*",
            f"",
        ]

        if stats.get("hours"):
            lines.append(f"⏰ *TOP HEURES UTC :*")
            for h, count in stats["hours"][:3]:
                pct = round(count / stats["total"] * 100)
                lines.append(f"  `{h:02d}h` : {count} bulls \\({pct}%\\)")
            lines.append("")

        if stats.get("days_week"):
            lines.append(f"📅 *TOP JOURS :*")
            for d, count in stats["days_week"]:
                pct = round(count / stats["total"] * 100)
                lines.append(f"  {self._esc(d)} : {pct}%")
            lines.append("")

        if stats.get("mc_buckets"):
            lines.append(f"💰 *MARKET CAP :*")
            for bucket, count in stats["mc_buckets"][:3]:
                pct = round(count / stats["total"] * 100)
                lines.append(
                    f"  {self._esc(bucket)} : {pct}%"
                )
            lines.append("")

        if stats.get("liq_buckets"):
            lines.append(f"💧 *LIQUIDITÉ :*")
            for bucket, count in stats["liq_buckets"][:3]:
                pct = round(count / stats["total"] * 100)
                lines.append(
                    f"  {self._esc(bucket)} : {pct}%"
                )
            lines.append("")

        if stats.get("br_buckets"):
            lines.append(f"🟢 *BUY RATIO 1h :*")
            for bucket, count in stats["br_buckets"][:3]:
                pct = round(count / stats["total"] * 100)
                lines.append(
                    f"  {self._esc(bucket)} : {pct}%"
                )
            lines.append("")

        recos = self.bull_analyzer.get_recommendations()
        if recos:
            lines.append(f"🧠 *RECOMMANDATIONS :*")
            for r in recos[:5]:
                lines.append(f"  • {self._esc(r)}")
            lines.append("")

        if stats.get("top_5"):
            lines.append(f"🏆 *TOP 5 GAINERS 7j :*")
            for i, b in enumerate(stats["top_5"], 1):
                lines.append(
                    f"  `{i}\\.` ${self._esc(b['symbol'])} "
                    f"\\+{b['change_24h']:.0f}%"
                )

        msg = "\n".join(lines)
        await self._send_reply(msg)

    async def _cmd_backtest(self, args: str = ""):
        """Commande /backtest [min_liquidity] [days]"""
        parts = args.split() if args else []

        min_liquidity = 5_000
        days = 30

        try:
            if len(parts) >= 1:
                min_liquidity = int(parts[0])
            if len(parts) >= 2:
                days = int(parts[1])
        except ValueError:
            await self._send_reply(
                "❌ Usage : `/backtest [min_liquidity] [days]`\n"
                "Exemple : `/backtest 1000 7`"
            )
            return

        configs = [
            {
                "name": "Actuel",
                "min_liquidity": 5_000,
                "min_volume":    100_000,
                "min_buy_ratio": 55,
                "days": days,
            },
            {
                "name": "Custom",
                "min_liquidity": min_liquidity,
                "min_volume":    100_000,
                "min_buy_ratio": 55,
                "days": days,
            },
            {
                "name": "Aggressif",
                "min_liquidity": 1_000,
                "min_volume":    50_000,
                "min_buy_ratio": 50,
                "days": days,
            },
        ]

        results = self.backtester.compare_configs(configs)

        if results[0].get("total_bulls", 0) == 0:
            msg = (
                f"📊 *BACKTEST*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"{self._esc(results[0].get('message', 'Pas de données'))}\n\n"
                f"⏳ Le BullAnalyzer collecte les bulls\\.\n"
                f"Reviens dans quelques heures\\."
            )
            await self._send_reply(msg)
            return

        lines = [
            f"📊 *BACKTEST HISTORIQUE*",
            f"━━━━━━━━━━━━━━",
            f"",
            f"Période : `{days} jours`",
            f"Bulls totaux : `{results[0]['total_bulls']}`",
            f"",
        ]

        for res in results:
            name = res["name"]
            params = res.get("params", {})
            liq = params.get("min_liquidity", 0)

            lines.append(f"━━━━━━━━━━━━━━")
            lines.append(
                f"🎯 *{self._esc(name)}* "
                f"\\(liq ≥ ${liq/1000:.0f}K\\)"
            )
            lines.append(
                f"  Alertes : `{res['would_alert']}` "
                f"/`{res['total_bulls']}`"
            )
            lines.append(
                f"  Hit rate : `{res['hit_rate']:.1f}%`"
            )
            lines.append(
                f"  Gain moyen : `\\+{res['avg_gain']:.0f}%`"
            )
            lines.append("")

        best = results[0]
        if best.get("top_5"):
            lines.append(f"━━━━━━━━━━━━━━")
            lines.append(f"🏆 *TOP 5 CATCHÉS \\(config Actuel\\) :*")
            for i, b in enumerate(best["top_5"], 1):
                lines.append(
                    f"  `{i}\\.` ${self._esc(b['symbol'])} "
                    f"\\+{b['change_24h']:.0f}%"
                )
            lines.append("")

        if best.get("missed_5"):
            lines.append(f"❌ *TOP 5 RATÉS \\(config Actuel\\) :*")
            for i, b in enumerate(best["missed_5"], 1):
                liq = b.get("liquidity", 0)
                vol = b.get("volume_24h", 0)
                br  = b.get("buy_ratio_1h", 0)

                if liq < 5_000:
                    reason = f"liq trop basse \\(${liq/1000:.0f}K\\)"
                elif vol < 100_000:
                    reason = f"vol trop bas"
                elif br < 55:
                    reason = f"buy ratio {br:.0f}%"
                else:
                    reason = "MC trop élevé"

                lines.append(
                    f"  `{i}\\.` ${self._esc(b['symbol'])} "
                    f"\\+{b['change_24h']:.0f}% → {reason}"
                )

        msg = "\n".join(lines)
        await self._send_reply(msg)

    async def _cmd_positions(self):
        """Commande /positions - Voir positions surveillées"""
        positions = self.sell_generator.get_positions()

        if not positions:
            msg = (
                f"💰 *POSITIONS SURVEILLÉES*\n"
                f"━━━━━━━━━━━━━━\n\n"
                f"📭 Aucune position ouverte\\.\n\n"
                f"💡 *Pour ajouter une position :*\n"
                f"`/watch <mint>`\n\n"
                f"Exemple :\n"
                f"`/watch 7xKXtg2CW...`\n\n"
                f"⚡ Les alertes ACHÈTE ajoutent\n"
                f"automatiquement les positions\\."
            )
            await self._send_reply(msg)
            return

        lines = [
            f"💰 *POSITIONS SURVEILLÉES*",
            f"━━━━━━━━━━━━━━",
            f"",
            f"📊 Total : `{len(positions)}` positions",
            f"",
        ]

        for i, (mint, pos) in enumerate(list(positions.items())[:10], 1):
            elapsed = (time.time() - pos["entry_time"]) / 60
            if elapsed < 60:
                elapsed_str = f"{elapsed:.0f}min"
            else:
                elapsed_str = f"{elapsed/60:.1f}h"

            symbol = pos["symbol"]
            entry_mc = pos["entry_mc"]
            max_gain = pos["max_gain"]
            tps = len(pos["tp_triggered"])

            lines.append(f"━━━━━━━━━━━━━━")
            lines.append(
                f"`{i}\\.` *${self._esc(symbol)}*"
            )
            lines.append(
                f"  Entry MC : `${entry_mc/1000:.0f}K`"
            )
            lines.append(
                f"  Max gain : `\\+{max_gain:.0f}%`"
            )
            lines.append(
                f"  TPs : `{tps}/4` | SL : "
                f"{'🛑' if pos['sl_triggered'] else '✅'}"
            )
            lines.append(
                f"  Ouvert : `{elapsed_str}`"
            )
            lines.append("")

        lines.append(f"💡 `/close <symbol>` pour fermer")

        msg = "\n".join(lines)
        await self._send_reply(msg)

    async def _cmd_watch(self, mint: str):
        """Commande /watch <mint> - Ajouter position manuellement"""
        if not mint or len(mint) < 32:
            await self._send_reply(
                "❌ Format : `/watch <adresse_mint>`\n"
                "Exemple : `/watch 7xKXtg2CW\\.\\.\\.`"
            )
            return

        try:
            data = await self.sell_generator._fetch_token_data(mint)
            if not data or data.get("price", 0) == 0:
                await self._send_reply(
                    f"❌ Impossible de récupérer les données\\.\n"
                    f"Le token existe\\-t\\-il ?"
                )
                return

            self.sell_generator.add_position(
                mint=mint,
                symbol="?",
                entry_price=data["price"],
                entry_mc=data["market_cap"],
                entry_liquidity=data["liquidity"],
                entry_buy_ratio=data["buy_ratio"],
                entry_volume_1h=data["volume_1h"],
                source="manual",
            )

            await self._send_reply(
                f"✅ *Position ajoutée \\!*\n\n"
                f"Mint : `{mint[:16]}\\.\\.\\.`\n"
                f"Entry MC : `${data['market_cap']/1000:.0f}K`\n"
                f"Entry Liq : `${data['liquidity']/1000:.0f}K`\n\n"
                f"💰 Sell signals actifs\n"
                f"📱 Tu recevras une alerte quand vendre"
            )

        except Exception as e:
            await self._send_reply(f"❌ Erreur : {self._esc(str(e))}")

    async def _cmd_close(self, symbol_or_mint: str):
        """Commande /close <symbol> - Fermer position"""
        if not symbol_or_mint:
            await self._send_reply(
                "❌ Format : `/close <symbol>` ou `/close <mint>`"
            )
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
            await self._send_reply(
                f"❌ Position `{self._esc(symbol_or_mint)}` non trouvée\\."
            )
            return

        pos = positions[target_mint]
        self.sell_generator.remove_position(target_mint)

        await self._send_reply(
            f"✅ *Position fermée*\n\n"
            f"Token : *${self._esc(pos['symbol'])}*\n"
            f"Max gain : `\\+{pos['max_gain']:.0f}%`\n"
            f"TPs atteints : `{len(pos['tp_triggered'])}/4`"
        )

    async def _cmd_pause(self):
        self.paused = True
        await self._send_reply(
            "⏸ *Bot mis en pause*\n\n"
            "Les nouveaux tokens ne seront plus analysés\\.\n"
            "Tape /resume pour reprendre\\."
        )
        logger.warning("⏸ Bot mis en pause via Telegram")

        if self.dashboard:
            self.dashboard.add_event("Bot mis en pause")

    async def _cmd_resume(self):
        self.paused = False
        await self._send_reply(
            "▶️ *Bot repris \\!*\n\n"
            "Analyse des nouveaux tokens active\\."
        )
        logger.info("▶️ Bot repris via Telegram")

        if self.dashboard:
            self.dashboard.add_event("Bot repris")

    async def _cmd_help(self):
        msg = (
            "🤖 *MemeSniper v12\\.7 FINAL*\n"
            "━━━━━━━━━━━━━━\n\n"
            "📊 *Info:*\n"
            "/status \\- État du bot\n"
            "/stats \\- Performance\n"
            "/alertes \\- 10 dernières alertes\n"
            "/bullrun \\- Analyse des bulls\n"
            "/backtest \\- Simuler réglages\n\n"
            "💰 *Positions \\(Sell Signals\\)*\n"
            "/positions \\- Voir positions\n"
            "/watch `<mint>` \\- Surveiller token\n"
            "/close `<symbol>` \\- Fermer position\n\n"
            "🔍 *Analyse:*\n"
            "/check `<mint>` \\- Safety check\n\n"
            "🧠 *ML \\(apprentissage\\):*\n"
            "/win `<token>` `<pct>` \\- Trade gagnant\n"
            "/loss `<token>` `<pct>` \\- Trade perdant\n"
            "/mlstats \\- Stats du ML\n\n"
            "⚙️ *Contrôle:*\n"
            "/pause \\- Mettre en pause\n"
            "/resume \\- Reprendre\n"
            "/help \\- Cette aide\n"
        )
        await self._send_reply(msg)

    async def _send_reply(self, text: str):
        await self.alert_sender._send_telegram(text)

    def _esc(self, text: str) -> str:
        special = r'_*[]()~`>#+-=|{}.!'
        return "".join(
            f"\\{c}" if c in special else c
            for c in str(text)
        )

    # ═══════════════════════════════════════════════════
    # HANDLERS TOKENS ENTRANTS
    # ═══════════════════════════════════════════════════

    async def handle_new_token_ws(self, token_data: dict):
        """Nouveau token détecté via WebSocket."""
        if self.paused:
            return

        address = token_data.get("address", "")

        if not address or address in self.alerted_tokens:
            return

        if address in self.processing_tokens:
            return

        symbol = token_data.get("symbol", "???")

        logger.info(
            f"[WS] 🆕 Nouveau token : "
            f"{symbol} ({address[:8]}...)"
        )

        if self.dashboard:
            self.dashboard.add_event(f"Nouveau token: {symbol}")

        await asyncio.sleep(45)
        await self._analyze_and_alert(address, source="websocket")

    async def handle_new_token_polling(self, token: dict):
        """Nouveau token détecté via polling."""
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
        """Nouveau token détecté via Raydium/Birdeye."""
        if self.paused:
            return

        address = (
            token_data.get("address", "")
            or token_data.get("mint", "")
        )

        if not address or address in self.alerted_tokens:
            return

        if address in self.processing_tokens:
            return

        source = token_data.get("source", "raydium")
        symbol = token_data.get("symbol", "?")
        liq    = token_data.get("liquidity", 0)

        self.raydium_tokens += 1

        logger.info(
            f"[RAYDIUM] 🔄 {symbol} | "
            f"Liq: ${liq:,.0f} | Source: {source}"
        )

        if self.dashboard:
            self.dashboard.add_event(
                f"Raydium: {symbol} (${liq:,.0f})"
            )

        await self._analyze_and_alert(
            address, source=f"raydium_{source}"
        )

    # ═══════════════════════════════════════════════════
    # HANDLER MOMENTUM v1.2
    # ═══════════════════════════════════════════════════

    async def handle_momentum_token(self, token_data: dict):
        """Callback Momentum Detector"""
        try:
            if self.paused:
                return

            mint    = token_data["mint"]
            symbol  = token_data["symbol"]
            name    = token_data["name"]
            trigger = token_data["trigger"]
            pct     = token_data["trigger_pct"]
            mc      = token_data["market_cap"]
            liq     = token_data["liquidity"]
            vol     = token_data["volume_24h"]
            txns    = token_data["txns_1h"]

            quality = token_data.get("quality_score", 0)
            state   = token_data.get("momentum_state", "?")
            buys    = token_data.get("buys_1h", 0)
            sells   = token_data.get("sells_1h", 0)
            b_ratio = token_data.get("buy_ratio", 0) * 100

            safety = await self.token_safety.full_safety_check(mint)
            safety_score = safety.get("score", 0)

            if not safety.get("safe") and safety_score < 3:
                logger.info(
                    f"🔥 MOMENTUM {symbol} bloqué safety "
                    f"(score {safety_score})"
                )
                return

            emoji = "🔥🔥🔥" if pct >= 500 else "🔥🔥" if pct >= 200 else "🔥"

            state_emoji = {
                "ACCELERATING": "🚀",
                "STEADY":       "📈",
                "COOLING":      "🌡️",
                "REVERSING":    "⚠️",
            }.get(state, "❓")

            if quality >= 85:
                q_emoji = "💎"
            elif quality >= 75:
                q_emoji = "✅"
            elif quality >= 65:
                q_emoji = "👌"
            else:
                q_emoji = "⚠️"

            e_name    = self._esc(name)
            e_symbol  = self._esc(symbol)
            e_trigger = self._esc(trigger)
            e_state   = self._esc(state)

            msg = (
                f"{emoji} *MOMENTUM DETECTED* {emoji}\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"💎 *{e_name}* \\(${e_symbol}\\)\n\n"
                f"📈 *\\+{pct:.0f}%* en {e_trigger}\n"
                f"  • 5min : `{token_data['change_5m']:+.0f}%`\n"
                f"  • 1h   : `{token_data['change_1h']:+.0f}%`\n"
                f"  • 6h   : `{token_data['change_6h']:+.0f}%`\n"
                f"  • 24h  : `{token_data['change_24h']:+.0f}%`\n\n"
                f"{q_emoji} *Quality : `{quality}/100`*\n"
                f"{state_emoji} État : *{e_state}*\n\n"
                f"💰 MC        : `${mc/1000:.0f}K`\n"
                f"💧 Liquidité : `${liq/1000:.0f}K`\n"
                f"📊 Volume 24h: `${vol/1000:.0f}K`\n"
                f"🔄 Txns 1h   : `{txns}` \\({buys}b/{sells}s\\)\n"
                f"🟢 Buy Ratio : `{b_ratio:.0f}%`\n"
                f"🛡️ Safety    : `{safety_score:.1f}/10`\n\n"
                f"⚠️ *Pas de signal alpha — DYOR*\n\n"
                f"`{mint}`"
            )

            buttons = [
                [
                    {"text": "🚀 Photon", "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"},
                    {"text": "📊 Chart", "url": token_data.get("dex_url") or f"https://dexscreener.com/solana/{mint}"},
                ],
                [
                    {"text": "🔍 Safety", "url": f"https://rugcheck.xyz/tokens/{mint}"},
                    {"text": "💱 Jupiter", "url": f"https://jup.ag/swap/SOL-{mint}"},
                ],
                [
                    {"text": "🔎 Solscan", "url": f"https://solscan.io/token/{mint}"},
                    {"text": f"🐦 Twitter ${symbol}", "url": f"https://twitter.com/search?q=%24{symbol}"},
                ],
            ]

            # v12.7 : Tenter d'envoyer avec chart
            chart_url = None
            try:
                chart_url = await self.chart_screenshot.get_chart_url(mint)
            except Exception as e:
                logger.debug(f"Chart fetch error momentum : {e}")

            if chart_url:
                await self.alert_sender._send_telegram_photo(
                    photo_url=chart_url,
                    caption=msg,
                    buttons={"inline_keyboard": buttons},
                )
            else:
                await self.alert_sender._send_telegram(
                    msg, buttons={"inline_keyboard": buttons}
                )

            self.momentum_alerts += 1

            if self.dashboard:
                self.dashboard.add_event(
                    f"🔥 MOMENTUM ${symbol} +{pct:.0f}% "
                    f"(Q:{quality}) en {trigger}"
                )

            logger.info(
                f"✅ Alerte MOMENTUM envoyée : "
                f"${symbol} +{pct:.0f}% | "
                f"Q:{quality} | {state}"
            )
        except Exception as e:
            logger.error(f"Handler momentum error : {e}", exc_info=True)

    # ═══════════════════════════════════════════════════
    # HANDLER SELL SIGNAL v12.6
    # ═══════════════════════════════════════════════════

    async def handle_sell_signal(self, signal_data: dict):
        """Callback SellSignalGenerator - Envoie alerte de vente"""
        try:
            symbol       = signal_data["symbol"]
            mint         = signal_data["mint"]
            pnl          = signal_data["pnl_pct"]
            max_gain     = signal_data["max_gain"]
            elapsed_min  = signal_data["elapsed_min"]
            signals      = signal_data["signals"]
            recommend    = signal_data["recommended_action"]
            confidence   = signal_data["confidence"]
            current_mc   = signal_data["current_mc"]

            if pnl >= 100:
                pnl_emoji = "🚀"
            elif pnl >= 50:
                pnl_emoji = "💰"
            elif pnl >= 0:
                pnl_emoji = "📈"
            elif pnl >= -20:
                pnl_emoji = "📉"
            else:
                pnl_emoji = "🛑"

            has_sl = any(s["type"] == "SL" for s in signals)
            has_tp = any(s["type"] == "TP" for s in signals)

            if has_sl:
                urgency_emoji = "🚨🚨🚨"
                urgency_text = "URGENT"
            elif has_tp:
                urgency_emoji = "🎯"
                urgency_text = "TAKE PROFIT"
            else:
                urgency_emoji = "⚠️"
                urgency_text = "ATTENTION"

            e_symbol = self._esc(symbol)
            e_recommend = self._esc(recommend)

            msg_lines = [
                f"{urgency_emoji} *SELL SIGNAL* {urgency_emoji}",
                f"━━━━━━━━━━━━━━━━━━",
                f"",
                f"💎 Token : *${e_symbol}*",
                f"⏱ Ouvert : `{elapsed_min:.0f} min`",
                f"",
                f"{pnl_emoji} *PnL actuel : `{pnl:+.0f}%`*",
                f"📊 Max atteint : `\\+{max_gain:.0f}%`",
                f"💰 MC actuel : `${current_mc/1000:.0f}K`",
                f"",
                f"⚠️ *SIGNAUX \\({len(signals)}\\) :*",
            ]

            for sig in signals[:5]:
                sig_msg = self._esc(sig['message'])
                msg_lines.append(f"  • {sig_msg}")

            msg_lines.extend([
                f"",
                f"💡 *RECOMMANDATION :*",
                f"*{e_recommend}*",
                f"",
                f"🛡️ Confiance : `{confidence}/100`",
                f"",
                f"`{mint}`",
            ])

            msg = "\n".join(msg_lines)

            buttons = [
                [
                    {"text": "💱 VENDRE Jupiter",
                     "url": f"https://jup.ag/swap/{mint}-SOL"},
                    {"text": "💱 VENDRE Photon",
                     "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"},
                ],
                [
                    {"text": "📊 Chart",
                     "url": f"https://dexscreener.com/solana/{mint}"},
                ],
            ]

            await self.alert_sender._send_telegram(
                msg, buttons={"inline_keyboard": buttons}
            )

            self.sell_alerts_sent += 1

            if self.dashboard:
                self.dashboard.add_event(
                    f"💰 SELL ${symbol} PnL {pnl:+.0f}% "
                    f"({urgency_text})"
                )

            logger.info(
                f"💰 SELL alerte envoyée : ${symbol} "
                f"PnL {pnl:+.0f}% | Conf: {confidence}"
            )

        except Exception as e:
            logger.error(f"Handler sell signal error : {e}", exc_info=True)

    # ═══════════════════════════════════════════════════
    # ANALYSE + ALERTE — CŒUR DU BOT
    # ═══════════════════════════════════════════════════

    async def _analyze_and_alert(self, address: str, source: str):
        """Analyse un token et envoie une alerte Telegram"""

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
                logger.warning(
                    f"🚫 [SAFETY] Bloqué : "
                    f"{address[:8]}... | {reason}"
                )

                if self.dashboard:
                    self.dashboard.add_event(
                        f"🚫 Bloqué: {reason[:40]}"
                    )

                return

            analysis["safety"] = safety

            score        = float(analysis.get("score", 0))
            symbol       = analysis.get("symbol", "???")
            smart_count  = int(analysis.get("smart_count", 0))
            has_critical = bool(analysis.get("has_critical", False))
            alpha_count  = int(analysis.get("alpha_wallets", 0))
            whale_count  = int(analysis.get("whale_inflow_count", 0))
            giga_count   = int(analysis.get("giga_whale_count", 0))
            early_signal = analysis.get("early_signal")

            twitter_signal = (
                self.twitter_tracker.get_token_twitter_signal(address)
            )

            if not twitter_signal and symbol and symbol != "???":
                twitter_signal = (
                    self.twitter_tracker.get_symbol_twitter_signal(
                        symbol
                    )
                )

            if twitter_signal:
                twitter_bonus = float(
                    twitter_signal.get("bonus", 0)
                )
                score = min(10.0, score + twitter_bonus)

                analysis["score"]          = score
                analysis["twitter_signal"] = twitter_signal

            ml_bonus = 0.0
            ml_features = self.ml_scorer.extract_features(
                analysis, analysis, safety
            )
            ml_bonus = self.ml_scorer.get_ml_bonus(ml_features)

            if ml_bonus != 0.0:
                old_score = score
                score     = round(
                    max(0.0, min(10.0, score + ml_bonus)), 2
                )
                analysis["score"]       = score
                analysis["ml_bonus"]    = ml_bonus
                analysis["ml_features"] = ml_features
                logger.info(
                    f"🧠 ML | {symbol} | "
                    f"Score: {old_score:.1f} → {score:.1f} "
                    f"(bonus: {ml_bonus:+.2f})"
                )

            critical_tag = " 🚨CRITICAL" if has_critical else ""
            alpha_tag    = f" 🐋x{alpha_count}" if alpha_count else ""
            copy_tag     = (
                " 🚀COPY" if source.startswith("copy_") else ""
            )
            raydium_tag  = (
                " 🔄RAYDIUM" if source.startswith("raydium_") else ""
            )
            ml_tag       = (
                f" 🧠ML{ml_bonus:+.1f}" if ml_bonus != 0 else ""
            )

            twitter_tag = ""

            if source.startswith("twitter_"):
                tier_part = source.split("_", 1)[-1]
                twitter_tag = f" 🐦{tier_part}"
            elif twitter_signal:
                uname = twitter_signal.get("username", "")[:10]
                twitter_tag = f" 🐦@{uname}"

            whale_tag = ""

            if giga_count > 0:
                whale_tag = f" 🐳GIGAx{giga_count}"
            elif whale_count > 0:
                whale_tag = f" 🐳x{whale_count}"

            early_tag = ""

            if early_signal and early_signal.get("bonus", 0) > 0:
                early_tag = " ⚡EARLY"

            logger.info(
                f"[SCORE] {symbol} — {score:.1f}/10 "
                f"| Smart:{smart_count}"
                f"{critical_tag}{alpha_tag}{copy_tag}{raydium_tag}"
                f"{twitter_tag}{whale_tag}{early_tag}{ml_tag} "
                f"| Safety:{safety.get('score', '?')}/10 "
                f"| src:{source}"
            )

            min_score = MIN_SCORE

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
                    thresholds = [
                        get_copy_threshold(w)
                        for w in copy_wallets
                    ]
                    min_score = min(thresholds)
                else:
                    if "TIER1_5" in source:
                        min_score = 6.0
                    elif "TIER1" in source:
                        min_score = 5.5
                    elif "TIER2" in source:
                        min_score = 6.5

            if score < min_score:
                logger.debug(
                    f"[SCORE] {symbol} ignoré "
                    f"({score:.1f} < {min_score:.1f} requis "
                    f"| src:{source})"
                )
                return

            decision = self.alert_sender.decision_eng.decide(analysis)

            if decision["action"] == "IGNORE":
                logger.info(
                    f"[DECISION] {symbol} ignoré : "
                    f"{decision.get('reason', 'raison inconnue')}"
                )
                return

            # v12.7 : Récupérer le chart pour l'envoyer avec l'alerte
            chart_url = None
            try:
                chart_url = await self.chart_screenshot.get_chart_url(address)
            except Exception as e:
                logger.debug(f"Chart fetch error : {e}")

            sent = await self.alert_sender.send_alert(
                analysis, decision=decision, chart_url=chart_url,
            )

            if sent:
                self.alerted_tokens[address] = time.time()
                self.alerts_sent += 1

                self._trim_alerted_tokens()

                self.perf_tracker.record_alert(analysis, decision)

                if decision["action"] == "ACHÈTE":
                    self.position_tracker.add_position(
                        analysis,
                        decision,
                        decision["amount_eur"],
                    )

                    # ═══ SELL SIGNAL v12.6 ═══
                    try:
                        sell_data = await self.sell_generator._fetch_token_data(address)
                        if sell_data and sell_data.get("price", 0) > 0:
                            self.sell_generator.add_position(
                                mint=address,
                                symbol=symbol,
                                entry_price=sell_data["price"],
                                entry_mc=sell_data["market_cap"],
                                entry_liquidity=sell_data["liquidity"],
                                entry_buy_ratio=sell_data["buy_ratio"],
                                entry_volume_1h=sell_data["volume_1h"],
                                source=source,
                            )
                    except Exception as e:
                        logger.debug(f"Sell auto-add error : {e}")

                logger.info(
                    f"[ALERT] ✅ {symbol} {score:.1f}/10 "
                    f"→ {decision['action']} | "
                    f"tier:{decision['tier']} | "
                    f"montant:{decision['amount_eur']}€ | "
                    f"src:{source}"
                )

                if self.dashboard:
                    self.dashboard.add_event(
                        f"🚨 ALERTE {decision['tier']}: "
                        f"{symbol} {score:.1f}/10"
                    )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(
                f"[ANALYZE] Erreur {address[:8]}: {e}",
                exc_info=True,
            )
        finally:
            self.processing_tokens.discard(address)

    # ═══════════════════════════════════════════════════
    # HELPERS INTERNES
    # ═══════════════════════════════════════════════════

    def _trim_alerted_tokens(self):
        if len(self.alerted_tokens) <= self.max_alerted:
            return

        newest = dict(
            sorted(
                self.alerted_tokens.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:250]
        )

        removed = len(self.alerted_tokens) - len(newest)
        self.alerted_tokens = newest

        if removed > 0:
            logger.debug(
                f"[TRIM] {removed} tokens anciens purgés "
                f"(garde {len(newest)})"
            )


# ═══════════════════════════════════════════════════════
# CLEANUP GRACIEUX
# ═══════════════════════════════════════════════════════

async def cleanup_all(bot: MemeSniper):
    logger.info("[CLEANUP] 🛑 Arrêt en cours...")

    try:
        bot.perf_tracker.flush()
        logger.info("[CLEANUP] ✅ Performance tracker sauvegardé")
    except Exception as e:
        logger.error(f"[CLEANUP] perf_tracker.flush() : {e}")

    try:
        if hasattr(bot.ws_client, "stop"):
            await bot.ws_client.stop()
            logger.info("[CLEANUP] ✅ WebSocket arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] ws_client.stop() : {e}")

    try:
        if bot.token_safety:
            await bot.token_safety.stop()
            logger.info("[CLEANUP] ✅ TokenSafety arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] token_safety.stop() : {e}")

    try:
        if bot.raydium_monitor:
            await bot.raydium_monitor.stop()
            logger.info("[CLEANUP] ✅ RadyiumMonitor arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] raydium_monitor.stop() : {e}")

    try:
        if bot.momentum_detector:
            await bot.momentum_detector.stop()
            logger.info("[CLEANUP] ✅ MomentumDetector arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] momentum_detector.stop() : {e}")

    try:
        if bot.bull_analyzer:
            await bot.bull_analyzer.stop()
            logger.info("[CLEANUP] ✅ BullRunAnalyzer arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] bull_analyzer.stop() : {e}")

    try:
        if bot.sell_generator:
            await bot.sell_generator.stop()
            logger.info("[CLEANUP] ✅ SellSignalGenerator arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] sell_generator.stop() : {e}")

    try:
        if bot.chart_screenshot:
            await bot.chart_screenshot.stop()
            logger.info("[CLEANUP] ✅ ChartScreenshot arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] chart_screenshot.stop() : {e}")

    try:
        if bot.dashboard:
            await bot.dashboard.stop()
            logger.info("[CLEANUP] ✅ Dashboard arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] dashboard.stop() : {e}")

    try:
        if bot.http_session and not bot.http_session.closed:
            await bot.http_session.close()
            logger.info("[CLEANUP] ✅ HTTP session fermée")
    except Exception as e:
        logger.error(f"[CLEANUP] http_session.close() : {e}")

    try:
        if hasattr(bot.pump_monitor, "close"):
            await bot.pump_monitor.close()
            logger.info("[CLEANUP] ✅ Pump monitor fermé")
    except Exception as e:
        logger.error(f"[CLEANUP] pump_monitor.close() : {e}")

    modules_to_close = [
        ("analyzer",         bot.analyzer),
        ("alert_sender",     bot.alert_sender),
        ("position_tracker", bot.position_tracker),
        ("market_context",   bot.market_context),
        ("alpha_tracker",    bot.alpha_tracker),
        ("early_detector",   bot.early_detector),
        ("whale_inflow",     bot.whale_inflow),
        ("twitter_tracker",  bot.twitter_tracker),
        ("whale_tracker",    bot.whale_tracker),
    ]

    for name, module in modules_to_close:
        try:
            if hasattr(module, "close"):
                await module.close()
                logger.info(f"[CLEANUP] ✅ {name} fermé")
        except Exception as e:
            logger.error(f"[CLEANUP] {name}.close() : {e}")

    logger.info("[CLEANUP] 🎉 Arrêt complet — à bientôt !")


# ═══════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    bot = MemeSniper()

    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("👋 Bot arrêté par l'utilisateur (Ctrl+C)")
        asyncio.run(cleanup_all(bot))
    except Exception as e:
        logger.error(f"💥 Erreur fatale : {e}", exc_info=True)
        asyncio.run(cleanup_all(bot))