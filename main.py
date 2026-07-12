"""
🤖 MEMECOIN SNIPER BOT v2.1
Améliorations :
- Score minimum abaissé à 5
- Whale tracker avec vrais wallets
- Alertes spéciales baleines
- Stats toutes les heures
- ⚠️ FILTRE STRICT SOLANA (rejette EVM)
- Meilleure gestion des erreurs
"""

import time
import schedule
from datetime import datetime
from utils.logger import logger
from modules.token_analyzer import TokenAnalyzer
from modules.pump_fun_monitor import PumpFunMonitor
from modules.whale_tracker import WhaleTracker
from modules.alert_sender import AlertSender
from config.settings import (
    SCAN_INTERVAL_SECONDS,
    MIN_LIQUIDITY,
    SCORE_MIN_ALERT,
    SCORE_BUY,
)


class MemeSniper:
    def __init__(self):
        logger.info("🚀 Démarrage du Bot v2.1...")

        self.analyzer = TokenAnalyzer()
        self.pumpfun = PumpFunMonitor()
        self.whales = WhaleTracker()
        self.alerter = AlertSender()

        self.analyzed_tokens = set()
        self.scan_count = 0
        self.alert_count = 0
        self.rejected_evm = 0
        self.start_time = datetime.utcnow()

        logger.info("✅ Bot v2.1 prêt !")
        self.alerter.send_simple_message(
            f"🤖 *Bot Sniper v2.1 actif !*\n\n"
            f"📊 Config :\n"
            f"   🎯 Score min alerte : {SCORE_MIN_ALERT}/10\n"
            f"   💧 Liquidité min : ${MIN_LIQUIDITY:,}\n"
            f"   ⏰ Scan : toutes les {SCAN_INTERVAL_SECONDS}s\n"
            f"   🐋 Wallets surveillés : "
            f"{len(self.whales.known_whales)}\n"
            f"   🔒 Filtre STRICT : Solana uniquement\n\n"
            f"🚀 *Chasse aux gems lancée !*"
        )

    def run_scan_cycle(self):
        """Exécute un cycle complet de scan"""
        self.scan_count += 1
        logger.info(
            f"🔍 Scan #{self.scan_count} en cours..."
        )

        try:
            self._scan_new_tokens()
        except Exception as e:
            logger.error(f"❌ Erreur scan : {e}")

        logger.info(f"✅ Scan #{self.scan_count} terminé")

    def _scan_new_tokens(self):
        """Scanne les nouveaux tokens Solana"""
        tokens = self.pumpfun.get_trending_tokens()

        if not tokens:
            logger.info("Aucun nouveau token ce cycle")
            return

        # Filtre les tokens déjà analysés
        new_tokens = [
            t for t in tokens
            if t.get("contract") not in self.analyzed_tokens
        ]

        logger.info(
            f"📊 {len(new_tokens)} nouveaux tokens à analyser"
        )

        # Analyse les 15 premiers
        for token in new_tokens[:15]:
            contract = token.get("contract", "")
            symbol = token.get("symbol", "???")

            if not contract:
                continue

            self._full_analysis(contract, symbol)
            time.sleep(1)  # Rate limiting

    def _full_analysis(self, contract, symbol):
        """Analyse complète d'un token"""
        self.analyzed_tokens.add(contract)

        # ==========================================
        # ⚠️ SÉCURITÉ CRITIQUE : FILTRE SOLANA
        # ==========================================
        
        # Rejette les adresses Ethereum/Polygon/Base (EVM)
        if contract.startswith("0x"):
            self.rejected_evm += 1
            logger.warning(
                f"⛔ ${symbol} adresse EVM (non Solana) "
                f"→ Ignoré : {contract[:20]}..."
            )
            return
        
        # Rejette les formats invalides
        if len(contract) < 32 or len(contract) > 44:
            logger.warning(
                f"⛔ ${symbol} format contract invalide "
                f"→ Ignoré : {contract[:20]}..."
            )
            return

        # ==========================================
        # NETTOYAGE MÉMOIRE
        # ==========================================
        if len(self.analyzed_tokens) > 5000:
            self.analyzed_tokens = set(
                list(self.analyzed_tokens)[-2000:]
            )

        logger.info(
            f"📊 Analyse ${symbol} ({contract[:8]}...)"
        )

        # ==========================================
        # 1. ANALYSE MARCHÉ + SÉCURITÉ
        # ==========================================
        token_data = self.analyzer.analyze_token(contract)
        if not token_data:
            logger.info(f"❌ ${symbol} pas de données")
            return

        # ==========================================
        # 2. FILTRE HONEYPOT
        # ==========================================
        if token_data.get("is_honeypot") is True:
            logger.warning(
                f"⛔ ${symbol} HONEYPOT → Ignoré"
            )
            return

        # ==========================================
        # 3. FILTRE LIQUIDITÉ MINIMUM
        # ==========================================
        liquidity = token_data.get("liquidity_usd", 0)
        if liquidity < MIN_LIQUIDITY:
            logger.info(
                f"⚠️ ${symbol} liq. faible "
                f"(${liquidity:,.0f}) → Ignoré"
            )
            return

        # ==========================================
        # 4. FILTRE ÂGE (rejette les tokens > 30 jours)
        # ==========================================
        age_hours = token_data.get("age_hours", 0)
        if age_hours > 720:  # 30 jours
            logger.info(
                f"⚠️ ${symbol} trop ancien "
                f"({age_hours:.0f}h) → Ignoré"
            )
            return

        # ==========================================
        # 5. FILTRE ACTIVITÉ (rejette les tokens morts)
        # ==========================================
        volume_1h = token_data.get("volume_1h", 0)
        if volume_1h < 100:  # Moins de 100$ sur 1h = mort
            logger.info(
                f"⚠️ ${symbol} token inactif "
                f"(vol 1h : ${volume_1h:.0f}) → Ignoré"
            )
            return

        # ==========================================
        # 6. VÉRIFIE LES BALEINES
        # ==========================================
        whale_data = self.whales.check_whale_activity(contract)

        # ==========================================
        # 7. BONUS BALEINE SUR LE SCORE
        # ==========================================
        score = token_data.get("score", 0)
        if whale_data.get("is_smart_money_signal"):
            bonus = whale_data.get("score_bonus", 0)
            score = min(10, score + bonus)
            token_data["score"] = round(score, 1)
            logger.info(
                f"🐋 Bonus baleine +{bonus} → "
                f"Score: {score}/10"
            )

        # ==========================================
        # 8. COMPILE TOUTES LES DONNÉES
        # ==========================================
        full_data = {
            **token_data,
            "contract": contract,
            "source": "DexScreener",
            "whale_count": whale_data.get("whale_count", 0),
            "whale_names": whale_data.get("whale_names", []),
            "mention_count": 0,
        }

        logger.info(
            f"📈 ${symbol} — Score : {score}/10"
        )

        # ==========================================
        # 9. ALERTE SPÉCIALE BALEINE
        # ==========================================
        if whale_data.get("is_smart_money_signal"):
            logger.info(
                f"🐋 SMART MONEY sur ${symbol} !"
            )
            if whale_data.get("whales"):
                self.alerter.send_whale_alert(
                    whale_data["whales"][0],
                    full_data
                )

        # ==========================================
        # 10. ALERTE PRINCIPALE
        # ==========================================
        if score >= SCORE_MIN_ALERT:
            self.alert_count += 1
            logger.info(
                f"🚨 ALERTE #{self.alert_count} : "
                f"${symbol} ({score}/10)"
            )
            self.alerter.send_alert(full_data)
        else:
            logger.info(
                f"❌ ${symbol} score {score}/10 "
                f"< {SCORE_MIN_ALERT} → Ignoré"
            )

    def send_hourly_stats(self):
        """Envoie les stats toutes les heures"""
        uptime = datetime.utcnow() - self.start_time
        hours = int(uptime.total_seconds() // 3600)
        minutes = int(
            (uptime.total_seconds() % 3600) // 60
        )

        self.alerter.send_simple_message(
            f"📊 *RAPPORT HORAIRE*\n\n"
            f"⏰ Uptime : {hours}h {minutes}min\n"
            f"🔍 Scans : {self.scan_count}\n"
            f"🔔 Alertes : {self.alert_count}\n"
            f"⛔ EVM rejetés : {self.rejected_evm}\n"
            f"📋 Tokens analysés : "
            f"{len(self.analyzed_tokens)}\n"
            f"🟢 Bot en bonne santé"
        )

    def start(self):
        """Démarre le bot en boucle continue"""
        logger.info("🤖 BOT v2.1 ACTIF")
        logger.info(
            f"⏰ Scan toutes les {SCAN_INTERVAL_SECONDS}s"
        )
        logger.info(
            f"🎯 Score minimum pour alerter : "
            f"{SCORE_MIN_ALERT}/10"
        )
        logger.info(
            f"🔒 Filtre STRICT : Solana uniquement"
        )

        # Premier scan immédiat
        self.run_scan_cycle()

        # Scans réguliers
        schedule.every(SCAN_INTERVAL_SECONDS).seconds.do(
            self.run_scan_cycle
        )

        # Stats toutes les heures
        schedule.every(1).hours.do(self.send_hourly_stats)

        # Boucle infinie
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("⛔ Bot arrêté manuellement")
            uptime = datetime.utcnow() - self.start_time
            self.alerter.send_simple_message(
                f"⛔ *Bot arrêté*\n\n"
                f"📊 Session :\n"
                f"   🔍 Scans : {self.scan_count}\n"
                f"   🔔 Alertes : {self.alert_count}\n"
                f"   ⛔ EVM rejetés : {self.rejected_evm}\n"
                f"   📋 Tokens : "
                f"{len(self.analyzed_tokens)}"
            )


# === POINT D'ENTRÉE ===
if __name__ == "__main__":
    bot = MemeSniper()
    bot.start()