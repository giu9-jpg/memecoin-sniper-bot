# main.py — v6.0
# Bot Sniper Memecoin Solana - Ultimate Edition

import asyncio
import time
import os
from dotenv import load_dotenv

load_dotenv()

from utils.logger import logger
from modules.pump_portal_ws   import PumpPortalWebSocket
from modules.pump_fun_monitor import PumpFunMonitor
from modules.token_analyzer   import TokenAnalyzer
from modules.alert_sender     import AlertSender
from modules.whale_tracker    import WhaleTracker
from modules.position_tracker import PositionTracker
from modules.market_context   import MarketContext
from modules.alpha_tracker    import AlphaTracker


POLLING_INTERVAL     = 30
HEALTH_CHECK_EVERY   = 300
POSITION_CHECK_EVERY = 60
MARKET_CHECK_EVERY   = 180
ALPHA_CHECK_EVERY    = 300
MIN_SCORE            = 7.5


class MemeSniper:

    def __init__(self):
        # ── v6.0 — Market Context + Alpha Tracker ─────
        self.market_context   = MarketContext()
        self.alpha_tracker    = AlphaTracker()

        # ── Modules core ──────────────────────────────
        self.analyzer         = TokenAnalyzer(alpha_tracker=self.alpha_tracker)
        self.alert_sender     = AlertSender(market_context=self.market_context)
        self.whale_tracker    = WhaleTracker()
        self.pump_monitor     = PumpFunMonitor()
        self.position_tracker = PositionTracker(alert_sender=self.alert_sender)
        self.ws_client        = PumpPortalWebSocket(
            token_callback=self.handle_new_token_ws
        )

        # ── Stats ─────────────────────────────────────
        self.alerted_tokens  = set()
        self.ws_active       = False
        self.start_time      = time.time()
        self.tokens_analyzed = 0
        self.alerts_sent     = 0

    # ═══════════════════════════════════════════════════
    # DÉMARRAGE
    # ═══════════════════════════════════════════════════
    async def run(self):
        logger.info("🚀 MemeSniper v6.0 démarré !")
        logger.info(f"   Score minimum    : {MIN_SCORE}/10")
        logger.info(f"   Smart Signals    : ACTIVÉS")
        logger.info(f"   Market Context   : ACTIF (BTC/SOL/FG)")
        logger.info(f"   Alpha Wallets    : ACTIF")
        logger.info(f"   Decision Engine  : v6.0")
        logger.info(f"   Position Tracker : ACTIF")

        # Fetch initial contexte marché
        await self.market_context.fetch_market_data()
        sig = self.market_context.get_market_signal()
        logger.info(
            f"   📊 Marché actuel : {sig['regime']} | "
            f"BTC {sig['btc_change_24h']:+.1f}% | "
            f"SOL {sig['sol_change_24h']:+.1f}% | "
            f"FG {sig['fear_greed']}"
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
            return_exceptions=True
        )

    # ═══════════════════════════════════════════════════
    # BOUCLES PRINCIPALES
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
        """Met à jour le contexte marché toutes les 3 min."""
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
        """Met à jour les alpha wallets toutes les 5 min."""
        logger.info("[ALPHA] Tracker actif (5 min)")
        await asyncio.sleep(60)   # délai initial
        while True:
            try:
                await self.alpha_tracker.check_alpha_wallets()
                tokens_tracked = len(self.alpha_tracker.token_buyers)
                logger.info(f"[ALPHA] {tokens_tracked} token(s) tracké(s)")
            except Exception as e:
                logger.error(f"[ALPHA] Erreur : {e}")
            await asyncio.sleep(ALPHA_CHECK_EVERY)

    async def _run_whale_tracker(self):
        logger.info("[WHALE] Démarré")
        while True:
            try:
                signals = await self.whale_tracker.check_whales()
                for signal in signals:
                    addr = signal.get("token_address", "")
                    if addr and addr not in self.alerted_tokens:
                        await self._analyze_and_alert(addr, "whale_signal")
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

    async def _run_health_check(self):
        await asyncio.sleep(60)
        while True:
            uptime      = int((time.time() - self.start_time) / 60)
            ws          = "✅" if self.ws_active else "❌"
            n_positions = len([
                p for p in self.position_tracker.positions.values()
                if not p.get("closed")
            ])
            sig = self.market_context.get_market_signal()
            logger.info(
                f"[HEALTH] Uptime:{uptime}min | WS:{ws} | "
                f"Analysés:{self.tokens_analyzed} | "
                f"Alertes:{self.alerts_sent} | "
                f"Positions:{n_positions} | "
                f"Marché:{sig['regime']}"
            )
            await asyncio.sleep(HEALTH_CHECK_EVERY)

    # ═══════════════════════════════════════════════════
    # HANDLERS TOKENS
    # ═══════════════════════════════════════════════════

    async def handle_new_token_ws(self, token_data: dict):
        address = token_data.get("address", "")
        if not address or address in self.alerted_tokens:
            return
        symbol = token_data.get("symbol", "???")
        logger.info(f"[WS] Nouveau token : {symbol} ({address[:8]}...)")
        await asyncio.sleep(10)   # attendre un peu de liquidité
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

            # Tags pour le log
            critical_tag = " 🚨CRITICAL" if has_critical else ""
            alpha_tag    = f" 🐋x{alpha_count}" if alpha_count else ""

            logger.info(
                f"[SCORE] {symbol} — {score}/10 "
                f"| Smart:{smart_count}{critical_tag}{alpha_tag} "
                f"| via {source}"
            )

            if score >= MIN_SCORE:
                sent = await self.alert_sender.send_alert(analysis)
                if sent:
                    self.alerted_tokens.add(address)
                    self.alerts_sent += 1

                    # Ajouter en position tracker
                    decision = self.alert_sender.decision_eng.decide(analysis)
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

if __name__ == "__main__":
    bot = MemeSniper()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("👋 Bot arrêté proprement (Ctrl+C)")
    except Exception as e:
        logger.error(f"💥 Erreur fatale : {e}")