# modules/pump_portal_ws.py — v2.1 FIXED
# FIX : seen_tokens dict avec timestamp
# FIX : close() complet avec annulation heartbeat
# FIX : reconnexion exponentielle avec jitter
# FIX : rate limit plus robuste
# FIX : heartbeat vérifie si ws est encore ouvert
# FIX : messages de ping/pong ignorés proprement

import asyncio
import json
import random
import time
import websockets
from utils.logger import logger

PUMP_PORTAL_WS_URL      = "wss://pumpportal.fun/api/data"
RECONNECT_DELAYS        = [5, 10, 20, 40, 60]
HEARTBEAT_INTERVAL      = 30
MAX_RECONNECTS_PER_HOUR = 10
RATE_LIMIT_PER_MINUTE   = 10
MAX_SEEN_TOKENS         = 10_000
KEEP_SEEN_TOKENS        = 5_000


class PumpPortalWebSocket:

    def __init__(self, token_callback):
        self.token_callback       = token_callback
        self.ws                   = None
        self.running              = False
        self.reconnect_timestamps: list[float] = []

        # FIX : dict {address: timestamp} au lieu d'un set
        self.seen_tokens: dict[str, float] = {}

        self.alert_timestamps: list[float] = []
        self._heartbeat_task: asyncio.Task | None = None

    # ═══════════════════════════════════════════════════
    # DÉMARRAGE
    # ═══════════════════════════════════════════════════

    async def start(self):
        """
        Boucle principale de connexion avec reconnexion automatique.
        FIX : jitter aléatoire sur les délais pour éviter les reconnexions
              synchronisées avec d'autres bots.
        """
        self.running = True
        attempt      = 0

        while self.running:
            try:
                if attempt > 0:
                    base_delay = RECONNECT_DELAYS[
                        min(attempt - 1, len(RECONNECT_DELAYS) - 1)
                    ]
                    # FIX : jitter ±20% pour éviter le thundering herd
                    jitter = random.uniform(0.8, 1.2)
                    delay  = base_delay * jitter
                    logger.info(
                        f"[WS] Reconnexion dans {delay:.0f}s "
                        f"(tentative #{attempt})"
                    )
                    await asyncio.sleep(delay)

                logger.info("[WS] Connexion à PumpPortal...")
                await self._connect_and_listen()
                attempt = 0   # Reset si connexion réussie

            except asyncio.CancelledError:
                logger.info("[WS] Annulé proprement")
                break

            except Exception as e:
                attempt += 1
                self._record_reconnect()
                logger.error(f"[WS] Erreur connexion : {e}")

                if self._too_many_reconnects():
                    logger.critical(
                        "[WS] ⚠️ Trop de reconnexions "
                        "— pause 10 min"
                    )
                    await asyncio.sleep(600)
                    self.reconnect_timestamps.clear()
                    attempt = 0

    # ═══════════════════════════════════════════════════
    # ARRÊT
    # ═══════════════════════════════════════════════════

    async def stop(self):
        """
        Arrête proprement le WebSocket.
        FIX : annule le heartbeat avant de fermer le WS.
        """
        self.running = False

        # FIX : annule le heartbeat d'abord
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        # Ferme le WebSocket
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None

        logger.info("[WS] Arrêté proprement")

    # ═══════════════════════════════════════════════════
    # CONNEXION ET ÉCOUTE
    # ═══════════════════════════════════════════════════

    async def _connect_and_listen(self):
        """Connexion WebSocket et boucle de lecture des messages."""
        async with websockets.connect(
            PUMP_PORTAL_WS_URL,
            ping_interval=None,    # On gère le ping manuellement
            close_timeout=10,
            max_size=2 ** 20,      # 1 MB max par message
            open_timeout=15,       # FIX : timeout de connexion
        ) as ws:
            self.ws = ws
            logger.info("[WS] ✅ Connecté à PumpPortal.fun !")

            # Souscriptions
            await self._subscribe(ws)

            # Lance le heartbeat
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(ws)
            )

            # Boucle de lecture
            try:
                async for raw_message in ws:
                    if not self.running:
                        break
                    await self._handle_message(raw_message)
            finally:
                # FIX : annule le heartbeat quand la boucle se termine
                if (
                    self._heartbeat_task
                    and not self._heartbeat_task.done()
                ):
                    self._heartbeat_task.cancel()

    # ═══════════════════════════════════════════════════
    # SOUSCRIPTIONS
    # ═══════════════════════════════════════════════════

    async def _subscribe(self, ws):
        """S'abonne aux événements PumpPortal."""
        subscriptions = [
            {"method": "subscribeNewToken"},
            {"method": "subscribeNewBondingCurve"},
        ]
        for sub in subscriptions:
            try:
                await ws.send(json.dumps(sub))
                logger.info(f"[WS] ✅ Abonné : {sub['method']}")
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(
                    f"[WS] Erreur souscription {sub['method']}: {e}"
                )

    # ═══════════════════════════════════════════════════
    # HEARTBEAT
    # ═══════════════════════════════════════════════════

    async def _heartbeat_loop(self, ws):
        """
        Envoie un ping toutes les 30s pour maintenir la connexion.
        FIX : vérifie que le ws est encore ouvert avant d'envoyer.
        FIX : s'arrête proprement sur CancelledError.
        """
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                # FIX : vérifie l'état du WebSocket
                if ws.closed:
                    logger.debug("[WS] Heartbeat : WS fermé, arrêt")
                    break

                try:
                    await ws.send(json.dumps({"method": "ping"}))
                    logger.debug("[WS] Heartbeat envoyé")
                except websockets.exceptions.ConnectionClosed:
                    logger.debug("[WS] Heartbeat : connexion fermée")
                    break
                except Exception as e:
                    logger.debug(f"[WS] Heartbeat erreur : {e}")
                    break

        except asyncio.CancelledError:
            pass   # Arrêt propre

    # ═══════════════════════════════════════════════════
    # TRAITEMENT DES MESSAGES
    # ═══════════════════════════════════════════════════

    async def _handle_message(self, raw_message: str):
        """
        Parse et route un message WebSocket.
        FIX : ignore les messages système sans planter.
        """
        try:
            data = json.loads(raw_message)
        except json.JSONDecodeError:
            logger.debug(f"[WS] Message non-JSON ignoré")
            return

        # FIX : ignore les messages système (pong, status, errors)
        if not isinstance(data, dict):
            return
        if data.get("message") or data.get("status") or data.get("pong"):
            return
        if data.get("error"):
            logger.warning(f"[WS] Erreur serveur : {data['error']}")
            return

        # Détecte le type d'événement
        event_type = (
            data.get("txType")
            or data.get("type")
            or data.get("event")
            or ""
        )

        NEW_TOKEN_EVENTS = {
            "create",
            "newToken",
            "newBondingCurve",
            "new_token",
            "token_created",
        }

        if event_type in NEW_TOKEN_EVENTS:
            await self._process_new_token(data)

    # ═══════════════════════════════════════════════════
    # TRAITEMENT NOUVEAU TOKEN
    # ═══════════════════════════════════════════════════

    async def _process_new_token(self, data: dict):
        """
        Traite un nouveau token détecté.
        FIX : validation adresse plus stricte.
        FIX : nettoyage seen_tokens par timestamp.
        """
        token_address = (
            data.get("mint")
            or data.get("tokenAddress")
            or data.get("address")
            or ""
        )

        # ── Validation ────────────────────────────────
        if not token_address:
            return
        if len(token_address) < 32 or len(token_address) > 44:
            return
        if token_address.startswith("0x"):
            return

        # ── Déduplication ─────────────────────────────
        if token_address in self.seen_tokens:
            return

        # FIX : enregistre avec timestamp
        self.seen_tokens[token_address] = time.time()

        # Nettoyage si trop de tokens en mémoire
        if len(self.seen_tokens) > MAX_SEEN_TOKENS:
            self._cleanup_seen_tokens()

        # ── Rate limiting ─────────────────────────────
        if not self._check_rate_limit():
            logger.debug(
                f"[WS] Rate limit atteint, token mis en attente"
            )
            await asyncio.sleep(3)

        # ── Construction du token_data ────────────────
        token_data = {
            "address":   token_address,
            "name":      data.get("name", "Unknown"),
            "symbol":    data.get("symbol", "???"),
            "creator":   (
                data.get("traderPublicKey")
                or data.get("creator")
                or ""
            ),
            "timestamp": data.get("timestamp", int(time.time())),
            "source":    "pumpportal_ws",
            # Données supplémentaires si disponibles
            "initial_buy": data.get("initialBuy", 0),
            "market_cap":  data.get("marketCapSol", 0),
        }

        logger.info(
            f"[WS] 🆕 {token_data['symbol']} "
            f"({token_address[:8]}...)"
        )

        # ── Callback ──────────────────────────────────
        try:
            await self.token_callback(token_data)
        except Exception as e:
            logger.error(f"[WS] Erreur callback : {e}")

    # ═══════════════════════════════════════════════════
    # RATE LIMITING
    # ═══════════════════════════════════════════════════

    def _check_rate_limit(self) -> bool:
        """
        Vérifie le rate limit (10 tokens/minute max).
        FIX : nettoyage avant le check.
        """
        now = time.time()

        # FIX : nettoie avant de compter
        self.alert_timestamps = [
            t for t in self.alert_timestamps
            if now - t < 60
        ]

        if len(self.alert_timestamps) >= RATE_LIMIT_PER_MINUTE:
            logger.warning(
                f"[WS] ⚠️ Rate limit : "
                f"{len(self.alert_timestamps)}/{RATE_LIMIT_PER_MINUTE} "
                f"tokens/min"
            )
            return False

        self.alert_timestamps.append(now)
        return True

    # ═══════════════════════════════════════════════════
    # RECONNEXION
    # ═══════════════════════════════════════════════════

    def _record_reconnect(self):
        """Enregistre une tentative de reconnexion."""
        now = time.time()
        self.reconnect_timestamps.append(now)
        # Nettoie les reconnexions > 1h
        self.reconnect_timestamps = [
            t for t in self.reconnect_timestamps
            if now - t < 3600
        ]

    def _too_many_reconnects(self) -> bool:
        """Retourne True si trop de reconnexions dans la dernière heure."""
        return len(self.reconnect_timestamps) >= MAX_RECONNECTS_PER_HOUR

    # ═══════════════════════════════════════════════════
    # NETTOYAGE MÉMOIRE
    # ═══════════════════════════════════════════════════

    def _cleanup_seen_tokens(self):
        """
        Nettoie seen_tokens par ancienneté.
        FIX : supprime les plus vieux d'abord.
        """
        # Trie par timestamp et garde les plus récents
        sorted_tokens = sorted(
            self.seen_tokens.items(),
            key=lambda x: x[1],
            reverse=True,
        )
        self.seen_tokens = dict(sorted_tokens[:KEEP_SEEN_TOKENS])
        logger.debug(
            f"[WS] 🧹 seen_tokens tronqué à {KEEP_SEEN_TOKENS}"
        )