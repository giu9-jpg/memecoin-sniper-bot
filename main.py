# main.py — v10.0
# Bot Sniper Memecoin Solana - Ultimate Edition
# + Copy Trading + Early Detector + Whale Inflow
# + 15 Alpha Wallets sélectionnés (Cielo + GMGN)

import asyncio
import time
import os
from dotenv import load_dotenv

load_dotenv()

from utils.logger import logger
from modules.pump_portal_ws      import PumpPortalWebSocket
from modules.pump_fun_monitor    import PumpFunMonitor
from modules.token_analyzer      import TokenAnalyzer
from modules.alert_sender        import AlertSender
from modules.whale_tracker       import WhaleTracker
from modules.position_tracker    import PositionTracker
from modules.market_context      import MarketContext
from modules.alpha_tracker       import AlphaTracker
from modules.performance_tracker import PerformanceTracker
from modules.early_detector      import EarlyDetector
from modules.whale_inflow        import WhaleInflowTracker
from config.alpha_wallets        import (
    ALPHA_WALLETS,
    get_all_wallets,
    get_copy_threshold,
)


POLLING_INTERVAL      = 30
HEALTH_CHECK_EVERY    = 300
POSITION_CHECK_EVERY  = 60
MARKET_CHECK_EVERY    = 180
ALPHA_CHECK_EVERY     = 300
COPY_TRADING_EVERY    = 180
STATS_EVERY           = 3600
MEMORY_CLEANUP_EVERY  = 1800
MIN_SCORE             = 7.5


class MemeSniper:

    def __init__(self):
        # ── v10.0 ─────────────────────────────────────
        self.market_context    = MarketContext()
        self.alpha_tracker     = AlphaTracker()
        self.perf_tracker      = PerformanceTracker()
        self.early_detector    = EarlyDetector()
        self.whale_inflow      = WhaleInflowTracker()

        # ── Modules core (avec injections v9.0) ──────
        self.analyzer          = TokenAnalyzer(
            alpha_tracker=self.alpha_tracker,
            early_detector=self.early_detector,
            whale_inflow=self.whale_inflow,
        )
        self.alert_sender      = AlertSender(
            market_context=self.market_context
        )
        self.whale_tracker     = WhaleTracker()
        self.pump_monitor      = PumpFunMonitor()
        self.position_tracker  = PositionTracker(
            alert_sender=self.alert_sender
        )
        self.ws_client         = PumpPortalWebSocket(
            token_callback=self.handle_new_token_ws
        )

        # ── Stats ─────────────────────────────────────
        self.alerted_tokens    = set()
        self.ws_active         = False
        self.start_time        = time.time()
        self.tokens_analyzed   = 0
        self.alerts_sent       = 0
        self.copy_trades       = 0
        self.max_alerted       = 500

    # ═══════════════════════════════════════════════════
    # DÉMARRAGE
    # ═══════════════════════════════════════════════════
    async def run(self):
        # ── Compteur dynamique des wallets ────────────
        total_wallets = len(get_all_wallets())
        t1  = len(ALPHA_WALLETS.get("TIER1", []))
        t15 = len(ALPHA_WALLETS.get("TIER1_5", []))
        t2  = len(ALPHA_WALLETS.get("TIER2", []))

        logger.info("🚀 MemeSniper v10.0 démarré !")
        logger.info(f"   Score minimum      : {MIN_SCORE}/10")
        logger.info(f"   Smart Signals      : ACTIVÉS")
        logger.info(f"   Market Context     : ACTIF")
        logger.info(f"   Alpha Wallets      : ACTIF ({total_wallets} wallets | T1:{t1} T1.5:{t15} T2:{t2})")
        logger.info(f"   Copy Trading       : ACTIF")
        logger.info(f"   Early Detector     : ACTIF (v9.0)")
        logger.info(f"   Whale Inflow       : ACTIF (v9.0)")
        logger.info(f"   Performance Track  : ACTIF")
        logger.info(f"   Multi-Timeframe    : ACTIF")

        await self.market_context.fetch_market_data()
        sig = self.market_context.get_market_signal()
        logger.info(
            f"   📊 Marché : {sig['regime']} | "
            f"BTC {sig['btc_change_24h']:+.1f}% | "
            f"SOL {sig['sol_change_24h']:+.1f}% | "
            f"FG {sig['fear_greed']}"
        )

        stats = self.perf_tracker.get_stats()
        logger.info(
            f"   📈 Historique : {stats['total_alerts']} alertes | "
            f"Win rate : {stats['win_rate']}%"
        )

        await self.alert_sender.send_startup_message()

        await asyncio.gather(
            self._run_websocket(),
            self._run_polling_fallback(),
            self._run_whale_tracker(),
            self._run_health_check(),
            self._run_position_tracker(),
            self._run_market_updater(),
            self._run_alpha_updater(),
            self._run_stats_reporter(),
            self._run_memory_cleanup(),
            self._run_alpha_copy_trading(),
            return_exceptions=True
        )

    # ═══════════════════════════════════════════════════
    # BOUCLES
    # ═══════════════════════════════════════════════════

    async def _run_websocket(self):
        try:
            self.ws_active = True
            await self.ws_client.start()
        except Exception as e:
            self.ws_active = False
            logger.error(f"[WS] Mort : {e}")

    async def _run_polling_fallback(self):
        logger.info("[POLLING] Backup 30s actif")
        while True:
            try:
                tokens = await self.pump_monitor.get_new_tokens()
                for token in tokens:
                    await self.handle_new_token_polling(token)
            except Exception as e:
                logger.error(f"[POLLING] Erreur : {e}")
            await asyncio.sleep(POLLING_INTERVAL)

    async def _run_market_updater(self):
        logger.info("[MARKET] Updater actif (3 min)")
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
            except Exception as e:
                logger.error(f"[MARKET] Erreur : {e}")

    async def _run_alpha_updater(self):
        logger.info("[ALPHA] Tracker actif (5 min)")
        await asyncio.sleep(60)
        while True:
            try:
                await self.alpha_tracker.check_alpha_wallets()
                n = len(self.alpha_tracker.token_buyers)
                logger.info(f"[ALPHA] {n} token(s) tracké(s)")
            except Exception as e:
                logger.error(f"[ALPHA] Erreur : {e}")
            await asyncio.sleep(ALPHA_CHECK_EVERY)

    async def _run_alpha_copy_trading(self):
        """Alerte IMMÉDIATE quand un alpha wallet achète."""
        logger.info("[COPY] 🐋 Alpha copy-trading actif (3 min)")
        await asyncio.sleep(120)

        while True:
            try:
                async def on_alpha_buy(token, wallet, tier):
                    self.copy_trades += 1
                    tier_str = tier or "UNKNOWN"

                    logger.info(
                        f"[COPY] 🚨 {tier_str} wallet {wallet[:8]}... "
                        f"→ achat {token[:8]}..."
                    )

                    if token not in self.alerted_tokens:
                        await self._analyze_and_alert(
                            token, source=f"copy_{tier_str}"
                        )

                new_buys = await self.alpha_tracker.check_new_alpha_buys(
                    callback=on_alpha_buy
                )

                if new_buys:
                    logger.info(
                        f"[COPY] 📊 {len(new_buys)} nouveau(x) achat(s)"
                    )

            except Exception as e:
                logger.error(f"[COPY] Erreur : {e}")

            await asyncio.sleep(COPY_TRADING_EVERY)

    async def _run_whale_tracker(self):
        logger.info("[WHALE] Démarré")
        while True:
            try:
                signals = await self.whale_tracker.check_whales()
                for signal in signals:
                    addr = signal.get("token_address", "")
                    if addr and addr not in self.alerted_tokens:
                        await self._analyze_and_alert(addr, "whale")
            except Exception as e:
                logger.error(f"[WHALE] Erreur : {e}")
            await asyncio.sleep(60)

    async def _run_position_tracker(self):
        logger.info("[POSITIONS] Tracker actif (60s)")
        await asyncio.sleep(30)
        while True:
            try:
                await self.position_tracker.check_all_positions()
            except Exception as e:
                logger.error(f"[POSITIONS] Erreur : {e}")
            await asyncio.sleep(POSITION_CHECK_EVERY)

    async def _run_stats_reporter(self):
        await asyncio.sleep(3600)
        while True:
            try:
                stats_msg = self.perf_tracker.get_summary_message()
                await self.alert_sender._send_telegram(
                    stats_msg, buttons=None
                )
                logger.info("[STATS] 📊 Rapport horaire envoyé")
            except Exception as e:
                logger.error(f"[STATS] Erreur : {e}")
            await asyncio.sleep(STATS_EVERY)

    async def _run_memory_cleanup(self):
        """Nettoie la mémoire toutes les 30 minutes."""
        await asyncio.sleep(600)
        while True:
            try:
                import gc

                self.alpha_tracker.cleanup_old_data()
                self.early_detector.cleanup_old()
                self.whale_inflow.cleanup_cache()

                if len(self.alerted_tokens) > self.max_alerted:
                    self.alerted_tokens = set(
                        list(self.alerted_tokens)[-250:]
                    )

                collected = gc.collect()

                logger.info(
                    f"[MEMORY] 🧹 alerted={len(self.alerted_tokens)} | "
                    f"tokens={len(self.alpha_tracker.token_buyers)} | "
                    f"early={len(self.early_detector.recent_tokens)} | "
                    f"whales={len(self.whale_inflow.cache)} | "
                    f"gc={collected}"
                )

            except Exception as e:
                logger.error(f"[MEMORY] Erreur : {e}")

            await asyncio.sleep(MEMORY_CLEANUP_EVERY)

    async def _run_health_check(self):
        await asyncio.sleep(60)
        while True:
            uptime = int((time.time() - self.start_time) / 60)
            ws     = "✅" if self.ws_active else "❌"
            n_pos  = len([
                p for p in self.position_tracker.positions.values()
                if not p.get("closed")
            ])
            sig = self.market_context.get_market_signal()
            logger.info(
                f"[HEALTH] Uptime:{uptime}min | WS:{ws} | "
                f"Analysés:{self.tokens_analyzed} | "
                f"Alertes:{self.alerts_sent} | "
                f"Copy:{self.copy_trades} | "
                f"Positions:{n_pos} | "
                f"Marché:{sig['regime']}"
            )
            await asyncio.sleep(HEALTH_CHECK_EVERY)

    # ═══════════════════════════════════════════════════
    # HANDLERS
    # ═══════════════════════════════════════════════════

    async def handle_new_token_ws(self, token_data: dict):
        address = token_data.get("address", "")
        if not address or address in self.alerted_tokens:
            return
        symbol = token_data.get("symbol", "???")
        logger.info(f"[WS] {symbol} ({address[:8]}...)")
        await asyncio.sleep(10)
        await self._analyze_and_alert(address, source="websocket")

    async def handle_new_token_polling(self, token: dict):
        address = (
            token.get("tokenAddress")
            or token.get("address")
            or token.get("baseToken", {}).get("address", "")
        )
        if not address or address in self.alerted_tokens:
            return
        await self._analyze_and_alert(address, source="polling")

    # ═══════════════════════════════════════════════════
    # ANALYSE + ALERTE
    # ═══════════════════════════════════════════════════

    async def _analyze_and_alert(self, address: str, source: str):
        if address in self.alerted_tokens:
            return
        try:
            self.tokens_analyzed += 1
            analysis = await self.analyzer.analyze_token(address)
            if not analysis:
                return

            score        = analysis.get("score", 0)
            symbol       = analysis.get("symbol", "???")
            smart_count  = analysis.get("smart_count", 0)
            has_critical = analysis.get("has_critical", False)
            alpha_count  = analysis.get("alpha_wallets", 0)
            whale_count  = analysis.get("whale_inflow_count", 0)
            giga_count   = analysis.get("giga_whale_count", 0)
            early_signal = analysis.get("early_signal")

            critical_tag = " 🚨CRITICAL" if has_critical else ""
            alpha_tag    = f" 🐋x{alpha_count}" if alpha_count else ""
            copy_tag     = " 🚀COPY" if source.startswith("copy_") else ""
            whale_tag    = ""
            if giga_count > 0:
                whale_tag = f" 🐳GIGAx{giga_count}"
            elif whale_count > 0:
                whale_tag = f" 🐳x{whale_count}"
            early_tag = ""
            if early_signal and early_signal.get("bonus", 0) > 0:
                early_tag = " ⚡EARLY"

            logger.info(
                f"[SCORE] {symbol} — {score}/10 "
                f"| Smart:{smart_count}"
                f"{critical_tag}{alpha_tag}{copy_tag}{whale_tag}{early_tag} "
                f"| {source}"
            )

            # ── Seuil dynamique via config ────────────
            min_score = MIN_SCORE
            if source.startswith("copy_"):
                # Extraire le wallet address depuis l'analysis
                copy_wallets = analysis.get("alpha_wallet_list", [])
                if copy_wallets:
                    # Prend le seuil le plus bas parmi les wallets détectés
                    thresholds = [get_copy_threshold(w) for w in copy_wallets]
                    min_score = min(thresholds) if thresholds else MIN_SCORE
                else:
                    # Fallback par tier dans le source tag
                    if "TIER1_5" in source:
                        min_score = 6.0
                    elif "TIER1" in source:
                        min_score = 5.5
                    elif "TIER2" in source:
                        min_score = 6.5

            if score >= min_score:
                sent = await self.alert_sender.send_alert(analysis)
                if sent:
                    self.alerted_tokens.add(address)
                    self.alerts_sent += 1

                    if len(self.alerted_tokens) > self.max_alerted:
                        self.alerted_tokens = set(
                            list(self.alerted_tokens)[-250:]
                        )

                    decision = self.alert_sender.decision_eng.decide(
                        analysis
                    )

                    self.perf_tracker.record_alert(analysis, decision)

                    if decision["action"] == "ACHÈTE":
                        self.position_tracker.add_position(
                            analysis, decision, decision["amount_eur"]
                        )

                    logger.info(
                        f"[ALERT] ✅ {symbol} {score}/10 "
                        f"→ {decision['action']} {decision['tier']}"
                    )

        except Exception as e:
            logger.error(f"[ANALYZE] Erreur {address[:8]}: {e}")


# ═══════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════

async def cleanup_all(bot):
    try:
        await bot.analyzer.close()
        await bot.alert_sender.close()
        await bot.position_tracker.close()
        await bot.market_context.close()
        await bot.alpha_tracker.close()
        await bot.early_detector.close()
        await bot.whale_inflow.close()
        logger.info("[CLEANUP] Toutes les sessions fermées")
    except Exception as e:
        logger.error(f"[CLEANUP] Erreur : {e}")


if __name__ == "__main__":
    bot = MemeSniper()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("👋 Bot arrêté (Ctrl+C)")
        asyncio.run(cleanup_all(bot))
    except Exception as e:
        logger.error(f"💥 Erreur fatale : {e}")
        asyncio.run(cleanup_all(bot))