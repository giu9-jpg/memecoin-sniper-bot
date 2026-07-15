# main.py — v5.1 — Hybride WebSocket + Polling + Smart Signals + Position Tracking
import asyncio
import time
import os
from dotenv import load_dotenv

load_dotenv()

from utils.logger import logger
from modules.pump_portal_ws    import PumpPortalWebSocket
from modules.pump_fun_monitor  import PumpFunMonitor
from modules.token_analyzer    import TokenAnalyzer
from modules.alert_sender      import AlertSender
from modules.whale_tracker     import WhaleTracker
from modules.position_tracker  import PositionTracker


POLLING_INTERVAL     = 30
HEALTH_CHECK_EVERY   = 300
POSITION_CHECK_EVERY = 60
MIN_SCORE            = 7.5


class MemeSniper:

    def __init__(self):
        self.analyzer         = TokenAnalyzer()
        self.alert_sender     = AlertSender()
        self.whale_tracker    = WhaleTracker()
        self.pump_monitor     = PumpFunMonitor()
        self.position_tracker = PositionTracker(alert_sender=self.alert_sender)
        self.ws_client        = PumpPortalWebSocket(
            token_callback=self.handle_new_token_ws
        )
        self.alerted_tokens  = set()
        self.ws_active       = False
        self.start_time      = time.time()
        self.tokens_analyzed = 0
        self.alerts_sent     = 0

    async def run(self):
        logger.info("🚀 MemeSniper v5.1 démarré !")
        logger.info(f"   Score minimum : {MIN_SCORE}/10")
        logger.info(f"   Smart Signals : ACTIVÉS")
        logger.info(f"   Decision Engine : ACTIF")
        logger.info(f"   Position Tracker : ACTIF")

        await self.alert_sender.send_startup_message()

        await asyncio.gather(
            self._run_websocket(),
            self._run_polling_fallback(),
            self._run_whale_tracker(),
            self._run_health_check(),
            self._run_position_tracker(),
            return_exceptions=True
        )

    async def _run_websocket(self):
        try:
            self.ws_active = True
            await self.ws_client.start()
        except Exception as e:
            self.ws_active = False
            logger.error(f"[MAIN] WebSocket mort : {e}")

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

    async def handle_new_token_ws(self, token_data):
        address = token_data.get("address", "")
        if not address or address in self.alerted_tokens:
            return
        logger.info(f"[WS→ANALYZE] {token_data.get('symbol')} ({address[:8]}...)")
        await asyncio.sleep(10)
        await self._analyze_and_alert(address, source="websocket")

    async def handle_new_token_polling(self, token):
        address = (
            token.get("tokenAddress")
            or token.get("address")
            or token.get("baseToken", {}).get("address", "")
        )
        if not address or address in self.alerted_tokens:
            return
        await self._analyze_and_alert(address, source="polling")

    async def _analyze_and_alert(self, address, source):
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

            critical_tag = " 🚨CRITICAL" if has_critical else ""
            logger.info(
                f"[SCORE] {symbol} — {score}/10 "
                f"| Smart:{smart_count}{critical_tag} (via {source})"
            )

            if score >= MIN_SCORE:
                sent = await self.alert_sender.send_alert(analysis)
                if sent:
                    self.alerted_tokens.add(address)
                    self.alerts_sent += 1

                    # Enregistrer la position potentielle
                    decision = self.alert_sender.decision_eng.decide(analysis)
                    if decision["action"] == "ACHÈTE":
                        self.position_tracker.add_position(
                            analysis, decision, decision["amount_eur"]
                        )
                        logger.info(f"[POSITION] {symbol} tracké pour TP/SL")

                    logger.info(f"[ALERT] ✅ {symbol} {score}/10 envoyé")

        except Exception as e:
            logger.error(f"[ANALYZE] Erreur {address[:8]}: {e}")

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
        logger.info("[POSITIONS] Tracker actif (check 60s)")
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
            logger.info(
                f"[HEALTH] Uptime:{uptime}min | WS:{ws} | "
                f"Analysés:{self.tokens_analyzed} | "
                f"Alertes:{self.alerts_sent} | "
                f"Positions:{n_positions}"
            )
            await asyncio.sleep(HEALTH_CHECK_EVERY)


if __name__ == "__main__":
    bot = MemeSniper()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("👋 Bot arrêté proprement (Ctrl+C)")
    except Exception as e:
        logger.error(f"💥 Erreur fatale : {e}")