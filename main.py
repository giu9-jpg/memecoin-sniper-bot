# main.py — v2.2 — Hybride WebSocket + Polling
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
from config.settings          import settings


POLLING_INTERVAL   = 30
HEALTH_CHECK_EVERY = 300
MIN_SCORE          = settings.MIN_SCORE


class MemeSniper:

    def __init__(self):
        self.analyzer      = TokenAnalyzer()
        self.alert_sender  = AlertSender()
        self.whale_tracker = WhaleTracker()
        self.pump_monitor  = PumpFunMonitor()
        self.ws_client     = PumpPortalWebSocket(
            token_callback=self.handle_new_token_ws
        )
        self.alerted_tokens  = set()
        self.ws_active       = False
        self.start_time      = time.time()
        self.tokens_analyzed = 0
        self.alerts_sent     = 0

    async def run(self):
        logger.info("🚀 MemeSniper v2.2 démarré !")
        logger.info(f"   Score minimum : {MIN_SCORE}/10")
        await self.alert_sender.send_startup_message()
        await asyncio.gather(
            self._run_websocket(),
            self._run_polling_fallback(),
            self._run_whale_tracker(),
            self._run_health_check(),
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
        logger.info(
            f"[WS→ANALYZE] {token_data.get('symbol')} "
            f"({address[:8]}...)"
        )
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
            score = analysis.get("score", 0)
            logger.info(
                f"[SCORE] {analysis.get('symbol','???')} "
                f"— {score}/10 (via {source})"
            )
            if score >= MIN_SCORE:
                self.alerted_tokens.add(address)
                self.alerts_sent += 1
                await self.alert_sender.send_token_alert(analysis)
                logger.info(
                    f"[ALERT] ✅ {analysis.get('symbol')} "
                    f"{score}/10"
                )
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
                        await self._analyze_and_alert(
                            addr, "whale_signal"
                        )
            except Exception as e:
                logger.error(f"[WHALE] Erreur : {e}")
            await asyncio.sleep(60)

    async def _run_health_check(self):
        await asyncio.sleep(60)
        while True:
            uptime = int((time.time() - self.start_time) / 60)
            ws     = "✅" if self.ws_active else "❌"
            logger.info(
                f"[HEALTH] Uptime:{uptime}min | WS:{ws} | "
                f"Analysés:{self.tokens_analyzed} | "
                f"Alertes:{self.alerts_sent}"
            )
            await asyncio.sleep(HEALTH_CHECK_EVERY)


if __name__ == "__main__":
    bot = MemeSniper()
    asyncio.run(bot.run())