# main.py — v12.0 SAFETY + COMMANDES
# Bot Sniper Memecoin Solana - Ultimate Edition
# + Copy Trading + Early Detector + Whale Inflow
# + 15 Alpha Wallets sélectionnés (Cielo + GMGN)
# + Twitter Tracker (7 comptes Nitter)
# + Performance Tracker v7.1
# + PumpFunMonitor v2.3 + PumpPortalWebSocket v2.1
# + TokenSafety Anti-Rug avancé
# + NOUVEAU v12.0 : Commandes Telegram interactives
# + PAS de trading automatique achat/vente

import asyncio
import gc
import time
import os
import aiohttp
from dotenv import load_dotenv

load_dotenv()

from utils.logger import logger
from utils.config_loader import load_config

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
from modules.twitter_tracker     import TwitterTracker
from modules.token_safety        import TokenSafety

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
COMMAND_POLL_EVERY   = 2      # v12.0: check commandes Telegram
MIN_SCORE            = 7.5


# ═══════════════════════════════════════════════════════
# BOT PRINCIPAL
# ═══════════════════════════════════════════════════════

class MemeSniper:

    def __init__(self):

        # ── Config v12.0 ──────────────────────────────
        self.config = load_config()

        # ── Modules contexte / tracking ───────────────
        self.market_context  = MarketContext()
        self.alpha_tracker   = AlphaTracker()
        self.perf_tracker    = PerformanceTracker()
        self.early_detector  = EarlyDetector()
        self.whale_inflow    = WhaleInflowTracker()
        self.twitter_tracker = TwitterTracker()

        # ── Module sécurité v12.0 ─────────────────────
        self.token_safety = TokenSafety(self.config.solana_rpc_url)

        # ── Modules core ──────────────────────────────
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

        self.position_tracker = PositionTracker(
            alert_sender=self.alert_sender
        )

        self.ws_client = PumpPortalWebSocket(
            token_callback=self.handle_new_token_ws
        )

        # ── Session HTTP pour commandes Telegram (v12.0) ──
        self.http_session = None

        # ── État interne ──────────────────────────────
        self.alerted_tokens = {}
        self.processing_tokens = set()
        self.paused = False  # v12.0: pause/resume

        self.ws_active        = False
        self.start_time       = time.time()
        self.tokens_analyzed  = 0
        self.alerts_sent      = 0
        self.copy_trades      = 0
        self.twitter_signals  = 0
        self.max_alerted      = 500

        # ── v12.0: offset Telegram pour polling commandes
        self.telegram_offset = 0

    # ═══════════════════════════════════════════════════
    # DÉMARRAGE
    # ═══════════════════════════════════════════════════

    async def run(self):
        """Point d'entrée principal du bot."""

        # ── Session HTTP partagée (v12.0) ─────────────
        self.http_session = aiohttp.ClientSession()

        # ── Démarrage TokenSafety v12.0 ───────────────
        try:
            await self.token_safety.start()
            logger.info("🛡️ TokenSafety v12.0 : ACTIF")
        except Exception as e:
            logger.error(f"❌ Impossible de démarrer TokenSafety : {e}")
            raise

        # ── Infos wallets ─────────────────────────────
        total_wallets = len(get_all_wallets())
        t1            = len(ALPHA_WALLETS.get("TIER1",   []))
        t15           = len(ALPHA_WALLETS.get("TIER1_5", []))
        t2            = len(ALPHA_WALLETS.get("TIER2",   []))

        # ── Infos Twitter ─────────────────────────────
        twitter_count = len(get_all_twitter_accounts())
        t1_tw         = len(ALPHA_ACCOUNTS.get("TIER1", []))
        t2_tw         = len(ALPHA_ACCOUNTS.get("TIER2", []))
        t3_tw         = len(ALPHA_ACCOUNTS.get("TIER3", []))

        # ── Logs de démarrage ─────────────────────────
        logger.info("🚀 MemeSniper v12.0 SAFETY démarré !")
        logger.info(f"   Score minimum      : {MIN_SCORE}/10")
        logger.info(f"   Smart Signals      : ACTIVÉS")
        logger.info(f"   Market Context     : ACTIF")
        logger.info(f"   Anti-Rug Safety    : ACTIF")
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
        logger.info(f"   PumpPortal WS      : ACTIF (v2.1)")
        logger.info(f"   Polling Fallback   : ACTIF (v2.3)")
        logger.info(f"   Commandes Telegram : ACTIF (v12.0)")
        logger.info(f"   Trading Auto       : DÉSACTIVÉ")

        # ── Contexte marché au démarrage ──────────────
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

        # ── Historique des performances ───────────────
        try:
            stats = self.perf_tracker.get_stats()
            logger.info(
                f"   📈 Historique : {stats['total_alerts']} alertes | "
                f"Win rate : {stats['win_rate']}%"
            )
        except Exception as e:
            logger.warning(f"   ⚠️ Performance tracker : {e}")

        # ── Message de démarrage Telegram ─────────────
        try:
            await self.alert_sender.send_startup_message()
        except Exception as e:
            logger.warning(f"   ⚠️ Message startup Telegram : {e}")

        # ── Purge des vieilles commandes Telegram ─────
        # Pour ne pas exécuter des commandes envoyées avant le démarrage
        try:
            await self._init_telegram_offset()
        except Exception as e:
            logger.warning(f"   ⚠️ Init Telegram offset : {e}")

        # ── Lancement de toutes les boucles ───────────
        logger.info("   ⚙️  Lancement des boucles...")

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
            self._run_twitter_tracker(),
            self._run_command_listener(),   # v12.0
            return_exceptions=True,
        )

    # ═══════════════════════════════════════════════════
    # BOUCLES PRINCIPALES
    # ═══════════════════════════════════════════════════

    async def _run_websocket(self):
        """Écoute les nouveaux tokens via WebSocket PumpPortal."""
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
        """Backup polling toutes les 30s."""
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

    async def _run_market_updater(self):
        """Met à jour le contexte marché toutes les 3 minutes."""
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
        """Scan général des alpha wallets toutes les 5 minutes."""
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
        """Copy trading : alerte immédiate quand un alpha wallet achète."""
        logger.info(
            f"[COPY] 🐋 Alpha copy-trading actif "
            f"({COPY_TRADING_EVERY}s)"
        )
        await asyncio.sleep(120)

        while True:
            try:
                async def on_alpha_buy(
                    token: str,
                    wallet: str,
                    tier: str
                ):
                    self.copy_trades += 1
                    tier_str = tier or "UNKNOWN"

                    logger.info(
                        f"[COPY] 🚨 {tier_str} "
                        f"{wallet[:8]}... → "
                        f"achat {token[:8]}..."
                    )

                    if token not in self.alerted_tokens:
                        await self._analyze_and_alert(
                            token,
                            source=f"copy_{tier_str}",
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
        """Scan des tweets alpha toutes les 5 minutes."""
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

                    for address in addrs:
                        if address not in self.alerted_tokens:
                            await self._analyze_and_alert(
                                address,
                                source=f"twitter_{tier}",
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
        """Surveille les gros wallets Solana."""
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
                        f"{addr[:8]}... "
                        f"(${amt:,.0f})"
                    )

                    await self._analyze_and_alert(
                        addr,
                        source="whale"
                    )

            except asyncio.CancelledError:
                break

            except Exception as e:
                logger.error(f"[WHALE] Erreur : {e}")

            await asyncio.sleep(60)

    async def _run_position_tracker(self):
        """Vérifie les TP/SL des positions ouvertes toutes les 60s."""
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
        """Envoie un rapport de performance Telegram toutes les heures."""
        logger.info(f"[STATS] Reporter actif (toutes les heures)")
        await asyncio.sleep(STATS_EVERY)

        while True:
            try:
                stats_msg = self.perf_tracker.get_summary_message()
                await self.alert_sender._send_telegram(
                    stats_msg,
                    buttons=None
                )
                logger.info("[STATS] 📊 Rapport horaire envoyé")

            except asyncio.CancelledError:
                break

            except Exception as e:
                logger.error(f"[STATS] Erreur : {e}")

            await asyncio.sleep(STATS_EVERY)

    async def _run_memory_cleanup(self):
        """Nettoyage mémoire toutes les 30 minutes."""
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
                    f"gc={collected}"
                )

            except asyncio.CancelledError:
                break

            except Exception as e:
                logger.error(f"[MEMORY] Erreur : {e}")

            await asyncio.sleep(MEMORY_CLEANUP_EVERY)

    async def _run_health_check(self):
        """Log de santé du bot toutes les 5 minutes."""
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

                logger.info(
                    f"[HEALTH] "
                    f"{pause_status} | "
                    f"Uptime:{uptime}min | "
                    f"WS:{ws_status} | "
                    f"Analysés:{self.tokens_analyzed} | "
                    f"Alertes:{self.alerts_sent} | "
                    f"Copy:{self.copy_trades} | "
                    f"Twitter:{self.twitter_signals} | "
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
    # COMMANDES TELEGRAM v12.0
    # ═══════════════════════════════════════════════════

    async def _init_telegram_offset(self):
        """
        Récupère l'offset actuel Telegram pour ignorer
        les vieilles commandes envoyées avant le démarrage.
        """
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
                        # Prendre le dernier + 1 pour ignorer tout
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
        """
        Écoute les commandes /xxx envoyées dans Telegram.
        Polling toutes les 2 secondes.
        """
        logger.info(f"[CMD] 📱 Command listener actif ({COMMAND_POLL_EVERY}s)")

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
                            chat = str(msg.get("chat", {}).get("id", ""))

                            # Sécurité : notre chat SEULEMENT
                            if chat != chat_id:
                                logger.warning(
                                    f"[CMD] ⚠️ Commande ignorée "
                                    f"(chat inconnu: {chat})"
                                )
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
        """Route vers le bon handler selon la commande"""

        text_lower = text.lower().strip()

        logger.info(f"[CMD] 📥 Reçu : {text}")

        # Commandes avec arguments
        if text_lower.startswith("/check "):
            mint = text[7:].strip()
            await self._cmd_check(mint)
            return

        # Commandes simples
        routes = {
            "/status":  self._cmd_status,
            "/stats":   self._cmd_stats,
            "/alertes": self._cmd_alertes,
            "/pause":   self._cmd_pause,
            "/resume":  self._cmd_resume,
            "/help":    self._cmd_help,
            "/start":   self._cmd_help,
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
        """Commande /status - État du bot"""
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

        msg = (
            f"🤖 *MemeSniper v12\\.0 SAFETY*\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"⏱ Uptime: `{h}h {m}m {s}s`\n"
            f"🔄 État: *{self._esc(pause_str)}*\n"
            f"📡 WebSocket: {ws_str}\n"
            f"🛡️ Anti\\-Rug: ✅ Actif\n\n"
            f"📊 *Activité:*\n"
            f"  Tokens analysés: `{self.tokens_analyzed}`\n"
            f"  Alertes envoyées: `{self.alerts_sent}`\n"
            f"  Copy trades: `{self.copy_trades}`\n"
            f"  Twitter signals: `{self.twitter_signals}`\n"
            f"  Positions ouvertes: `{n_pos}`\n\n"
            f"🌍 *Marché:*\n"
            f"  Régime: *{self._esc(regime)}*\n"
            f"  BTC 24h: `{btc:+.1f}%`\n"
        )

        await self._send_reply(msg)

    async def _cmd_stats(self):
        """Commande /stats - Performance"""
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
        """Commande /alertes - Dernières alertes"""
        if not self.alerted_tokens:
            await self._send_reply("📭 Aucune alerte envoyée encore")
            return

        # Trier par timestamp (récentes d'abord)
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
        """Commande /check <mint> - Analyse manuelle"""
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
            # Safety check
            safety = await self.token_safety.full_safety_check(mint)
            summary = self.token_safety.summary(safety)

            # Escaper pour MarkdownV2
            summary_esc = self._esc(summary)

            msg = (
                f"🛡️ *Résultat safety check:*\n"
                f"━━━━━━━━━━━━━━\n"
                f"```\n{summary_esc}\n```"
            )

            await self._send_reply(msg)

        except Exception as e:
            await self._send_reply(f"❌ Erreur: {self._esc(str(e))}")

    async def _cmd_pause(self):
        """Commande /pause - Mettre en pause"""
        self.paused = True
        await self._send_reply(
            "⏸ *Bot mis en pause*\n\n"
            "Les nouveaux tokens ne seront plus analysés\\.\n"
            "Tape /resume pour reprendre\\."
        )
        logger.warning("⏸ Bot mis en pause via Telegram")

    async def _cmd_resume(self):
        """Commande /resume - Reprendre"""
        self.paused = False
        await self._send_reply(
            "▶️ *Bot repris \\!*\n\n"
            "Analyse des nouveaux tokens active\\."
        )
        logger.info("▶️ Bot repris via Telegram")

    async def _cmd_help(self):
        """Commande /help"""
        msg = (
            "🤖 *MemeSniper v12\\.0 \\- Commandes*\n"
            "━━━━━━━━━━━━━━\n\n"
            "📊 *Info:*\n"
            "/status \\- État du bot en direct\n"
            "/stats \\- Statistiques performance\n"
            "/alertes \\- 10 dernières alertes\n\n"
            "🔍 *Analyse:*\n"
            "/check `<mint>` \\- Analyser un token\n"
            "  ex: `/check 7xKXtg2CW\\.\\.\\.`\n\n"
            "⚙️ *Contrôle:*\n"
            "/pause \\- Mettre le bot en pause\n"
            "/resume \\- Reprendre l'analyse\n\n"
            "❓ /help \\- Cette aide\n"
        )
        await self._send_reply(msg)

    async def _send_reply(self, text: str):
        """Envoie un message Telegram simple"""
        await self.alert_sender._send_telegram(text)

    def _esc(self, text: str) -> str:
        """Escape MarkdownV2"""
        special = r'_*[]()~`>#+-=|{}.!'
        return "".join(f"\\{c}" if c in special else c for c in str(text))

    # ═══════════════════════════════════════════════════
    # HANDLERS TOKENS ENTRANTS
    # ═══════════════════════════════════════════════════

    async def handle_new_token_ws(self, token_data: dict):
        """Nouveau token détecté via WebSocket PumpPortal."""

        # v12.0: skip si en pause
        if self.paused:
            return

        address = token_data.get("address", "")

        if not address:
            return

        if address in self.alerted_tokens:
            return

        if address in self.processing_tokens:
            return

        symbol = token_data.get("symbol", "???")

        logger.info(
            f"[WS] 🆕 Nouveau token : "
            f"{symbol} ({address[:8]}...)"
        )

        await asyncio.sleep(10)
        await self._analyze_and_alert(address, source="websocket")

    async def handle_new_token_polling(self, token: dict):
        """Nouveau token détecté via polling DexScreener."""

        # v12.0: skip si en pause
        if self.paused:
            return

        address = (
            token.get("tokenAddress")
            or token.get("address")
            or token.get("baseToken", {}).get("address", "")
        )

        if not address:
            return

        if address in self.alerted_tokens:
            return

        if address in self.processing_tokens:
            return

        await self._analyze_and_alert(address, source="polling")

    # ═══════════════════════════════════════════════════
    # ANALYSE + ALERTE — CŒUR DU BOT
    # ═══════════════════════════════════════════════════

    async def _analyze_and_alert(self, address: str, source: str):
        """
        Analyse un token et envoie une alerte Telegram
        si le score dépasse le seuil requis.
        """

        # ── Vérifications rapides ─────────────────────
        if self.paused:  # v12.0
            return

        if not address or not isinstance(address, str):
            return

        if address in self.alerted_tokens:
            return

        if address in self.processing_tokens:
            logger.debug(
                f"[ANALYZE] Déjà en cours : {address[:8]}"
            )
            return

        # ── Acquisition du verrou ─────────────────────
        self.processing_tokens.add(address)

        try:
            self.tokens_analyzed += 1

            # ── Analyse complète du token ─────────────
            analysis = await self.analyzer.analyze_token(address)

            if not analysis:
                return

            # ── SAFETY CHECK v12.0 ─────────────────────
            safety = await self.token_safety.full_safety_check(address)

            if not safety.get("safe", True):
                reason = safety.get("reasons", ["Unknown"])[0]
                logger.warning(
                    f"🚫 [SAFETY] Bloqué : "
                    f"{address[:8]}... | {reason}"
                )
                return

            analysis["safety"] = safety

            # ── Extraction des métriques ──────────────
            score        = float(analysis.get("score", 0))
            symbol       = analysis.get("symbol", "???")
            smart_count  = int(analysis.get("smart_count", 0))
            has_critical = bool(analysis.get("has_critical", False))
            alpha_count  = int(analysis.get("alpha_wallets", 0))
            whale_count  = int(analysis.get("whale_inflow_count", 0))
            giga_count   = int(analysis.get("giga_whale_count", 0))
            early_signal = analysis.get("early_signal")

            # ── Bonus Twitter ─────────────────────────
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

            # ── Construction des tags pour les logs ───
            critical_tag = " 🚨CRITICAL" if has_critical else ""
            alpha_tag    = f" 🐋x{alpha_count}" if alpha_count else ""
            copy_tag     = (
                " 🚀COPY" if source.startswith("copy_") else ""
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
                f"{critical_tag}{alpha_tag}{copy_tag}"
                f"{twitter_tag}{whale_tag}{early_tag} "
                f"| Safety:{safety.get('score', '?')}/10 "
                f"| src:{source}"
            )

            # ── Seuil dynamique selon la source ───────
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

            # ── Score insuffisant → on ignore ─────────
            if score < min_score:
                logger.debug(
                    f"[SCORE] {symbol} ignoré "
                    f"({score:.1f} < {min_score:.1f} requis "
                    f"| src:{source})"
                )
                return

            # ── Décision (un seul appel) ──────────────
            decision = self.alert_sender.decision_eng.decide(analysis)

            if decision["action"] == "IGNORE":
                logger.info(
                    f"[DECISION] {symbol} ignoré : "
                    f"{decision.get('reason', 'raison inconnue')}"
                )
                return

            # ── Envoi de l'alerte Telegram ────────────
            sent = await self.alert_sender.send_alert(
                analysis,
                decision=decision,
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

                logger.info(
                    f"[ALERT] ✅ {symbol} {score:.1f}/10 "
                    f"→ {decision['action']} | "
                    f"tier:{decision['tier']} | "
                    f"montant:{decision['amount_eur']}€ | "
                    f"src:{source}"
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
        """Purge alerted_tokens par ordre chronologique."""
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
    """Ferme proprement toutes les sessions et sauvegarde les données."""
    logger.info("[CLEANUP] 🛑 Arrêt en cours...")

    # ── 1. Sauvegarde des données ─────────────────────
    try:
        bot.perf_tracker.flush()
        logger.info("[CLEANUP] ✅ Performance tracker sauvegardé")
    except Exception as e:
        logger.error(f"[CLEANUP] perf_tracker.flush() : {e}")

    # ── 2. Arrêt WebSocket ────────────────────────────
    try:
        if hasattr(bot.ws_client, "stop"):
            await bot.ws_client.stop()
            logger.info("[CLEANUP] ✅ WebSocket arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] ws_client.stop() : {e}")

    # ── 3. Arrêt TokenSafety ──────────────────────────
    try:
        if hasattr(bot, "token_safety") and bot.token_safety:
            await bot.token_safety.stop()
            logger.info("[CLEANUP] ✅ TokenSafety arrêté")
    except Exception as e:
        logger.error(f"[CLEANUP] token_safety.stop() : {e}")

    # ── 4. Fermeture session HTTP v12.0 ───────────────
    try:
        if bot.http_session and not bot.http_session.closed:
            await bot.http_session.close()
            logger.info("[CLEANUP] ✅ HTTP session fermée")
    except Exception as e:
        logger.error(f"[CLEANUP] http_session.close() : {e}")

    # ── 5. Fermeture du pump monitor ──────────────────
    try:
        if hasattr(bot.pump_monitor, "close"):
            await bot.pump_monitor.close()
            logger.info("[CLEANUP] ✅ Pump monitor fermé")
    except Exception as e:
        logger.error(f"[CLEANUP] pump_monitor.close() : {e}")

    # ── 6. Fermeture des modules HTTP ─────────────────
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