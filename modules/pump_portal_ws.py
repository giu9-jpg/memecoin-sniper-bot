# modules/pump_portal_ws.py
import asyncio
import json
import time
import websockets
from utils.logger import logger

PUMP_PORTAL_WS_URL      = "wss://pumpportal.fun/api/data"
RECONNECT_DELAYS        = [5, 10, 20, 40, 60]
HEARTBEAT_INTERVAL      = 30
MAX_RECONNECTS_PER_HOUR = 10
RATE_LIMIT_PER_MINUTE   = 10


class PumpPortalWebSocket:

    def __init__(self, token_callback):
        self.token_callback       = token_callback
        self.ws                   = None
        self.running              = False
        self.reconnect_count      = 0
        self.reconnect_timestamps = []
        self.seen_tokens          = set()
        self.alert_timestamps     = []
        self._heartbeat_task      = None

    async def start(self):
        self.running = True
        attempt      = 0
        while self.running:
            try:
                delay = RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]
                if attempt > 0:
                    logger.info(f"[WS] Reconnexion dans {delay}s (tentative #{attempt})")
                    await asyncio.sleep(delay)
                logger.info(f"[WS] Connexion à PumpPortal...")
                await self._connect_and_listen()
                attempt = 0
            except Exception as e:
                attempt += 1
                self._record_reconnect()
                logger.error(f"[WS] Erreur : {e}")
                if self._too_many_reconnects():
                    logger.critical("[WS] Trop de reconnexions — pause 10 min")
                    await asyncio.sleep(600)
                    self.reconnect_timestamps.clear()
                    attempt = 0

    async def stop(self):
        self.running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self.ws:
            await self.ws.close()

    async def _connect_and_listen(self):
        async with websockets.connect(
            PUMP_PORTAL_WS_URL,
            ping_interval=None,
            close_timeout=10,
            max_size=2**20
        ) as ws:
            self.ws = ws
            logger.info("[WS] ✅ Connecté à PumpPortal.fun !")
            await self._subscribe(ws)
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(ws)
            )
            async for raw_message in ws:
                await self._handle_message(raw_message)

    async def _subscribe(self, ws):
        for sub in [
            {"method": "subscribeNewToken"},
            {"method": "subscribeNewBondingCurve"},
        ]:
            await ws.send(json.dumps(sub))
            logger.info(f"[WS] Abonné : {sub['method']}")
            await asyncio.sleep(0.2)

    async def _heartbeat_loop(self, ws):
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                try:
                    await ws.send(json.dumps({"method": "ping"}))
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def _handle_message(self, raw_message):
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            return

        if data.get("message") or data.get("status"):
            return

        event_type = data.get("txType") or data.get("type", "")
        if event_type in ("create", "newToken", "newBondingCurve"):
            await self._process_new_token(data)

    async def _process_new_token(self, data):
        token_address = (
            data.get("mint")
            or data.get("tokenAddress")
            or data.get("address", "")
        )

        if not token_address or len(token_address) < 32:
            return
        if token_address.startswith("0x"):
            return
        if token_address in self.seen_tokens:
            return

        self.seen_tokens.add(token_address)
        if len(self.seen_tokens) > 10_000:
            self.seen_tokens = set(list(self.seen_tokens)[-5_000:])

        if not self._check_rate_limit():
            await asyncio.sleep(3)

        token_data = {
            "address":   token_address,
            "name":      data.get("name", "Unknown"),
            "symbol":    data.get("symbol", "???"),
            "creator":   data.get("traderPublicKey", ""),
            "timestamp": data.get("timestamp", int(time.time())),
            "source":    "pumpportal_ws",
        }

        logger.info(f"[WS] 🆕 {token_data['symbol']} ({token_address[:8]}...)")

        try:
            await self.token_callback(token_data)
        except Exception as e:
            logger.error(f"[WS] Erreur callback : {e}")

    def _check_rate_limit(self):
        now = time.time()
        self.alert_timestamps = [
            t for t in self.alert_timestamps if now - t < 60
        ]
        if len(self.alert_timestamps) >= RATE_LIMIT_PER_MINUTE:
            return False
        self.alert_timestamps.append(now)
        return True

    def _record_reconnect(self):
        now = time.time()
        self.reconnect_timestamps.append(now)
        self.reconnect_timestamps = [
            t for t in self.reconnect_timestamps if now - t < 3600
        ]

    def _too_many_reconnects(self):
        return len(self.reconnect_timestamps) >= MAX_RECONNECTS_PER_HOUR