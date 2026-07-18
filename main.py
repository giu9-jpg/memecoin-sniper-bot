# main.py — v11.3 FINAL
# Bot Sniper Memecoin Solana - Ultimate Edition
# + Copy Trading + Early Detector + Whale Inflow
# + 15 Alpha Wallets sélectionnés (Cielo + GMGN)
# + Twitter Tracker (7 comptes Nitter)
# + Performance Tracker v7.1
# + PumpFunMonitor v2.3 + PumpPortalWebSocket v2.1
# + Toutes les corrections appliquées

import asyncio
import gc
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
from modules.twitter_tracker     import TwitterTracker
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

POLLING_INTERVAL     = 30     # secondes entre chaque polling
HEALTH_CHECK_EVERY   = 300    # 5 min
POSITION_CHECK_EVERY = 60     # 1 min
MARKET_CHECK_EVERY   = 180    # 3 min
ALPHA_CHECK_EVERY    = 300    # 5 min
COPY_TRADING_EVERY   = 180    # 3 min
TWITTER_CHECK_EVERY  = 300    # 5 min
STATS_EVERY          = 3600   # 1h
MEMORY_CLEANUP_EVERY = 1800   # 30 min
MIN_SCORE            = 7.5    # Score minimum pour alerter


# ═══════════════════════════════════════════════════════
# BOT PRINCIPAL
# ═══════════════════════════════════════════════════════

class MemeSniper:

    def __init__(self):

        # ── Modules contexte / tracking ───────────────
        self.market_context  = MarketContext()
        self.alpha_tracker   = AlphaTracker()
        self.perf_tracker    = PerformanceTracker()
        self.early_detector  = EarlyDetector()
        self.whale_inflow    = WhaleInflowTracker()
        self.twitter_tracker = TwitterTracker()

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

        # ── État interne ──────────────────────────────
        # dict {address: timestamp} — ordonné et purgeable
        self.alerted_tokens    = {}
        # Verrou pour éviter analyses parallèles du même token
        self.processing_tokens = set()

        self.ws_active        = False
        self.start_time       = time.time()
        self.tokens_analyzed  = 0
        self.alerts_sent      = 0
        self.copy_trades      = 0
        self.twitter_signals  = 0
        self.max_alerted      = 500

    # ═══════════════════════════════════════════════════
    # DÉMARRAGE
    # ═══════════════════════════════════════════════════

    async def run(self):
        """Point d'entrée principal du bot."""

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
        logger.info("🚀 MemeSniper v11.3 démarré !")
        logger.info(f"   Score minimum      : {MIN_SCORE}/10")
        logger.info(f"   Smart Signals      : ACTIVÉS")
        logger.info(f"   Market Context     : ACTIF")
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

        # ── Historique des performances ────────────────
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
            return_exceptions=True,
        )

    # ═══════════════════════════════════════════════════
    # BOUCLES PRINCIPALES
    # ═══════════════════════════════════════════════════

    async def _run_websocket(self):
        """
        Écoute les nouveaux tokens via WebSocket PumpPortal.
        Si le WS tombe, ws_active passe à False.
        Le polling prend le relais automatiquement.
        """
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
        """
        Backup polling toutes les 30s.
        Fonctionne en parallèle du WebSocket.
        """
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
        """
        Scan général des alpha wallets toutes les 5 minutes.
        Populate token_buyers pour get_alpha_signal().
        """
        logger.info(f"[ALPHA] Tracker actif ({ALPHA_CHECK_EVERY}s)")
        await asyncio.sleep(60)   # Laisse le bot se stabiliser
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
        """
        Copy trading : alerte immédiate quand un alpha wallet achète.
        Seuil de score abaissé selon le tier du wallet.
        Vérifie toutes les 3 minutes.
        """
        logger.info(
            f"[COPY] 🐋 Alpha copy-trading actif "
            f"({COPY_TRADING_EVERY}s)"
        )
        await asyncio.sleep(120)   # Délai initial

        while True:
            try:
                # Callback appelé pour chaque nouvel achat détecté
                async def on_alpha_buy(
                    token: str, wallet: str, tier: str
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
        """
        Scan des tweets alpha toutes les 5 minutes.
        Si un CA Solana est détecté dans un tweet → analyse immédiate.
        Premier scan = bootstrap (pas d'alerte sur les vieux tweets).
        """
        logger.info(
            f"[TWITTER] 🐦 Tracker actif ({TWITTER_CHECK_EVERY}s)"
        )
        await asyncio.sleep(180)   # Délai initial

        while True:
            try:
                # Callback appelé pour chaque nouveau signal Twitter
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

                    # Analyse chaque adresse CA détectée
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
        """
        Surveille les gros wallets Solana.
        Si achat détecté → analyse du token immédiate.
        """
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
                        addr, source="whale"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[WHALE] Erreur : {e}")
            await asyncio.sleep(60)

    async def _run_position_tracker(self):
        """
        Vérifie les TP/SL des positions ouvertes toutes les 60s.
        Envoie les alertes Telegram si TP/SL atteint.
        """
        logger.info(
            f"[POSITIONS] Tracker actif ({POSITION_CHECK_EVERY}s)"
        )
        await asyncio.sleep(30)   # Délai initial
        while True:
            try:
                await self.position_tracker.check_all_positions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[POSITIONS] Erreur : {e}")
            await asyncio.sleep(POSITION_CHECK_EVERY)

    async def _run_stats_reporter(self):
        """
        Envoie un rapport de performance Telegram toutes les heures.
        Premier envoi après 1h de fonctionnement.
        """
        logger.info(f"[STATS] Reporter actif (toutes les heures)")
        await asyncio.sleep(STATS_EVERY)   # Attend 1h avant premier rapport
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
        """
        Nettoyage mémoire toutes les 30 minutes.
        - Purge les anciens tokens alertés
        - Nettoie les caches internes de chaque module
        - Force le garbage collector Python
        Premier nettoyage après 10 min.
        """
        logger.info(
            f"[MEMORY] Cleanup actif ({MEMORY_CLEANUP_EVERY}s)"
        )
        await asyncio.sleep(600)   # Premier cleanup après 10 min
        while True:
            try:
                # ── Nettoyage des modules ──────────────
                self.alpha_tracker.cleanup_old_data()
                self.early_detector.cleanup_old()
                self.whale_inflow.cleanup_cache()
                self.twitter_tracker.cleanup_old_data()

                # ── Purge alerted_tokens ───────────────
                self._trim_alerted_tokens()

                # ── GC Python ─────────────────────────
                collected = gc.collect()

                # ── Rapport mémoire ───────────────────
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
        """
        Log de santé du bot toutes les 5 minutes.
        Affiche l'état de tous les composants.
        """
        logger.info(
            f"[HEALTH] Health check actif ({HEALTH_CHECK_EVERY}s)"
        )
        await asyncio.sleep(60)   # Premier check après 1 min
        while True:
            try:
                uptime = int((time.time() - self.start_time) / 60)
                ws_status = "✅" if self.ws_active else "❌"

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
                    f"Uptime:{uptime}min | "
                    f"WS:{ws_status} | "
                    f"Analysés:{self.tokens_analyzed} | "
                    f"Alertes:{self.alerts_sent} | "
                    f"Copy:{self.copy_trades} | "
                    f"Twitter:{self.twitter_signals} | "
                    f"Positions:{n_pos} | "
                    f"Marché:{regime}"
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[HEALTH] Erreur : {e}")

            await asyncio.sleep(HEALTH_CHECK_EVERY)

    # ═══════════════════════════════════════════════════
    # HANDLERS TOKENS ENTRANTS
    # ═══════════════════════════════════════════════════

    async def handle_new_token_ws(self, token_data: dict):
        """
        Nouveau token détecté via WebSocket PumpPortal.
        Attente de 10s pour laisser la liquidité s'installer
        avant d'analyser.
        """
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

        # Attente pour laisser les données se propager sur DexScreener
        await asyncio.sleep(10)
        await self._analyze_and_alert(address, source="websocket")

    async def handle_new_token_polling(self, token: dict):
        """
        Nouveau token détecté via polling DexScreener.
        Pas de délai car les données sont déjà disponibles.
        """
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

        Corrections v11.3 :
        ─────────────────────────────────────────────
        1. Verrou processing_tokens → pas d'analyses parallèles
        2. alerted_tokens dict → purge chronologique propre
        3. Un seul appel decide() → cohérence garantie
        4. min_score dynamique selon la source (twitter/copy/normal)
        5. Bonus Twitter appliqué avant le seuil
        6. Finally → verrou toujours libéré même en cas d'erreur
        """

        # ── Vérifications rapides ─────────────────────
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
            # Cherche d'abord par adresse, puis par symbole
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
                twitter_bonus           = float(
                    twitter_signal.get("bonus", 0)
                )
                score                   = min(10.0, score + twitter_bonus)
                analysis["score"]           = score
                analysis["twitter_signal"]  = twitter_signal

            # ── Construction des tags pour les logs ───
            critical_tag = " 🚨CRITICAL" if has_critical else ""
            alpha_tag    = f" 🐋x{alpha_count}" if alpha_count else ""
            copy_tag     = (
                " 🚀COPY" if source.startswith("copy_") else ""
            )

            twitter_tag = ""
            if source.startswith("twitter_"):
                tier_part   = source.split("_", 1)[-1]
                twitter_tag = f" 🐦{tier_part}"
            elif twitter_signal:
                uname       = twitter_signal.get("username", "")[:10]
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
                f"| src:{source}"
            )

            # ── Seuil dynamique selon la source ───────
            min_score = MIN_SCORE

            if source.startswith("twitter_"):
                # Seuil abaissé selon le tier Twitter
                if "TIER1" in source:
                    min_score = 6.0
                elif "TIER2" in source:
                    min_score = 6.5
                elif "TIER3" in source:
                    min_score = 7.0

            elif source.startswith("copy_"):
                # Seuil selon le tier du wallet alpha
                copy_wallets = analysis.get("alpha_wallet_list", [])
                if copy_wallets:
                    thresholds = [
                        get_copy_threshold(w)
                        for w in copy_wallets
                    ]
                    min_score = min(thresholds)
                else:
                    # Fallback par tier dans le nom de la source
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
            # On passe decision pour éviter un second appel decide()
            sent = await self.alert_sender.send_alert(
                analysis,
                decision=decision,
            )

            if sent:
                # Marque le token comme alerté
                self.alerted_tokens[address] = time.time()
                self.alerts_sent += 1

                # Purge si trop d'entrées
                self._trim_alerted_tokens()

                # Enregistrement dans l'historique de performance
                self.perf_tracker.record_alert(analysis, decision)

                # Ouverture de position si action = ACHÈTE
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
            # Ne pas swallow CancelledError
            raise

        except Exception as e:
            logger.error(
                f"[ANALYZE] Erreur {address[:8]}: {e}",
                exc_info=True,
            )

        finally:
            # Toujours libérer le verrou
            self.processing_tokens.discard(address)

    # ═══════════════════════════════════════════════════
    # HELPERS INTERNES
    # ═══════════════════════════════════════════════════

    def _trim_alerted_tokens(self):
        """
        Purge alerted_tokens par ordre chronologique.
        Garde uniquement les max_alerted tokens les plus récents.
        """
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
    """
    Ferme proprement toutes les sessions et sauvegarde les données.

    Ordre important :
    1. flush() perf_tracker EN PREMIER (sauvegarde les données)
    2. stop() WebSocket
    3. close() tous les modules avec session HTTP
    """
    logger.info("[CLEANUP] 🛑 Arrêt en cours...")

    # ── 1. Sauvegarde des données (EN PREMIER) ────────
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

    # ── 3. Fermeture du pump monitor ──────────────────
    try:
        if hasattr(bot.pump_monitor, "close"):
            await bot.pump_monitor.close()
            logger.info("[CLEANUP] ✅ Pump monitor fermé")
    except Exception as e:
        logger.error(f"[CLEANUP] pump_monitor.close() : {e}")

    # ── 4. Fermeture des modules HTTP ─────────────────
    modules_to_close = [
        ("analyzer",       bot.analyzer),
        ("alert_sender",   bot.alert_sender),
        ("position_tracker", bot.position_tracker),
        ("market_context", bot.market_context),
        ("alpha_tracker",  bot.alpha_tracker),
        ("early_detector", bot.early_detector),
        ("whale_inflow",   bot.whale_inflow),
        ("twitter_tracker", bot.twitter_tracker),
        ("whale_tracker",  bot.whale_tracker),
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