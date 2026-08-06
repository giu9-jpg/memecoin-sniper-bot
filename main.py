# main.py — v14.1-EVOLUTION
# ═══════════════════════════════════════════════════════════════════
# MemeSniper v14.1 — Auto-Evolution Architecture
# ✅ Event Store | Feature Store | Auto-ML | Strategy Optimizer | Drift Guard
# ✅ gRPC Ready | Dev Tracker | Bundle Detector | Hot-reload Config
# ✅ Intégration complète modules existants (v13.5.1 heritage)
# ═══════════════════════════════════════════════════════════════════

import asyncio
import gc
import json
import time
import os
import aiohttp
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Core utils ────────────────────────────────────────────────────
from utils.logger import logger
from utils.config_loader import load_config
from utils.helpers import get_config_hash

# ── Existing modules (v13.5.1 heritage) ──────────────────────────
from modules.pump_portal_ws import PumpPortalWebSocket
from modules.pump_fun_monitor import PumpFunMonitor
from modules.token_analyzer import TokenAnalyzer
from modules.alert_sender import AlertSender
from modules.whale_tracker import WhaleTracker
from modules.position_tracker import PositionTracker
from modules.market_context import MarketContext
from modules.alpha_tracker import AlphaTracker
from modules.performance_tracker import PerformanceTracker
from modules.early_detector import EarlyDetector
from modules.whale_inflow import WhaleInflowTracker
from modules.twitter_tracker import TwitterTracker
from modules.token_safety import TokenSafety
from modules.dashboard_v2 import DashboardServerV2
from modules.raydium_monitor import RadyiumMonitor
from modules.momentum_detector import MomentumDetector
from modules.ml_scorer import MLScorer
from modules.bull_run_analyzer import BullRunAnalyzer
from modules.backtester import Backtester
from modules.backtester_v2 import BacktesterV2
from modules.sell_signal_generator import SellSignalGenerator
from modules.chart_screenshot import ChartScreenshot
from modules.wallet_discovery import WalletDiscovery
from modules.auto_optimizer import AutoOptimizer
from modules.portfolio_tracker import PortfolioTracker
from modules.dump_detector import DumpDetector
from modules.whale_sell_tracker import WhaleSellTracker
from modules.csv_exporter import CSVExporter
from modules.watchlist import Watchlist
from modules.admin_security import AdminSecurity
from modules.social_score import SocialScore
from modules.trade_assistant import TradeAssistant
from modules.simulator import Simulator
from modules.callback_handler import CallbackHandler

# ── Config ───────────────────────────────────────────────────────
from config.alpha_wallets import (
    ALPHA_WALLETS, get_all_wallets, get_copy_threshold, get_wallet_tier,
)
from config.alpha_accounts import (
    ALPHA_ACCOUNTS, get_all_accounts as get_all_twitter_accounts,
)

# ── NEW: Evolution modules ───────────────────────────────────────
from modules.evolution.event_store import get_event_store, log_event
from modules.evolution.feature_store import get_feature_store
from modules.evolution.auto_ml import get_auto_ml, maybe_retrain
from modules.evolution.strategy_optimizer import get_strategy_optimizer
from modules.evolution.drift_guard import get_drift_guard
from modules.evolution.evolution_orchestrator import start_evolution, stop_evolution

# ═══════════════════════════════════════════════════════════════════
# CONSTANTES & CONFIG
# ═══════════════════════════════════════════════════════════════════

POLLING_INTERVAL = 30
HEALTH_CHECK_EVERY = 300
POSITION_CHECK_EVERY = 60
MARKET_CHECK_EVERY = 180
ALPHA_CHECK_EVERY = 300
COPY_TRADING_EVERY = 180
TWITTER_CHECK_EVERY = 300
STATS_EVERY = 86400
MEMORY_CLEANUP_EVERY = 1800
COMMAND_POLL_EVERY = 2

# Filtre horaire UTC (inchangé v13.5)
HOUR_CONFIG = {
    14: (7.5, "🔥 PEAK"), 15: (7.5, "🔥 PEAK"), 16: (7.5, "🔥 PEAK"),
    17: (7.5, "🔥 PEAK"), 18: (7.5, "🔥 PEAK"),
    19: (7.8, "📈 GOOD"), 20: (7.8, "📈 GOOD"), 21: (7.8, "📈 GOOD"),
    2: (8.0, "🌏 ASIA"), 3: (8.0, "🌏 ASIA"), 4: (8.0, "🌏 ASIA"),
    6: (8.5, "😴 SLOW"), 7: (8.5, "😴 SLOW"), 8: (8.5, "😴 SLOW"),
    9: (8.5, "😴 SLOW"), 10: (8.5, "😴 SLOW"), 11: (8.5, "😴 SLOW"),
    12: (8.2, "⬆️ WAKE"), 13: (8.0, "⬆️ WAKE"),
}

def get_hourly_min_score(base_score: float) -> tuple[float, str]:
    hour = time.gmtime().tm_hour
    if hour in HOUR_CONFIG:
        hour_score, label = HOUR_CONFIG[hour]
        final = max(base_score, hour_score)
        return final, label
    return base_score, "📊 NORMAL"


# ═══════════════════════════════════════════════════════════════════
# CLASS MEMESNIPER — v14.1 EVOLUTION
# ═══════════════════════════════════════════════════════════════════

class MemeSniper:
    def __init__(self):
        self.config = load_config()
        self.config_hash = get_config_hash()
        
        # ── Evolution Systems (initialisés en premier) ─────────────
        self.event_store = get_event_store()
        self.feature_store = get_feature_store()
        self.auto_ml = get_auto_ml()
        self.strategy_optimizer = get_strategy_optimizer()
        self.drift_guard = get_drift_guard()
        
        # ── Modules existants ─────────────────────────────────────
        self.market_context = MarketContext()
        self.alpha_tracker = AlphaTracker()
        self.perf_tracker = PerformanceTracker()
        self.early_detector = EarlyDetector()
        self.whale_inflow = WhaleInflowTracker()
        self.twitter_tracker = TwitterTracker()
        self.token_safety = TokenSafety(self.config.solana_rpc_url)
        self.ml_scorer = MLScorer()
        self.bull_analyzer = BullRunAnalyzer()
        self.backtester = Backtester(self.bull_analyzer)
        self.backtester_v2 = BacktesterV2(self.bull_analyzer)
        self.chart_screenshot = ChartScreenshot()
        self.wallet_discovery = WalletDiscovery(self.bull_analyzer)
        self.portfolio_tracker = PortfolioTracker()
        self.admin_security = AdminSecurity()
        self.social_score = SocialScore()
        
        # Sell & Risk
        self.sell_generator = SellSignalGenerator(alert_callback=self.handle_sell_signal)
        self.sell_alerts_sent = 0
        self.dump_detector = DumpDetector(alert_callback=self.handle_dump_signal)
        self.dump_alerts_sent = 0
        self.whale_sell_tracker = WhaleSellTracker(
            alert_callback=self.handle_whale_sell_signal,
            alpha_wallets=get_all_wallets(),
        )
        self.whale_sell_alerts_sent = 0
        self.watchlist = Watchlist(alert_callback=self.handle_watch_triggered)
        self.watchlist_alerts_sent = 0
        
        # Analyzer & Alert
        self.analyzer = TokenAnalyzer(
            alpha_tracker=self.alpha_tracker,
            early_detector=self.early_detector,
            whale_inflow=self.whale_inflow,
        )
        self.alert_sender = AlertSender(market_context=self.market_context)
        
        # Trading Assistant
        self.trade_assistant = TradeAssistant(
            portfolio_tracker=self.portfolio_tracker,
            alert_sender=self.alert_sender,
            ml_scorer=self.ml_scorer,
        )
        self.alert_sender.set_trade_assistant(self.trade_assistant)
        
        # Simulator (paper trading)
        self.simulator = Simulator(ml_scorer=self.ml_scorer)
        
        # Callback Handler (boutons inline + SL/TP auto)
        self.callback_handler = CallbackHandler(
            bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            trade_assistant=self.trade_assistant,
            ml_scorer=self.ml_scorer,
            performance_tracker=self.perf_tracker,
            portfolio_tracker=self.portfolio_tracker,
            sell_generator=self.sell_generator,
        )
        
        # Optimizers & Exporters
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
        
        # Monitors
        self.whale_tracker = WhaleTracker()
        self.pump_monitor = PumpFunMonitor()
        self.raydium_monitor = RadyiumMonitor()
        self.momentum_detector = MomentumDetector(alert_callback=self.handle_momentum_token)
        self.momentum_alerts = 0
        self.position_tracker = PositionTracker(alert_sender=self.alert_sender)
        
        # WebSocket
        self.ws_client = PumpPortalWebSocket(token_callback=self.handle_new_token_ws)
        
        # Dashboard
        self.dashboard = None
        if self.config.dashboard.enabled:
            self.dashboard = DashboardServerV2(
                bot=self,
                host=self.config.dashboard.host,
                port=self.config.dashboard.port,
            )
        
        # HTTP & State
        self.http_session = None
        self.alerted_tokens = {}
        self.processing_tokens = set()
        self.paused = False
        self.ws_active = False
        self.start_time = time.time()
        self.tokens_analyzed = 0
        self.alerts_sent = 0
        self.copy_trades = 0
        self.twitter_signals = 0
        self.raydium_tokens = 0
        self.max_alerted = 500
        self.telegram_offset = 0
        self.fast_alerts = 0
        self.hour_filtered = 0
        
        # Evolution state
        self._evolution_started = False
        self._last_config_reload = 0

    # ═══════════════════════════════════════════════════════════════
    # RUN — Point d'entrée principal
    # ═══════════════════════════════════════════════════════════════
    
    async def run(self):
        self.http_session = aiohttp.ClientSession()
        
        # ── 1. Démarre modules core ────────────────────────────────
        modules_to_start = [
            ("TokenSafety v1.4", self.token_safety),
            ("RadyiumMonitor", self.raydium_monitor),
            ("MomentumDetector v1.2", self.momentum_detector),
            ("BullRunAnalyzer", self.bull_analyzer),
            ("SellSignalGenerator v1.4", self.sell_generator),
            ("ChartScreenshot", self.chart_screenshot),
            ("WalletDiscovery", self.wallet_discovery),
            ("AutoOptimizer", self.auto_optimizer),
            ("PortfolioTracker", self.portfolio_tracker),
            ("DumpDetector", self.dump_detector),
            ("WhaleSellTracker", self.whale_sell_tracker),
            ("CSVExporter", self.csv_exporter),
            ("Watchlist", self.watchlist),
            ("AdminSecurity", self.admin_security),
            ("SocialScore", self.social_score),
            ("TradeAssistant", self.trade_assistant),
            ("Simulator", self.simulator),
        ]
        
        for name, module in modules_to_start:
            try:
                await module.start()
                logger.info(f"✅ {name} : ACTIF")
            except Exception as e:
                logger.error(f"❌ {name} : {e}")
        
        # ── 2. Démarre Evolution Orchestrator ─────────────────────
        try:
            await start_evolution()
            self._evolution_started = True
            logger.info("🧬 Evolution Orchestrator : ACTIF")
        except Exception as e:
            logger.error(f"❌ Evolution Orchestrator : {e}")
        
        # ── 3. Log startup ────────────────────────────────────────
        total_wallets = len(get_all_wallets())
        t1 = len(ALPHA_WALLETS.get("TIER1", []))
        t15 = len(ALPHA_WALLETS.get("TIER1_5", []))
        t2 = len(ALPHA_WALLETS.get("TIER2", []))
        twitter_count = len(get_all_twitter_accounts())
        t1_tw = len(ALPHA_ACCOUNTS.get("TIER1", []))
        t2_tw = len(ALPHA_ACCOUNTS.get("TIER2", []))
        t3_tw = len(ALPHA_ACCOUNTS.get("TIER3", []))
        
        ml_stats = self.ml_scorer.get_stats()
        opt_config = self.auto_optimizer.get_current_config()
        base_min_score = opt_config.get("min_score", 7.5)
        hour_score, hour_label = get_hourly_min_score(base_min_score)
        
        logger.info("🚀 MemeSniper v14.1-EVOLUTION démarré !")
        logger.info(f" Score min (base) : {base_min_score}/10")
        logger.info(f" Heure UTC : {time.gmtime().tm_hour}h — {hour_label} (score ≥ {hour_score})")
        logger.info(f" Alpha Wallets: {total_wallets} (T1:{t1} T1.5:{t15} T2:{t2})")
        logger.info(f" Twitter : {twitter_count} (T1:{t1_tw} T2:{t2_tw} T3:{t3_tw})")
        logger.info(f" ML : {ml_stats.get('trades', 0)} trades")
        logger.info(f" ⚡ Speed adaptatif : ACTIF")
        logger.info(f" 🕐 Filtre horaire : ACTIF")
        logger.info(f" 🎯 Bouton SELL : ACTIF")
        logger.info(f" 🐋 Micro whale : ACTIF")
        logger.info(f" 🛡️ SL auto inline : ACTIF")
        logger.info(f" 🧬 Auto-Evolution : ACTIF (Event Store, Feature Store, Auto-ML, Strategy Opt, Drift Guard)")
        
        if self.dashboard:
            logger.info(
                f" Dashboard v2 : http://{self.config.dashboard.host}:"
                f"{self.config.dashboard.port}"
            )
        
        # Market context initial
        try:
            await self.market_context.fetch_market_data()
            sig = self.market_context.get_market_signal()
            logger.info(
                f" 📊 Marché : {sig['regime']} | "
                f"BTC {sig['btc_change_24h']:+.1f}% | "
                f"FG {sig['fear_greed']}"
            )
        except Exception as e:
            logger.warning(f" ⚠️ Market : {e}")
        
        # Performance historique
        try:
            stats = self.perf_tracker.get_stats()
            logger.info(
                f" 📈 Historique : {stats['total_alerts']} alertes | "
                f"WR : {stats['win_rate']}%"
            )
        except Exception:
            pass
        
        # Startup Telegram
        try:
            await self.alert_sender.send_startup_message()
        except Exception as e:
            logger.warning(f" ⚠️ Startup Telegram : {e}")
        
        # Telegram offset
        try:
            await self._init_telegram_offset()
        except Exception as e:
            logger.warning(f" ⚠️ Init offset : {e}")
        
        logger.info(" ⚙️ Lancement des boucles...")
        
        # ── 4. Lance toutes les boucles ───────────────────────────
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
            self._run_evolution_maintenance(),  # NEW: maintenance evolution
        ]
        
        if self.dashboard:
            tasks.append(self.dashboard.start())
        
        await asyncio.gather(*tasks, return_exceptions=True)

    # ═══════════════════════════════════════════════════════════════
    # BOUCLES PRINCIPALES
    # ═══════════════════════════════════════════════════════════════
    
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
            await self.raydium_monitor.monitor_loop(callback=self.handle_new_token_raydium)
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
                base_score = self.auto_optimizer.get_min_score()
                hour_score, hour_label = get_hourly_min_score(base_score)
                logger.info(
                    f"[MARKET] {sig['regime']} | "
                    f"BTC {sig['btc_change_24h']:+.1f}% | "
                    f"FG {sig['fear_greed']} | "
                    f"Heure: {hour_label} score≥{hour_score}"
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
        logger.info("[STATS] Actif 24h — silencieux si aucune activité")
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
                    await self.alert_sender._send_telegram(delta_header + stats_msg, buttons=None)
                    logger.info(f"[STATS] Rapport 24h envoyé (+{delta_alerts} alertes)")
                else:
                    logger.info("[STATS] Rapport ignoré — aucune activité")
                
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
                sim_stats = self.simulator.get_stats()
                
                logger.info(
                    f"[MEMORY] alerted={len(self.alerted_tokens)} | "
                    f"proc={len(self.processing_tokens)} | "
                    f"bulls={len(self.bull_analyzer.bulls)} | "
                    f"pos={self.sell_generator.get_positions_count()} | "
                    f"disco={wd_stats['wallets_tracked']} | "
                    f"watch={wl_stats['active_watches']} | "
                    f"sim={sim_stats['open_positions']}o/"
                    f"{sim_stats['closed_positions']}c | "
                    f"fast={self.fast_alerts} | "
                    f"hfilt={self.hour_filtered} | "
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
                evolution_status = "🧬 ON" if self._evolution_started else "🧬 OFF"
                trading_paused = "🛑" if self.drift_guard.trading_paused else "✅"
                evolution_paused = "🛑" if self.drift_guard.auto_evolution_paused else "✅"
                
                try:
                    regime = self.market_context.get_market_signal()["regime"]
                except Exception:
                    regime = "N/A"
                
                base_score = self.auto_optimizer.get_min_score()
                hour_score, hour_label = get_hourly_min_score(base_score)
                
                ml = self.ml_scorer.get_stats()
                sell = self.sell_generator.get_stats()
                wd = self.wallet_discovery.get_stats()
                opt = self.auto_optimizer.get_stats()
                port = self.portfolio_tracker.get_portfolio_summary()
                wl = self.watchlist.get_stats()
                ta = self.trade_assistant.get_stats()
                sim = self.simulator.get_stats()
                
                logger.info(
                    f"[HEALTH] {pause} | {evolution_status} | "
                    f"Trading:{trading_paused} Evol:{evolution_paused} | "
                    f"Up:{uptime}min | WS:{ws} | "
                    f"Hour:{hour_label}(≥{hour_score}) | "
                    f"Anal:{self.tokens_analyzed} | Alrt:{self.alerts_sent} | "
                    f"Fast:{self.fast_alerts} | HFilt:{self.hour_filtered} | "
                    f"Copy:{self.copy_trades} | Tw:{self.twitter_signals} | "
                    f"Rd:{self.raydium_tokens} | Mom:{self.momentum_alerts} | "
                    f"Bulls:{len(self.bull_analyzer.bulls)} | "
                    f"Sells:{sell['positions_open']}p/{sell['total_signals']}s | "
                    f"SL:{sell['sl_hits']} TP:{sell['tp_hits']} | "
                    f"Dump:{self.dump_alerts_sent} | "
                    f"WSell:{self.whale_sell_alerts_sent} | "
                    f"Watch:{wl['active_watches']}/{self.watchlist_alerts_sent} | "
                    f"Port:{port['open_positions']}p | "
                    f"Trade:{ta['buys_confirmed']}b/{ta['sells_registered']}s | "
                    f"Sim:{sim['closed_positions']}t/"
                    f"WR{sim['win_rate']:.0f}%/"
                    f"ROI{sim['roi_pct']:+.0f}% | "
                    f"Wl:{wd['wallets_tracked']}/{wd['candidates_ready']}c | "
                    f"Opt:{opt['total_optimizations']} | "
                    f"ML:{ml.get('trades', 0)} | Mkt:{regime}"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[HEALTH] {e}")
            await asyncio.sleep(HEALTH_CHECK_EVERY)

    # ═══════════════════════════════════════════════════════════════
    # NEW: Evolution Maintenance Loop
    # ═══════════════════════════════════════════════════════════════
    
    async def _run_evolution_maintenance(self):
        """Boucle maintenance évolution: retrain check, config reload, drift check."""
        logger.info("[EVOLUTION] Maintenance loop actif (300s)")
        await asyncio.sleep(60)
        while True:
            try:
                # 1. Check auto-retrain
                maybe_retrain()
                
                # 2. Hot-reload optimized_config.json si changé
                await self._maybe_reload_config()
                
                # 3. Drift Guard health check
                if not self.drift_guard.is_trading_allowed():
                    logger.warning("[EVOLUTION] ⚠️ Trading PAUSÉ par Drift Guard")
                if not self.drift_guard.is_evolution_allowed():
                    logger.warning("[EVOLUTION] ⚠️ Auto-évolution PAUSÉE par Drift Guard")
                
                # 4. Flush event store
                self.event_store.flush_all()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[EVOLUTION] Maintenance error: {e}")
            await asyncio.sleep(300)

    async def _maybe_reload_config(self):
        """Recharge config optimisée si fichier modifié."""
        try:
            config_path = Path("data/optimized_config.json")
            if config_path.exists():
                mtime = config_path.stat().st_mtime
                if mtime > self._last_config_reload:
                    self._last_config_reload = mtime
                    with open(config_path) as f:
                        new_config = json.load(f)
                    self.auto_optimizer.update_config(new_config)
                    logger.info(f"[EVOLUTION] Config hot-reloaded: {new_config}")
        except Exception as e:
            logger.debug(f"[EVOLUTION] Config reload skip: {e}")

    # ═══════════════════════════════════════════════════════════════
    # TELEGRAM COMMANDS — Inchangé v13.5.1 (gardé complet)
    # ═══════════════════════════════════════════════════════════════
    
    async def _init_telegram_offset(self):
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if not token:
            return
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        try:
            async with self.http_session.get(
                url, params={"timeout": 1}, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    updates = data.get("result", [])
                    if updates:
                        self.telegram_offset = updates[-1]["update_id"] + 1
                        logger.info(f"[CMD] Offset initialisé : {self.telegram_offset}")
        except Exception:
            pass

    async def _run_command_listener(self):
        logger.info(f"[CMD] Actif ({COMMAND_POLL_EVERY}s) — callbacks inline ON")
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
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for update in data.get("result", []):
                            self.telegram_offset = update["update_id"] + 1
                            
                            # Callback Query (boutons inline)
                            if "callback_query" in update:
                                cq = update["callback_query"]
                                cq_chat = str(
                                    cq.get("message", {}).get("chat", {}).get("id", "")
                                )
                                if cq_chat == chat_id:
                                    try:
                                        await self.callback_handler.handle(cq)
                                    except Exception as e:
                                        logger.error(f"[CALLBACK] {e}")
                                continue
                            
                            # Message texte
                            msg = update.get("message", {})
                            text = msg.get("text", "").strip()
                            chat = str(msg.get("chat", {}).get("id", ""))
                            if not text or not chat:
                                continue
                            if not self.admin_security.is_authorized(chat):
                                continue
                            if text.startswith("/"):
                                await self._handle_command(text, chat)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"[CMD] {e}")
            await asyncio.sleep(COMMAND_POLL_EVERY)

    async def _handle_command(self, text: str, user_id: str = None):
        text_lower = text.lower().strip()
        logger.info(f"[CMD] {text}")
        
        if user_id:
            rl = self.admin_security.check_rate_limit(user_id, text_lower)
            if not rl["allowed"]:
                await self._send_reply(f"🔒 {rl['reason']}")
                return
            if self.admin_security.needs_confirmation(text_lower):
                conf = self.admin_security.request_confirmation(user_id, text_lower)
                if not conf["confirmed"]:
                    await self._send_reply(conf["message"])
                    return
            self.admin_security.register_command(user_id, text_lower)
        
        # Commandes avec arguments
        cmd_args = {
            "/check ": self._cmd_check,
            "/win ": self._cmd_win,
            "/loss ": self._cmd_loss,
            "/backtest ": self._cmd_backtest,
            "/watch ": self._cmd_watch_position,
            "/close ": self._cmd_close,
            "/buy ": self._cmd_buy,
            "/sell ": self._cmd_sell,
            "/sold ": self._cmd_sold,
            "/watchmc ": self._cmd_watchmc,
            "/watchpump ": self._cmd_watchpump,
            "/watchdrop ": self._cmd_watchdrop,
            "/unwatch ": self._cmd_unwatch,
            "/social ": self._cmd_social,
            "/strategy ": self._cmd_strategy,
        }
        for prefix, handler in cmd_args.items():
            if text_lower.startswith(prefix):
                await handler(text[len(prefix):].strip())
                return
        
        # Commandes sans arguments
        routes = {
            "/status": self._cmd_status,
            "/stats": self._cmd_stats,
            "/confirm": self._cmd_confirm_buy,
            "/cancel": self._cmd_cancel_buy,
            "/alertes": self._cmd_alertes,
            "/mlstats": self._cmd_mlstats,
            "/bullrun": self._cmd_bullrun,
            "/backtest": self._cmd_backtest,
            "/positions": self._cmd_positions,
            "/clearpositions": self._cmd_clear_positions,
            "/wallets": self._cmd_wallets,
            "/candidates": self._cmd_candidates,
            "/optimize": self._cmd_optimize,
            "/portfolio": self._cmd_portfolio,
            "/pnl": self._cmd_pnl,
            "/trades": self._cmd_trades,
            "/watchlist": self._cmd_watchlist,
            "/compare": self._cmd_compare_strategies,
            "/strategies": self._cmd_list_strategies,
            "/simulate": self._cmd_simulate,
            "/simreset": self._cmd_sim_reset,
            "/report": self._cmd_report,
            "/admin": self._cmd_admin,
            "/pause": self._cmd_pause,
            "/resume": self._cmd_resume,
            "/help": self._cmd_help,
            "/start": self._cmd_help,
        }
        handler = routes.get(text_lower)
        if handler:
            try:
                await handler()
            except Exception as e:
                logger.error(f"[CMD] {text}: {e}")
                await self._send_reply(f"❌ Erreur: {self._esc(str(e))}")
        else:
            await self._send_reply(f"❓ Commande inconnue: `{self._esc(text)}`\nTape /help")

    # ═══════════════════════════════════════════════════════════════
    # COMMANDES — Copiées de v13.5.1 (identiques)
    # ═══════════════════════════════════════════════════════════════
    
    async def _cmd_status(self):
        uptime = int(time.time() - self.start_time)
        h = uptime // 3600
        m = (uptime % 3600) // 60
        s = uptime % 60
        try:
            sig = self.market_context.get_market_signal()
            regime, btc = sig["regime"], sig["btc_change_24h"]
        except Exception:
            regime, btc = "N/A", 0
        
        ml = self.ml_scorer.get_stats()
        n_bulls = len(self.bull_analyzer.bulls)
        sell = self.sell_generator.get_stats()
        wd = self.wallet_discovery.get_stats()
        opt = self.auto_optimizer.get_stats()
        port = self.portfolio_tracker.get_portfolio_summary()
        wl = self.watchlist.get_stats()
        ta = self.trade_assistant.get_stats()
        sim = self.simulator.get_stats()
        base_score = self.auto_optimizer.get_min_score()
        hour_score, hour_label = get_hourly_min_score(base_score)
        pause_str = "⏸ EN PAUSE" if self.paused else "▶️ Actif"
        ws_str = "✅ Actif" if self.ws_active else "❌ Inactif"
        evolution_str = "🧬 ON" if self._evolution_started else "🧬 OFF"
        drift_trading = "🛑" if self.drift_guard.trading_paused else "✅"
        drift_evo = "🛑" if self.drift_guard.auto_evolution_paused else "✅"
        
        msg = (
            f"🤖 *MemeSniper v14.1-EVOLUTION*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⏱ Uptime: `{h}h {m}m {s}s`\n"
            f"🔄 État: *{self._esc(pause_str)}*\n"
            f"📡 WebSocket: {ws_str}\n"
            f"🧬 Evolution: {evolution_str}\n"
            f"🛡️ Drift Trading: {drift_trading} | Evol: {drift_evo}\n"
            f"🕐 Heure: `{self._esc(hour_label)}` \\(score ≥ `{hour_score}`\\)\n\n"
            f"🎯 *Modules :*\n"
            f"🛡️ Safety v1.4 | 🔥 Momentum v1.2\n"
            f"⚡ Speed adaptatif | 🐋 Micro whale\n"
            f"🛡️ SL auto inline (défaut #1 corrigé)\n"
            f"🎯 Bulls: `{n_bulls}` | "
            f"💰 Sells: `{sell['positions_open']}` pos\n"
            f"🛑 SL: `{sell['sl_hits']}` | "
            f"🎯 TP: `{sell['tp_hits']}`\n"
            f"📸 Charts | 🔍 Wallets: `{wd['wallets_tracked']}`\n"
            f"🎯 Optim: `{opt['total_optimizations']}`\n"
            f"💼 Portfolio: `{port['open_positions']}` pos\n"
            f"📉 Dump: `{self.dump_alerts_sent}`\n"
            f"🐋 WSell: `{self.whale_sell_alerts_sent}`\n"
            f"🔔 Watch: `{wl['active_watches']}`\n"
            f"💰 Trade: `{ta['buys_confirmed']}` buys | "
            f"`{ta['sells_registered']}` sells\n"
            f"🎮 Sim: `{sim['closed_positions']}` trades | "
            f"ROI `{sim['roi_pct']:+.0f}%`\n"
            f"🧠 ML: `{ml.get('trades', 0)}` trades\n\n"
            f"📊 *Activité :*\n"
            f" Analysés: `{self.tokens_analyzed}`\n"
            f" Alertes: `{self.alerts_sent}`\n"
            f" Fast: `{self.fast_alerts}` | "
            f"Filtrés heure: `{self.hour_filtered}`\n"
            f" Sell signals: `{self.sell_alerts_sent}`\n"
            f" Copy: `{self.copy_trades}`\n"
            f" Twitter: `{self.twitter_signals}`\n"
            f" Raydium: `{self.raydium_tokens}`\n"
            f" Momentum: `{self.momentum_alerts}`\n\n"
            f"🌍 Marché: *{self._esc(regime)}* "
            f"\\(BTC `{btc:+.1f}%`\\)"
        )
        await self._send_reply(msg)

    async def _cmd_stats(self):
        try:
            stats = self.perf_tracker.get_stats()
            tier_stats = stats.get("tier_stats", {})
            msg = (
                f"📈 *Performance*\n━━━━━━━━━━━━━━\n\n"
                f"Total alertes : `{stats.get('total_alerts', 0)}`\n"
                f"Trades fermés : `{stats.get('closed_trades', 0)}`\n"
                f"Win rate : `{stats.get('win_rate', 0):.1f}%`\n"
                f"Wins : `{stats.get('wins', 0)}` ✅\n"
                f"Losses : `{stats.get('losses', 0)}` ❌\n\n"
                f"💎 *Par tier :*\n"
                f" Ultimate : `{tier_stats.get('ULTIMATE', {}).get('total', 0)}` "
                f"\\(WR `{tier_stats.get('ULTIMATE', {}).get('rate', 0):.0f}%`\\)\n"
                f" Strong : `{tier_stats.get('STRONG', {}).get('total', 0)}` "
                f"\\(WR `{tier_stats.get('STRONG', {}).get('rate', 0):.0f}%`\\)\n"
                f" Good : `{tier_stats.get('GOOD', {}).get('total', 0)}` "
                f"\\(WR `{tier_stats.get('GOOD', {}).get('rate', 0):.0f}%`\\)\n"
                f" Normal : `{tier_stats.get('NORMAL', {}).get('total', 0)}` "
                f"\\(WR `{tier_stats.get('NORMAL', {}).get('rate', 0):.0f}%`\\)"
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
            reverse=True,
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
            short = f"{mint[:8]}...{mint[-4:]}"
            lines.append(f"{i}. `{short}` - {age_str}")
        await self._send_reply("\n".join(lines))

    async def _cmd_check(self, mint: str):
        if not mint or len(mint) < 32:
            await self._send_reply("❌ Format: `/check `")
            return
        await self._send_reply(f"🔍 Analyse `{self._esc(mint[:16])}...`")
        try:
            safety = await self.token_safety.full_safety_check(mint)
            summary = self.token_safety.summary(safety)
            await self._send_reply(f"🛡️ *Résultat:*\n```\n{self._esc(summary)}\n```")
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
            f"✅ *WIN* `{self._esc(name)}` `+{pnl:.0f}%`\n"
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
            "🎯 *BULL RUN ANALYZER*", "━━━━━━━━━━━━━━", "",
            f"📊 Bulls (7j): *{stats['total']}*", f"📈 Gain moyen: *+{stats['avg_gain']:.0f}%*",
        ]
        if stats.get("hours"):
            lines.append("\n⏰ *TOP HEURES :*")
            for h, c in stats["hours"][:3]:
                pct = round(c / stats["total"] * 100)
                lines.append(f" `{h:02d}h`: {c} ({pct}%)")
        if stats.get("top_5"):
            lines.append("\n🏆 *TOP 5 :*")
            for i, b in enumerate(stats["top_5"], 1):
                lines.append(f" `{i}.` ${self._esc(b['symbol'])} +{b['change_24h']:.0f}%")
        recos = self.bull_analyzer.get_recommendations()
        if recos:
            lines.append("\n🧠 *RECOS :*")
            for r in recos[:3]:
                lines.append(f" • {self._esc(r)}")
        await self._send_reply("\n".join(lines))

    async def _cmd_backtest(self, args: str = ""):
        parts = args.split() if args else []
        min_liq = 5_000
        days = 30
        try:
            if len(parts) >= 1: min_liq = int(parts[0])
            if len(parts) >= 2: days = int(parts[1])
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
            await self._send_reply(f"📊 *BACKTEST*\n\n{self._esc(results[0].get('message', ''))}")
            return
        lines = ["📊 *BACKTEST HISTORIQUE*", "━━━━━━━━━━━━━━", f"Période: `{days}j`", f"Bulls: `{results[0]['total_bulls']}`", ""]
        for res in results:
            liq = res.get("params", {}).get("min_liquidity", 0)
            lines.append("━━━━━━━━━━━━━━")
            lines.append(f"🎯 *{self._esc(res['name'])}* \\(liq ≥ ${liq/1000:.0f}K\\)")
            lines.append(f" Alertes: `{res['would_alert']}/{res['total_bulls']}`")
            lines.append(f" Hit rate: `{res['hit_rate']:.1f}%`")
            lines.append(f" Gain moy: `+{res['avg_gain']:.0f}%`")
        await self._send_reply("\n".join(lines))

    async def _cmd_strategy(self, args: str):
        parts = args.split()
        strat_name = parts[0].upper() if parts else "BALANCED"
        try:
            days = int(parts[1]) if len(parts) > 1 else 30
        except ValueError:
            days = 30
        result = self.backtester_v2.simulate_strategy(strategy_name=strat_name, days=days, entry_amount=10)
        if result.get("total_trades", 0) == 0:
            await self._send_reply(f"📊 *{self._esc(strat_name)}*\n\n{self._esc(result.get('message', 'Pas de données'))}")
            return
        msg = (
            f"📊 *STRATÉGIE : {self._esc(result['strategy_name'])}*\n"
            f"━━━━━━━━━━━━━━\n"
            f"_{self._esc(result['strategy_desc'])}_\n\n"
            f"🎯 Trades: `{result['total_trades']}`\n"
            f"✅ Wins: `{result['wins']}` | ❌ Losses: `{result['losses']}`\n"
            f"📈 WR: `{result['win_rate']:.1f}%`\n\n"
            f"💰 *Résultats :*\n"
            f" Investi: `{result['total_invested']:.0f}€`\n"
            f" PnL: `{result['total_pnl_eur']:+.0f}€`\n"
            f" ROI: `{result['roi_pct']:+.1f}%`\n\n"
            f"🎯 TPs: TP1:{result['tp_hits']['TP1']} | TP2:{result['tp_hits']['TP2']} | "
            f"TP3:{result['tp_hits']['TP3']} | TP4:{result['tp_hits']['TP4']}\n"
            f"🛑 SL: `{result['sl_hits']}`"
        )
        await self._send_reply(msg)

    async def _cmd_compare_strategies(self):
        result = self.backtester_v2.compare_strategies(days=30)
        if "error" in result:
            await self._send_reply(f"📊 {self._esc(result['error'])}")
            return
        lines = ["📊 *COMPARAISON STRATÉGIES*", "━━━━━━━━━━━━━━", f"Période: `{result['period_days']}j`", ""]
        for res in result["results"]:
            if res.get("total_trades", 0) == 0: continue
            lines.append("━━━━━━━━━━━━━━")
            lines.append(f"🎯 *{self._esc(res['strategy_name'])}*")
            lines.append(f" Trades: `{res['total_trades']}` | WR: `{res['win_rate']:.0f}%`")
            lines.append(f" ROI: `{res['roi_pct']:+.1f}%` | PnL: `{res['total_pnl_eur']:+.0f}€`")
            lines.append("")
        lines.append(f"🏆 Meilleur ROI: *{self._esc(result['best_by_roi'])}*")
        lines.append(f"🎯 Meilleur WR: *{self._esc(result['best_by_winrate'])}*")
        await self._send_reply("\n".join(lines))

    async def _cmd_list_strategies(self):
        strats = self.backtester_v2.get_available_strategies()
        lines = ["📊 *STRATÉGIES DISPONIBLES*", "━━━━━━━━━━━━━━", ""]
        for name, info in strats.items():
            lines.append(f"🎯 *{name}*")
            lines.append(f" {self._esc(info['description'])}")
            lines.append(f" TPs: `{info['tp_count']}` | SL: `{info['sl_pct']}%`")
            lines.append("")
        lines.append("💡 `/strategy NAME [days]`")
        lines.append("💡 `/compare` pour comparer")
        await self._send_reply("\n".join(lines))

    # ═══════════════════════════════════════════════════════════════
    # TRADING COMMANDS
    # ═══════════════════════════════════════════════════════════════

    async def _cmd_buy(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            await self._send_reply("❌ `/buy SYMBOL AMOUNT [MINT]`\nEx: `/buy PEPE 10`")
            return
        symbol = parts[0].upper()
        try:
            amount = float(parts[1])
        except ValueError:
            await self._send_reply("❌ Montant invalide")
            return
        mint = parts[2] if len(parts) > 2 else None
        user_id = os.getenv("TELEGRAM_CHAT_ID", "default")
        result = await self.trade_assistant.prepare_buy(user_id=user_id, symbol=symbol, amount_eur=amount, mint=mint)
        if not result["success"]:
            await self._send_reply(f"❌ {self._esc(result['message'])}")
            return
        msg = (
            f"💰 *ACHAT PRÉPARÉ*\n━━━━━━━━━━━━━━\n\n"
            f"🪙 Token: `${self._esc(symbol)}`\n"
            f"💵 Montant: `{amount:.2f}€`\n"
            f"◎ SOL: `{result['amount_sol']:.4f}`\n\n"
            f"📊 Prix: `${result['price']:.8f}`\n"
            f"💰 MC: `${result['market_cap']/1000:.0f}K`\n"
            f"💧 Liq: `${result['liquidity']/1000:.0f}K`\n\n"
            f"👇 *Étapes :*\n1. Clique *🚀 OUVRIR PHOTON*\n2. Achète dans Photon\n3. Tape `/confirm`\n\n⏱ Expire dans 10 min"
        )
        buttons = {"inline_keyboard": [
            [{"text": "🚀 OUVRIR PHOTON", "url": result["photon_url"]}],
            [{"text": "📊 Chart DexScreener", "url": f"https://dexscreener.com/solana/{result['mint']}"}],
        ]}
        await self.alert_sender._send_telegram(msg, buttons=buttons)

    async def _cmd_confirm_buy(self):
        user_id = os.getenv("TELEGRAM_CHAT_ID", "default")
        pending = self.trade_assistant.get_pending_buy(user_id)
        if not pending:
            await self._send_reply("❌ *Aucun achat en attente*\n\nUtilise d'abord `/buy SYMBOL AMOUNT`")
            return
        result = await self.trade_assistant.confirm_buy(user_id)
        if result["success"]:
            symbol = self._esc(result["symbol"])
            amount = result["amount_eur"]
            await self._send_reply(
                f"✅ *ACHAT CONFIRMÉ*\n━━━━━━━━━━━━━━\n\n"
                f"🪙 Token: `${symbol}`\n💵 Montant: `{amount:.2f}€`\n"
                f"📊 Prix entrée: `${result['entry_price']:.8f}`\n\n"
                f"✅ Ajouté au portfolio\n📊 `/portfolio` pour voir\n💰 `/sold {symbol} +150` quand tu vends"
            )
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_cancel_buy(self):
        user_id = os.getenv("TELEGRAM_CHAT_ID", "default")
        result = await self.trade_assistant.cancel_buy(user_id)
        if result["success"]:
            await self._send_reply(f"✅ {self._esc(result['message'])}")
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_sell(self, args: str):
        await self._cmd_sold(args)

    async def _cmd_sold(self, args: str):
        parts = args.split() if args else []
        if len(parts) < 2:
            await self._send_reply(
                "❌ *Usage :*\n`/sold SYMBOL POURCENTAGE`\n\n"
                "📌 *Exemples :*\n"
                "`/sold PEPE +150` → gain +150%\n"
                "`/sold BONK -45` → perte -45%\n"
                "`/sold WIF +300 TP2` → avec note"
            )
            return
        symbol = parts[0].upper()
        pnl_raw = parts[1].replace("%", "")
        notes = " ".join(parts[2:]) if len(parts) > 2 else ""
        try:
            is_negative = pnl_raw.startswith("-")
            raw_val = float(pnl_raw.replace("+", "").replace("-", ""))
            pnl_pct = -raw_val if is_negative else raw_val
        except ValueError:
            await self._send_reply("❌ Pourcentage invalide.\nExemples: `+150`, `-45`, `300`")
            return
        
        result = await self.trade_assistant.register_sell(symbol=symbol, pnl_pct=pnl_pct)
        if not result.get("success"):
            await self._send_reply(
                f"⚠️ *{self._esc(symbol)}* non trouvé dans les positions.\n\n"
                f"Tu peux quand même nourrir le ML :\n"
                f"`/{'win' if pnl_pct > 0 else 'loss'} {self._esc(symbol)} {abs(pnl_pct):.0f}`\n\n"
                f"💡 La prochaine fois, clique *✅ J'ai acheté* sur l'alerte pour enregistrer le trade."
            )
            return
        
        pnl_eur = result.get("pnl_eur", 0)
        final = result.get("final_eur", 0)
        amount = result.get("amount_eur", 0)
        duration = result.get("duration_min", 0)
        if duration < 60: dur_str = f"{duration:.0f}min"
        elif duration < 1440: dur_str = f"{duration/60:.1f}h"
        else: dur_str = f"{duration/1440:.1f}j"
        
        if pnl_pct >= 200: emoji = "🚀🚀🚀"
        elif pnl_pct >= 50: emoji = "🚀"
        elif pnl_pct > 0: emoji = "📈"
        elif pnl_pct > -30: emoji = "📉"
        else: emoji = "💀"
        result_str = "WIN 🎉" if pnl_pct > 0 else "LOSS 💀"
        
        ml_stats = self.ml_scorer.get_stats()
        wr = ml_stats.get("win_rate", 0)
        ml_total = ml_stats.get("trades", 0)
        
        msg = (
            f"{emoji} *VENTE ENREGISTRÉE — {self._esc(symbol)}*\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"📊 Résultat : *{result_str}*\n"
            f"💹 PnL : `{pnl_pct:+.1f}%` \\(`{pnl_eur:+.2f}€`\\)\n"
            f"💰 Investi : `{amount:.2f}€`\n"
            f"🏁 Final : `{final:.2f}€`\n"
            f"⏱ Durée : `{dur_str}`\n"
        )
        if notes:
            msg += f"📝 Notes : *{self._esc(notes)}*\n"
        msg += (
            f"\n━━━━━━━━━━━━━━\n"
            f"🧠 *ML nourri automatiquement*\n"
            f" Trades total : `{ml_total}`\n"
            f" Win rate : `{wr:.1f}%`\n\n"
            f"📊 `/pnl` | 💼 `/portfolio` | 🧠 `/mlstats`"
        )
        await self._send_reply(msg)

    # ═══════════════════════════════════════════════════════════════
    # SIMULATOR
    # ═══════════════════════════════════════════════════════════════

    async def _cmd_simulate(self):
        stats = self.simulator.get_stats()
        if stats["total_simulated"] == 0:
            await self._send_reply(
                "🎮 *SIMULATOR*\n━━━━━━━━━━━━━━\n\n"
                "⏳ Aucune simulation encore.\n\n"
                "Le bot simule automatiquement\nchaque alerte comme si tu avais\nacheté 10€.\n\nReviens dans quelques heures!"
            )
            return
        lines = ["🎮 *SIMULATOR - Paper Trading*", "━━━━━━━━━━━━━━", "", "📊 *Statistiques :*",
                 f" Simulés: `{stats['total_simulated']}`", f" Ouverts: `{stats['open_positions']}`",
                 f" Fermés: `{stats['closed_positions']}`", f" Wins: `{stats['wins']}` ✅",
                 f" Losses: `{stats['losses']}` ❌", f" Win rate: `{stats['win_rate']}%`", "",
                 "💰 *Performance :*", f" Investi total: `{stats['total_invested']:.0f}€`",
                 f" PnL global: `{stats['total_pnl']:+.2f}€`", f" ROI: `{stats['roi_pct']:+.1f}%`", "",
                 "📅 *Par période :*", f" Aujourd'hui: `{stats['pnl_day']:+.2f}€`",
                 f" 7 jours: `{stats['pnl_week']:+.2f}€`", "", f"⏱ Durée moy: `{stats['avg_duration_min']:.0f}min`"]
        if stats.get("best_trade"):
            best = stats["best_trade"]
            lines.extend(["", "🏆 *Meilleur trade :*",
                f" ${self._esc(best['symbol'])} : `{best.get('pnl_pct', 0):+.0f}%` \\(`{best.get('pnl_eur', 0):+.2f}€`\\)"])
        if stats.get("worst_trade"):
            worst = stats["worst_trade"]
            lines.extend(["", "💀 *Pire trade :*",
                f" ${self._esc(worst['symbol'])} : `{worst.get('pnl_pct', 0):+.0f}%` \\(`{worst.get('pnl_eur', 0):+.2f}€`\\)"])
        open_pos = self.simulator.get_open_positions()
        if open_pos:
            lines.extend(["", "━━━━━━━━━━━━━━", f"💎 *Positions ouvertes ({len(open_pos)}) :*"])
            for p in open_pos[:5]:
                sym = self._esc(p["symbol"]); pnl = p.get("current_pnl", 0)
                e = "🚀" if pnl > 0 else "📉" if pnl < 0 else "➡️"
                lines.append(f" {e} `${sym}` : `{pnl:+.0f}%`")
        recent = self.simulator.get_recent_trades(limit=5)
        if recent:
            lines.extend(["", "━━━━━━━━━━━━━━", "📋 *5 derniers trades :*"])
            for t in recent:
                sym = self._esc(t["symbol"]); pnl_pct = t.get("pnl_pct", 0); pnl_eur = t.get("pnl_eur", 0)
                reason = t.get("exit_reason", "")
                e = "🚀" if pnl_pct > 0 else "💀"
                reason_icon = "🛑" if "stop_loss" in reason else "🎯" if "take_profit" in reason else "⏰" if "timeout" in reason else ""
                lines.append(f" {e}{reason_icon} `${sym}` `{pnl_pct:+.0f}%` \\(`{pnl_eur:+.2f}€`\\)")
        await self._send_reply("\n".join(lines))

    async def _cmd_sim_reset(self):
        count = self.simulator.reset()
        await self._send_reply(f"✅ *{count} simulations supprimées*\n\nLe simulator est vide.\nNouvelles alertes = nouvelles simulations.")

    # ═══════════════════════════════════════════════════════════════
    # PORTFOLIO
    # ═══════════════════════════════════════════════════════════════

    async def _cmd_portfolio(self):
        summary = self.portfolio_tracker.get_portfolio_summary()
        positions = self.portfolio_tracker.get_all_positions()
        if summary["open_positions"] == 0 and summary["total_trades"] == 0:
            await self._send_reply("💼 *Portfolio vide*\n\n💡 Clique *✅ J'ai acheté* sur une alerte\nou tape `/buy SYMBOL AMOUNT`")
            return
        lines = ["💼 *PORTFOLIO*", "━━━━━━━━━━━━━━", "", f"📊 Positions: `{summary['open_positions']}`",
                 f"💰 Investi: `{summary['total_invested']:.0f}€`", f"📈 PnL réalisé: `{summary['total_pnl']:+.0f}€`",
                 f"📈 PnL non-réalisé: `{summary['total_open_pnl_eur']:+.0f}€`", f"🎯 Trades totaux: `{summary['total_trades']}`"]
        if positions:
            lines.append("\n━━━━━━━━━━━━━━"); lines.append("💎 *POSITIONS :*")
            for pos in positions[:10]:
                sym = self._esc(pos["symbol"]); amt = pos["amount_eur"]; pnl = pos.get("current_pnl", 0)
                e = "🚀" if pnl > 0 else "📉" if pnl < 0 else "➡️"
                lines.append(f" {e} `${sym}`: {amt:.0f}€ \\({pnl:+.0f}%\\)")
        await self._send_reply("\n".join(lines))

    async def _cmd_pnl(self):
        pnl = self.portfolio_tracker.get_pnl_by_period()
        def fmt(v): return f"`{v:+.2f}€`" if v != 0 else "`0€`"
        msg = (f"📊 *PnL PAR PÉRIODE*\n━━━━━━━━━━━━━━\n\n"
               f"📅 *Aujourd'hui :* {fmt(pnl['pnl_day'])}\n W/L: `{pnl['wins_day']}{pnl['losses_day']}`\n\n"
               f"📅 *7 jours :* {fmt(pnl['pnl_week'])}\n W/L: `{pnl['wins_week']}{pnl['losses_week']}`\n\n"
               f"📅 *30 jours :* {fmt(pnl['pnl_month'])}\n\n"
               f"🌍 *All-time :* {fmt(pnl['pnl_all'])}\n W/L: `{pnl['wins_all']}{pnl['losses_all']}`\n WR: `{pnl['win_rate_all']:.1f}%`")
        await self._send_reply(msg)

    async def _cmd_trades(self):
        trades = self.portfolio_tracker.get_all_trades(limit=15)
        if not trades:
            await self._send_reply("📭 Aucun trade")
            return
        lines = ["📋 *DERNIERS TRADES*", "━━━━━━━━━━━━━━", ""]
        for t in trades:
            sym = self._esc(t["symbol"]); pnl_pct = t["pnl_pct"]; pnl_eur = t["pnl_eur"]
            e = "🚀" if pnl_pct > 0 else "💀"
            lines.append(f"{e} `${sym}` `{pnl_pct:+.0f}%` \\(`{pnl_eur:+.2f}€`\\)")
        await self._send_reply("\n".join(lines))

    # ═══════════════════════════════════════════════════════════════
    # WATCHLIST
    # ═══════════════════════════════════════════════════════════════

    async def _cmd_watchmc(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            await self._send_reply("❌ `/watchmc SYMBOL TARGET`\nEx: `/watchmc PEPE 500K`")
            return
        symbol = parts[0]; target_str = parts[1].upper()
        try:
            if target_str.endswith("K"): target = float(target_str[:-1]) * 1000
            elif target_str.endswith("M"): target = float(target_str[:-1]) * 1_000_000
            else: target = float(target_str)
        except ValueError:
            await self._send_reply("❌ Target invalide")
            return
        result = await self.watchlist.add_watch(symbol_or_mint=symbol, alert_type="MC_TARGET", target=target)
        if result["success"]:
            await self._send_reply(f"🔔 *Watch MC ajoutée*\n`${self._esc(symbol)}` → `${target/1000:.0f}K`")
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_watchpump(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            await self._send_reply("❌ `/watchpump SYMBOL PCT`")
            return
        symbol = parts[0]
        try: pct = float(parts[1])
        except ValueError:
            await self._send_reply("❌ % invalide")
            return
        result = await self.watchlist.add_watch(symbol_or_mint=symbol, alert_type="PUMP", target=pct)
        if result["success"]:
            await self._send_reply(f"🔔 *Watch pump*\n`${self._esc(symbol)}` → `+{pct:.0f}%`")
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_watchdrop(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            await self._send_reply("❌ `/watchdrop SYMBOL PCT`")
            return
        symbol = parts[0]
        try: pct = float(parts[1])
        except ValueError:
            await self._send_reply("❌ % invalide")
            return
        result = await self.watchlist.add_watch(symbol_or_mint=symbol, alert_type="DROP", target=pct)
        if result["success"]:
            await self._send_reply(f"🔔 *Watch drop*\n`${self._esc(symbol)}` → `-{pct:.0f}%`")
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_unwatch(self, args: str):
        parts = args.split()
        if not parts:
            await self._send_reply("❌ `/unwatch SYMBOL [TYPE]`")
            return
        symbol = parts[0]; alert_type = parts[1].upper() if len(parts) > 1 else None
        result = self.watchlist.remove_watch(symbol, alert_type)
        if result["success"]:
            await self._send_reply(f"✅ {result['removed']} watch(s) supprimée(s)")
        else:
            await self._send_reply(f"❌ {self._esc(result['message'])}")

    async def _cmd_watchlist(self):
        watches = self.watchlist.get_all_watches()
        stats = self.watchlist.get_stats()
        if not watches:
            await self._send_reply("🔔 *Watchlist vide*\n\n💡 `/watchmc SYMBOL 500K`\n💡 `/watchpump SYMBOL 100`\n💡 `/watchdrop SYMBOL 30`")
            return
        lines = ["🔔 *WATCHLIST*", "━━━━━━━━━━━━━━", f"Actives: `{stats['active_watches']}`", f"Déclenchées: `{stats['triggered_watches']}`", ""]
        for w in watches[:15]:
            type_emoji = {"MC_TARGET": "🎯", "PUMP": "🚀", "DROP": "📉", "PRICE": "💰", "VOLUME": "📊"}.get(w["type"], "🔔")
            lines.append(f"{type_emoji} `${self._esc(w['symbol'])}` {self._esc(w['type'])} `{w['target']}`")
        await self._send_reply("\n".join(lines))

    # ═══════════════════════════════════════════════════════════════
    # POSITIONS (Sell Signals)
    # ═══════════════════════════════════════════════════════════════

    async def _cmd_positions(self):
        positions = self.sell_generator.get_positions()
        if not positions:
            await self._send_reply(
                "💰 *Positions vides*\n\n"
                "💡 `/watch ` pour surveiller un token que tu as acheté\n\n"
                "💡 Ou clique *✅ J'ai acheté* sur une alerte → SL/TP activés automatiquement !"
            )
            return
        lines = ["💰 *POSITIONS SURVEILLÉES*", "━━━━━━━━━━━━━━", ""]
        for i, (mint, pos) in enumerate(list(positions.items())[:10], 1):
            elapsed = (time.time() - pos["entry_time"]) / 60
            elapsed_str = f"{elapsed:.0f}min" if elapsed < 60 else f"{elapsed/60:.1f}h"
            source_icon = "🛒" if pos.get("source") == "inline_buy" else "✋" if pos.get("source") == "manual" else "🤖"
            lines.append("━━━━━━━━━━━━━━")
            lines.append(f"{i}. {source_icon} *${self._esc(pos['symbol'])}*")
            lines.append(f" Entry MC: `${pos['entry_mc']/1000:.0f}K`")
            lines.append(f" PnL actuel: `{pos['last_pnl']:+.0f}%`")
            lines.append(f" Max gain: `+{pos['max_gain']:.0f}%`")
            lines.append(f" TPs: `{len(pos['tp_triggered'])}/4`")
            lines.append(f" SL: `{self.sell_generator.SL_PCT}%`")
            lines.append(f" Ouvert: `{elapsed_str}`")
            lines.append("")
        lines.append("🛒 = inline | ✋ = manuel | 🤖 = auto")
        lines.append("💡 `/close SYM` ou `/clearpositions`")
        await self._send_reply("\n".join(lines))

    async def _cmd_clear_positions(self):
        count = self.sell_generator.clear_all_positions()
        await self._send_reply(f"✅ *{count} positions supprimées*\n\nLe sell tracker est vide.\nUtilise `/watch ` pour surveiller les tokens que tu achètes vraiment.")

    async def _cmd_watch_position(self, mint: str):
        if not mint or len(mint) < 32:
            await self._send_reply("❌ `/watch `")
            return
        try:
            data = await self.sell_generator._fetch_token_data(mint)
            if not data or data.get("price", 0) == 0:
                await self._send_reply("❌ Token non trouvé")
                return
            self.sell_generator.add_position(
                mint=mint, symbol="?", entry_price=data["price"], entry_mc=data["market_cap"],
                entry_liquidity=data["liquidity"], entry_buy_ratio=data["buy_ratio"],
                entry_volume_1h=data["volume_1h"], source="manual",
            )
            await self._send_reply(f"✅ *Position ajoutée*\nMC: `${data['market_cap']/1000:.0f}K`\nSL automatique à `{self.sell_generator.SL_PCT}%`")
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
            await self._send_reply("❌ Position introuvable")
            return
        pos = positions[target_mint]
        self.sell_generator.remove_position(target_mint)
        await self._send_reply(f"✅ *Position fermée*\n${self._esc(pos['symbol'])} | max `+{pos['max_gain']:.0f}%`")

    # ═══════════════════════════════════════════════════════════════
    # DISCOVERY
    # ═══════════════════════════════════════════════════════════════

    async def _cmd_wallets(self):
        stats = self.wallet_discovery.get_stats()
        await self._send_reply(
            f"🔍 *WALLET DISCOVERY*\n━━━━━━━━━━━━━━\n\n"
            f"Trackés: `{stats['wallets_tracked']}`\n"
            f"Bulls analysés: `{stats['bulls_analyzed']}`\n"
            f"Candidats: `{stats['candidates_ready']}`\n\n💡 `/candidates` pour voir top"
        )

    async def _cmd_candidates(self):
        candidates = self.wallet_discovery.get_top_candidates(10)
        if not candidates:
            await self._send_reply("🔍 *Candidats vides*\n\nBesoin de 3+ bulls et 60%+ WR")
            return
        lines = [f"🔍 *TOP {len(candidates)} CANDIDATS*", "━━━━━━━━━━━━━━", ""]
        for i, c in enumerate(candidates, 1):
            short = c["wallet"][:8] + "..." + c["wallet"][-4:]
            lines.append(f"{i}. `{short}`")
            lines.append(f" Bulls: `{c['bulls_hit']}` | WR: `{c['win_rate']:.0f}%`")
            lines.append(f" Avg gain: `+{c['avg_gain']:.0f}%`\n")
        await self._send_reply("\n".join(lines))

    async def _cmd_optimize(self):
        stats = self.auto_optimizer.get_stats()
        config = self.auto_optimizer.get_current_config()
        lines = ["🎯 *AUTO-OPTIMIZER*", "━━━━━━━━━━━━━━", f"Optimisations: `{stats['total_optimizations']}`\n", "⚙️ *Config actuelle :*"]
        for k, v in config.items():
            lines.append(f" {self._esc(k)}: `{v}`")
        await self._send_reply("\n".join(lines))

    # ═══════════════════════════════════════════════════════════════
    # SOCIAL
    # ══════════════════════════════════════════════════════════════

    async def _cmd_social(self, args: str):
        parts = args.split()
        if not parts:
            await self._send_reply("❌ `/social SYMBOL [MINT]`")
            return
        symbol = parts[0].upper()
        mint = parts[1] if len(parts) > 1 else None
        await self._send_reply(f"🐦 Analyse `${self._esc(symbol)}`...")
        result = await self.social_score.analyze_token(symbol, mint)
        emoji = self.social_score.get_score_emoji(result["score"])
        lines = ["🐦 *SOCIAL SCORE*", "━━━━━━━━━━━━━━", "", f"{emoji} *${self._esc(symbol)}*", "",
                 f"📊 Score: `{result['score']}/100` \\(`{self._esc(result['level'])}`\\)", "",
                 f"📈 Mentions 1h: `{result['mentions_1h']}`", f"📈 Mentions 24h: `{result['mentions_24h']}`",
                 f"👥 Utilisateurs: `{result['unique_users']}`", "",
                 f"✅ Positif: `{result['sentiment_pos']}%`", f"❌ Négatif: `{result['sentiment_neg']}%`", "",
                 f"⚡ Vélocité: `{result['velocity']:.1f}x`", f"🗑️ Spam: `{result['spam_ratio']}%`"]
        if result["trending"]: lines.append("🔥 *TRENDING !*")
        if result["influencers"]:
            lines.append("\n👥 *INFLUENCEURS :*")
            for inf in result["influencers"]:
                lines.append(f" Tier {inf['tier']}: @{self._esc(inf['username'])}")
        await self._send_reply("\n".join(lines))

    # ═══════════════════════════════════════════════════════════════
    # SYSTEM
    # ═══════════════════════════════════════════════════════════════

    async def _cmd_report(self):
        await self._send_reply("📊 Génération du rapport...")
        try:
            await self.csv_exporter.force_daily_report()
            await self._send_reply("✅ Rapport envoyé")
        except Exception as e:
            await self._send_reply(f"❌ {self._esc(str(e))}")

    async def _cmd_admin(self):
        stats = self.admin_security.get_stats()
        admins = self.admin_security.get_authorized_admins()
        base_score = self.auto_optimizer.get_min_score()
        hour_score, hour_label = get_hourly_min_score(base_score)
        lines = ["🔐 *ADMIN SECURITY*", "━━━━━━━━━━━━━━", "",
                 f"Admins: `{stats['authorized_admins']}`", f"Commandes: `{stats['total_commands']}`",
                 f"Blacklistés: `{stats['blacklisted']}`", f"Violations: `{stats['total_violations']}`", "",
                 "🕐 *Filtre horaire actuel :*", f" {self._esc(hour_label)} | Score min: `{hour_score}`",
                 f" Heure UTC: `{time.gmtime().tm_hour}h`", "", "👥 *Admins :*"]
        for admin in admins: lines.append(f" `{admin}`")
        await self._send_reply("\n".join(lines))

    async def _cmd_pause(self):
        self.paused = True
        await self._send_reply("⏸ *Bot en pause*")
        if self.dashboard: self.dashboard.add_event("Bot en pause")

    async def _cmd_resume(self):
        self.paused = False
        await self._send_reply("▶️ *Bot repris*")
        if self.dashboard: self.dashboard.add_event("Bot repris")

    async def _cmd_help(self):
        msg = (
            "🤖 *MemeSniper v14.1-EVOLUTION*\n━━━━━━━━━━━━━━\n\n"
            "📊 *Info :*\n/status /stats /alertes /bullrun /backtest\n\n"
            "💰 *TRADING :*\n/buy `SYM AMT` - Préparer achat\n/confirm - Confirmer achat\n/cancel - Annuler achat\n/sold `SYM PNL` - ✅ Enregistrer vente\n\n"
            "🛒 *BOUTONS INLINE :*\nChaque alerte a des boutons BUY\n✅ J'ai acheté → SL/TP auto activés !\n\n"
            "🎮 *SIMULATION :*\n/simulate - Résultats paper trading\n/simreset - Reset simulations\n\n"
            "💼 *Portfolio :*\n/portfolio /pnl /trades\n\n"
            "🔔 *Watchlist :*\n/watchmc `SYM 500K`\n/watchpump `SYM 100`\n/watchdrop `SYM 30`\n/unwatch `SYM` /watchlist\n\n"
            "💰 *Sell Signals :*\n/positions /watch `MINT`\n/close `SYM` /clearpositions\n\n"
            "📊 *Stratégies :*\n/strategies /strategy `NAME`\n/compare\n\n"
            "🔍 *Discovery :*\n/wallets /candidates /optimize\n\n"
            "🐦 *Social :*\n/social `SYMBOL`\n\n"
            "🔍 *Analyse :*\n/check `MINT`\n\n"
            "🧠 *ML :*\n/win `SYM PCT` /loss `SYM PCT`\n/mlstats\n\n"
            "🔐 *Système :*\n/report /admin /pause /resume /help"
        )
        await self._send_reply(msg)

    # ═══════════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════════

    async def _send_reply(self, text: str):
        await self.alert_sender._send_telegram(text)

    def _esc(self, text: str) -> str:
        special = r'_*[]()~`>#+-=|{}.!'
        return "".join(f"\\{c}" if c in special else c for c in str(text))

    def _trim_alerted_tokens(self):
        if len(self.alerted_tokens) <= self.max_alerted:
            return
        newest = dict(sorted(self.alerted_tokens.items(), key=lambda x: x[1], reverse=True)[:250])
        self.alerted_tokens = newest

    # ═══════════════════════════════════════════════════════════════
    # TOKEN HANDLERS — Avec EVENT STORE LOGGING
    # ═══════════════════════════════════════════════════════════════

    async def handle_new_token_ws(self, token_data: dict):
        if self.paused: return
        address = token_data.get("address", "")
        if not address or address in self.alerted_tokens or address in self.processing_tokens:
            return
        symbol = token_data.get("symbol", "???")
        logger.info(f"[WS] 🆕 {symbol} ({address[:8]}...)")
        if self.dashboard: self.dashboard.add_event(f"Nouveau: {symbol}")
        await asyncio.sleep(20)
        await self._analyze_and_alert(address, source="websocket")

    async def handle_new_token_polling(self, token: dict):
        if self.paused: return
        address = token.get("tokenAddress") or token.get("address") or token.get("baseToken", {}).get("address", "")
        if not address or address in self.alerted_tokens or address in self.processing_tokens:
            return
        await self._analyze_and_alert(address, source="polling")

    async def handle_new_token_raydium(self, token_data: dict):
        if self.paused: return
        address = token_data.get("address", "") or token_data.get("mint", "")
        if not address or address in self.alerted_tokens or address in self.processing_tokens:
            return
        source = token_data.get("source", "raydium")
        symbol = token_data.get("symbol", "?")
        liq = token_data.get("liquidity", 0)
        self.raydium_tokens += 1
        logger.info(f"[RAYDIUM] {symbol} | Liq: ${liq:,.0f}")
        if self.dashboard: self.dashboard.add_event(f"Raydium: {symbol}")
        await self._analyze_and_alert(address, source=f"raydium_{source}")

    # ═══════════════════════════════════════════════════════════════
    # ANALYZE & ALERT v14.1 — WITH EVOLUTION LOGGING
    # ═══════════════════════════════════════════════════════════════

    async def _analyze_and_alert(self, address: str, source: str):
        if self.paused: return
        if not address or not isinstance(address, str): return
        if address in self.alerted_tokens: return
        if address in self.processing_tokens: return
        
        self.processing_tokens.add(address)
        detection_ts = time.time()
        
        try:
            self.tokens_analyzed += 1
            
            # 1. Analyse token
            analysis = await self.analyzer.analyze_token(address)
            if not analysis:
                return
            
            # 2. Safety check
            safety = await self.token_safety.full_safety_check(address)
            if self.dashboard: self.dashboard.record_safety(safety)
            if not safety.get("safe", True):
                reason = safety.get("reasons", ["Unknown"])[0]
                logger.warning(f"🚫 SAFETY {address[:8]}... {reason}")
                if self.dashboard: self.dashboard.add_event(f"🚫 {reason[:40]}")
                return
            
            analysis["safety"] = safety
            score = float(analysis.get("score", 0))
            symbol = analysis.get("symbol", "???")
            
            # 3. Twitter signal
            twitter_signal = self.twitter_tracker.get_token_twitter_signal(address)
            if not twitter_signal and symbol and symbol != "???":
                twitter_signal = self.twitter_tracker.get_symbol_twitter_signal(symbol)
            if twitter_signal:
                score = min(10.0, score + float(twitter_signal.get("bonus", 0)))
                analysis["score"] = score
                analysis["twitter_signal"] = twitter_signal
            
            # 4. ML Bonus
            ml_features = self.ml_scorer.extract_features(analysis, analysis, safety)
            ml_bonus = self.ml_scorer.get_ml_bonus(ml_features)
            if ml_bonus != 0.0:
                score = round(max(0.0, min(10.0, score + ml_bonus)), 2)
                analysis["score"] = score
                analysis["ml_bonus"] = ml_bonus
                analysis["ml_features"] = ml_features
            
            # 5. Filtre score horaire
            base_min_score = self.auto_optimizer.get_min_score()
            if source not in ("twitter_TIER1", "copy_TIER1"):
                hour_min_score, hour_label = get_hourly_min_score(base_min_score)
                min_score = hour_min_score
            else:
                min_score = base_min_score
                hour_label = "ALPHA"
            
            if source.startswith("twitter_"):
                if "TIER1" in source: min_score = min(min_score, 6.0)
                elif "TIER2" in source: min_score = min(min_score, 6.5)
                elif "TIER3" in source: min_score = min(min_score, 7.0)
            elif source.startswith("copy_"):
                copy_wallets = analysis.get("alpha_wallet_list", [])
                if copy_wallets:
                    copy_thresh = min(get_copy_threshold(w) for w in copy_wallets)
                    min_score = min(min_score, copy_thresh)
            else:
                if "TIER1_5" in source: min_score = min(min_score, 6.0)
                elif "TIER1" in source: min_score = min(min_score, 5.5)
                elif "TIER2" in source: min_score = min(min_score, 6.5)
            
            if score < min_score:
                self.hour_filtered += 1
                logger.debug(f"[FILTER] {symbol} score={score:.1f} < min={min_score:.1f} ({hour_label})")
                return
            
            logger.info(f"[SCORE] {symbol} {score:.1f}/10 | Safety:{safety.get('score', '?')}/10 | src:{source} | heure:{hour_label}")
            
            # 6. Decision Engine
            decision = self.alert_sender.decision_eng.decide(analysis)
            if decision["action"] == "IGNORE":
                logger.info(f"[DECISION] {symbol} IGNORÉ : {decision.get('reason', '?')}")
                return
            
            # 7. Speed adaptatif
            if source == "websocket":
                alpha_count = analysis.get("alpha_wallets", 0)
                has_twitter = bool(analysis.get("twitter_signal"))
                has_whale = bool(analysis.get("whale_inflow", {}) and analysis.get("whale_inflow", {}).get("has_whales"))
                if score >= 9.0 or alpha_count >= 2 or (has_twitter and has_whale):
                    extra_wait = 0; self.fast_alerts += 1
                    logger.info(f"[SPEED] ⚡ FAST : {symbol} score={score:.1f} alpha={alpha_count}")
                elif score >= 8.5 or alpha_count >= 1 or has_twitter or has_whale:
                    extra_wait = 10
                    logger.info(f"[SPEED] 🔥 MEDIUM : {symbol} score={score:.1f} wait+{extra_wait}s")
                else:
                    extra_wait = 25
                    logger.debug(f"[SPEED] 📊 NORMAL : {symbol} score={score:.1f} wait+{extra_wait}s")
                if extra_wait > 0:
                    await asyncio.sleep(extra_wait)
                    if address in self.alerted_tokens: return
            
            # 8. Micro whale detection
            alpha_signal = analysis.get("alpha_signal", {})
            if alpha_signal and alpha_signal.get("has_alpha"):
                for wallet in alpha_signal.get("wallets", []):
                    if get_wallet_tier(wallet) == "TIER1":
                        score = min(10.0, score + 0.5)
                        analysis["score"] = score
                        logger.info(f"[MICRO_WHALE] 🐋 TIER1 détecté : {wallet[:8]}... sur {symbol}")
                        break
            
            # 9. Chart
            chart_url = None
            try: chart_url = await self.chart_screenshot.get_chart_url(address)
            except Exception: pass
            
            # 10. Envoie alerte
            sent = await self.alert_sender.send_alert(
                token_data=analysis, decision=decision, chart_url=chart_url,
                mint=address, symbol=symbol, score=score,
                tier=decision.get("tier", "NORMAL"),
                suggested_amount=float(decision.get("amount_eur", 10)),
                market_cap=float(analysis.get("market_cap", 0)),
                price=float(analysis.get("price_usd", 0) or analysis.get("price", 0)),
            )
            
            if sent:
                self.alerted_tokens[address] = detection_ts
                self.alerts_sent += 1
                self._trim_alerted_tokens()
                self.perf_tracker.record_alert(analysis, decision)
                
                if decision["action"] == "ACHÈTE":
                    self.position_tracker.add_position(analysis, decision, decision["amount_eur"])
                
                # Simulate buy
                try:
                    await self.simulator.simulate_buy(
                        mint=address, symbol=symbol,
                        alert_data={"score": score, "tier": decision.get("tier", "?")},
                    )
                except Exception as e:
                    logger.debug(f"Simulator buy error: {e}")
                
                # ── EVENT STORE: LOG DETECTION + DECISION ─────────────
                log_event(
                    "detection",           # event_type (positionnel 1)
                    "early_detector",      # source (positionnel 2)
                    token_mint=address,
                    token_symbol=symbol,
                    pool_address=analysis.get("pool", ""),
                    timestamp=detection_ts,
                    features={
                        "onchain_liquidity_usd": analysis.get("liquidity", 0),
                        "onchain_holder_count": analysis.get("holders", 0),
                        "onchain_top10_pct": analysis.get("top10_pct", 100),
                        "onchain_age_seconds": analysis.get("age", 0),
                        "safety_score": safety.get("score", 0),
                        "dev_credibility": analysis.get("dev_cred", 0),
                        "alpha_wallet_signal": float(analysis.get("alpha_wallets", 0) > 0),
                        "bundle_score": analysis.get("bundle_confidence", 0),
                        "twitter_mentions_5m": analysis.get("twitter_mentions_5m", 0),
                        "price_change_5m": analysis.get("price_change_5m", 0),
                        "hour_utc": datetime.now(timezone.utc).hour,
                        "composite_score": score,
                        "conviction_factors": analysis.get("conviction", 0),
                    },
                    decision={
                        "tier": decision.get("tier", "NONE"),
                        "score": score,
                        "alerted": True,
                        "reason": "passed",
                        "source": source,
                    },
                    meta={
                        "bot_version": "14.1-EVOLUTION",
                        "config_hash": self.config_hash,
                        "hour_label": hour_label,
                        "min_score_used": min_score,
                    }
                )
                
                logger.info(f"[ALERT] ✅ {symbol} {score:.1f}/10 → {decision['action']} ({decision['tier']})")
                if self.dashboard:
                    self.dashboard.add_event(f"🚨 {decision['tier']}: {symbol} {score:.1f}/10")
            
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"[ANALYZE] {address[:8]}: {e}", exc_info=True)
        finally:
            self.processing_tokens.discard(address)

    # ═══════════════════════════════════════════════════════════════
    # SIGNAL HANDLERS — Avec EVENT STORE LOGGING OUTCOMES
    # ═══════════════════════════════════════════════════════════════

    async def handle_momentum_token(self, token_data: dict):
        try:
            if self.paused: return
            mint = token_data["mint"]; symbol = token_data["symbol"]
            pct = token_data["trigger_pct"]; trigger = token_data["trigger"]
            quality = token_data.get("quality_score", 0)
            safety = await self.token_safety.full_safety_check(mint)
            if not safety.get("safe") and safety.get("score", 0) < 3: return
            emoji = "🔥🔥🔥" if pct >= 500 else "🔥🔥" if pct >= 200 else "🔥"
            msg = (f"{emoji} *MOMENTUM* {emoji}\n━━━━━━━━━━━━━━\n\n"
                   f"💎 *${self._esc(symbol)}*\n📈 *+{pct:.0f}%* en {self._esc(trigger)}\n"
                   f"💎 Quality: `{quality}/100`\n💰 MC: `${token_data['market_cap']/1000:.0f}K`\n"
                   f"💧 Liq: `${token_data['liquidity']/1000:.0f}K`\n\n⚠️ *DYOR*\n`{mint}`")
            buttons = {"inline_keyboard": [[
                {"text": "🚀 Photon", "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"},
                {"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"},
            ]]}
            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.momentum_alerts += 1
            if self.dashboard: self.dashboard.add_event(f"🔥 MOMENTUM ${symbol} +{pct:.0f}%")
        except Exception as e:
            logger.error(f"Momentum handler: {e}")

    async def handle_sell_signal(self, signal_data: dict):
        try:
            symbol = signal_data["symbol"]; mint = signal_data["mint"]
            pnl = signal_data["pnl_pct"]; signals = signal_data["signals"]
            confidence = signal_data["confidence"]
            
            # Simulate sell
            try: await self.simulator.simulate_sell(mint=mint, reason="sell_signal")
            except Exception as e: logger.debug(f"Simulator sell error: {e}")
            
            has_sl = any(s["type"] == "SL" for s in signals)
            has_tp = any(s["type"] == "TP" for s in signals)
            if has_sl: emoji = "🚨🚨🚨"
            elif has_tp: emoji = "🎯"
            else: emoji = "⚠️"
            
            msg = (f"{emoji} *SELL SIGNAL*\n━━━━━━━━━━━━━━\n\n"
                   f"💎 *${self._esc(symbol)}*\n📊 PnL: `{pnl:+.0f}%`\n"
                   f"🛡️ Confiance: `{confidence}/100`\n\n⚠️ *Signaux :*\n")
            for sig in signals[:3]: msg += f" • {self._esc(sig['message'])}\n"
            msg += (f"\n💡 *Action :* {self._esc(signal_data.get('recommended_action', ''))}\n`{mint}`")
            
            if has_sl:
                buttons = {"inline_keyboard": [
                    [{"text": "🚨 VENDRE SUR PHOTON", "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"}],
                    [{"text": "💱 Vendre sur Jupiter", "url": f"https://jup.ag/swap/{mint}-SOL"}],
                    [{"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"}],
                ]}
            elif has_tp:
                buttons = {"inline_keyboard": [[
                    {"text": "🎯 Vendre TP sur Photon", "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"},
                    {"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"},
                ]]}
            else:
                buttons = {"inline_keyboard": [[
                    {"text": "💱 Jupiter", "url": f"https://jup.ag/swap/{mint}-SOL"},
                    {"text": "💱 Photon", "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"},
                ]]}
            
            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.sell_alerts_sent += 1
            if self.dashboard: self.dashboard.add_event(f"💰 SELL ${symbol} PnL {pnl:+.0f}%")
        except Exception as e:
            logger.error(f"Sell handler: {e}")

    async def handle_dump_signal(self, dump_data: dict):
        try:
            symbol = dump_data["symbol"]; mint = dump_data["mint"]
            pct = dump_data["trigger_pct"]; trigger = dump_data["trigger"]
            severity = dump_data["severity"]
            emoji_map = {"COLLAPSE": "💀💀💀", "MAJOR_DUMP": "📉📉", "PANIC_SELL": "😱", "CRASH": "📉"}
            emoji = emoji_map.get(severity, "📉")
            msg = (f"{emoji} *DUMP DETECTED*\n━━━━━━━━━━━━━━\n\n"
                   f"💎 *${self._esc(symbol)}*\n📉 *{pct:.0f}%* en {self._esc(trigger)}\n"
                   f"⚠️ Sévérité: *{self._esc(severity)}*\n"
                   f"🟢 Buy ratio: `{dump_data['buy_ratio_1h']}%`\n"
                   f"💰 MC: `${dump_data['market_cap']/1000:.0f}K`\n\n`{mint}`")
            buttons = {"inline_keyboard": [[{"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"}]]}
            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.dump_alerts_sent += 1
            if self.dashboard: self.dashboard.add_event(f"📉 DUMP ${symbol} {pct:.0f}%")
        except Exception as e:
            logger.error(f"Dump handler: {e}")

    async def handle_whale_sell_signal(self, sell_data: dict):
        try:
            symbol = sell_data["symbol"]; mint = sell_data["mint"]
            amount = sell_data["amount_usd"]; severity = sell_data["severity"]
            is_alpha = sell_data.get("is_alpha", False); cascade = sell_data.get("cascade", False)
            emoji = "🐋🚨" if severity == "GIGA_SELL" else "🐋"
            msg = (f"{emoji} *WHALE SELL*\n━━━━━━━━━━━━━━\n\n"
                   f"💎 *${self._esc(symbol)}*\n💸 Montant: `${amount:,.0f}`\n"
                   f"⚠️ Type: *{self._esc(severity)}*\n")
            if is_alpha: msg += "🐋 *ALPHA WALLET !*\n"
            if cascade: msg += f"🌊 *CASCADE ({sell_data['cascade_count']})*\n"
            msg += (f"\n📊 PnL 5m: `{sell_data['change_5m']:+.1f}%`\n"
                    f"🟢 Buy ratio: `{sell_data['buy_ratio']}%`\n\n`{mint}`")
            buttons = {"inline_keyboard": [[{"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"}]]}
            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.whale_sell_alerts_sent += 1
            if self.dashboard: self.dashboard.add_event(f"🐋 WHALE SELL ${symbol} ${amount:,.0f}")
        except Exception as e:
            logger.error(f"Whale sell handler: {e}")

    async def handle_watch_triggered(self, alert_data: dict):
        try:
            watch = alert_data["watch"]; current = alert_data["current"]
            symbol = alert_data["symbol"]; mint = alert_data["mint"]
            type_emoji = {"MC_TARGET": "🎯", "PUMP": "🚀", "DROP": "📉", "PRICE": "💰", "VOLUME": "📊"}.get(watch["type"], "🔔")
            msg = (f"{type_emoji} *WATCHLIST ALERT*\n━━━━━━━━━━━━━━\n\n"
                   f"💎 *${self._esc(symbol)}*\nType: *{self._esc(watch['type'])}*\n"
                   f"Cible: `{watch['target']}`\n\n"
                   f"💰 Prix: `${current.get('price', 0):.8f}`\n"
                   f"💵 MC: `${current.get('market_cap', 0)/1000:.0f}K`\n"
                   f"📊 Vol 24h: `${current.get('volume_24h', 0)/1000:.0f}K`\n\n`{mint}`")
            buttons = {"inline_keyboard": [[
                {"text": "🚀 Photon", "url": f"https://photon-sol.tinyastro.io/en/lp/{mint}"},
                {"text": "📊 Chart", "url": f"https://dexscreener.com/solana/{mint}"},
            ]]}
            await self.alert_sender._send_telegram(msg, buttons=buttons)
            self.watchlist_alerts_sent += 1
            if self.dashboard: self.dashboard.add_event(f"🔔 WATCH ${symbol} {watch['type']}")
        except Exception as e:
            logger.error(f"Watch handler: {e}")

    # ═══════════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════════

    async def cleanup_all(self):
        logger.info("[CLEANUP] 🛑 Arrêt en cours...")
        try: self.perf_tracker.flush()
        except Exception as e: logger.error(f"[CLEANUP] perf: {e}")
        
        modules_to_stop = [
            ("WebSocket", self.ws_client), ("TokenSafety", self.token_safety),
            ("RadyiumMonitor", self.raydium_monitor), ("MomentumDetector", self.momentum_detector),
            ("BullAnalyzer", self.bull_analyzer), ("SellGenerator", self.sell_generator),
            ("ChartScreenshot", self.chart_screenshot), ("WalletDiscovery", self.wallet_discovery),
            ("AutoOptimizer", self.auto_optimizer), ("PortfolioTracker", self.portfolio_tracker),
            ("DumpDetector", self.dump_detector), ("WhaleSellTracker", self.whale_sell_tracker),
            ("CSVExporter", self.csv_exporter), ("Watchlist", self.watchlist),
            ("AdminSecurity", self.admin_security), ("SocialScore", self.social_score),
            ("TradeAssistant", self.trade_assistant), ("Simulator", self.simulator),
            ("Dashboard", self.dashboard),
        ]
        for name, module in modules_to_stop:
            if module is None: continue
            try:
                if hasattr(module, "stop"): await module.stop()
                logger.info(f"[CLEANUP] ✅ {name}")
            except Exception as e: logger.error(f"[CLEANUP] {name}: {e}")
        
        # Stop Evolution Orchestrator
        try:
            await stop_evolution()
            logger.info("[CLEANUP] ✅ Evolution Orchestrator")
        except Exception as e: logger.error(f"[CLEANUP] Evolution: {e}")
        
        try:
            if self.http_session and not self.http_session.closed: await self.http_session.close()
        except Exception: pass
        
        try:
            if hasattr(self.pump_monitor, "close"): await self.pump_monitor.close()
        except Exception: pass
        
        modules_to_close = [
            self.analyzer, self.alert_sender, self.position_tracker,
            self.market_context, self.alpha_tracker, self.early_detector,
            self.whale_inflow, self.twitter_tracker, self.whale_tracker,
        ]
        for module in modules_to_close:
            try:
                if hasattr(module, "close"): await module.close()
            except Exception: pass
        
        logger.info("[CLEANUP] 🎉 Arrêt complet")


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    bot = MemeSniper()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("👋 Bot arrêté (Ctrl+C)")
        asyncio.run(bot.cleanup_all())
    except Exception as e:
        logger.error(f"💥 Erreur fatale : {e}", exc_info=True)
        asyncio.run(bot.cleanup_all())