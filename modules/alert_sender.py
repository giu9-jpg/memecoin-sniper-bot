"""
Module d'envoi d'alertes Telegram
Formate les données et envoie sur ton Telegram
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from utils.logger import logger

load_dotenv()


class AlertSender:
    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = (
            f"https://api.telegram.org/bot{self.bot_token}"
        )
        self.alerts_sent = 0
        self.session_start = datetime.utcnow()

        if not self.bot_token:
            logger.error(
                "❌ TELEGRAM_BOT_TOKEN manquant dans .env"
            )
        if not self.chat_id:
            logger.error(
                "❌ TELEGRAM_CHAT_ID manquant dans .env"
            )

    def send_alert(self, data):
        """Envoie une alerte formatée avec toutes les infos"""
        message = self._format_alert(data)
        success = self._send_message(message)
        if success:
            self.alerts_sent += 1
        return success

    def _format_alert(self, data):
        """Formate le message Telegram complet"""
        score = data.get("score", 0)

        # Recommandation
        if score >= 7:
            emoji = "🟢"
            reco = "ACHÈTE"
            montant = f"{min(50, max(10, int(score * 5)))}$"
            urgence = "⚡ ACTION RAPIDE RECOMMANDÉE"
        elif score >= 5:
            emoji = "🟡"
            reco = "SURVEILLE / PETIT MONTANT"
            montant = "10$"
            urgence = "👀 À SURVEILLER"
        else:
            emoji = "🔴"
            reco = "ÉVITE"
            montant = "0$"
            urgence = "⛔ PASSE TON CHEMIN"

        # Sécurité
        honeypot = data.get("honeypot_verdict", "⚠️ N/A")
        liq_lock = "✅" if data.get("liquidity_locked") else "❌"
        mint = "✅" if data.get("mint_renounced") else "❌"
        freeze = "⚠️ OUI" if data.get("freeze_authority") else "✅ NON"

        # Holders concentration
        top10 = data.get("top10_holders_percent", 0)
        if top10 > 50:
            top10_str = f"🔴 {top10:.1f}%"
        elif top10 > 30:
            top10_str = f"🟡 {top10:.1f}%"
        else:
            top10_str = f"🟢 {top10:.1f}%"

        # Ratio achats/ventes
        ratio_5m = data.get("buy_sell_ratio_5m", 0)
        ratio_1h = data.get("buy_sell_ratio_1h", 0)
        if ratio_5m >= 2:
            ratio_str = f"🔥 {ratio_5m}x"
        elif ratio_5m >= 1.5:
            ratio_str = f"📈 {ratio_5m}x"
        else:
            ratio_str = f"📉 {ratio_5m}x"

        # Âge
        age = data.get("age_hours", 0)
        if age <= 1:
            age_str = f"🆕 {age}h (TRÈS EARLY)"
        elif age <= 6:
            age_str = f"⏰ {age}h (Early)"
        else:
            age_str = f"⏰ {age}h"

        # Baleines
        whale_count = data.get("whale_count", 0)
        whale_names = data.get("whale_names", [])
        if whale_count > 0:
            whale_str = (
                f"🐋 {whale_count} baleine(s) : "
                f"{', '.join(whale_names)}"
            )
        else:
            whale_str = "Aucune baleine détectée"

        # Points forts/faibles
        details = data.get("score_details", {})
        positifs = details.get("positifs", [])
        negatifs = details.get("negatifs", [])

        positifs_str = (
            "\n".join([f"   {p}" for p in positifs[:3]])
            if positifs else "   Aucun"
        )
        negatifs_str = (
            "\n".join([f"   {n}" for n in negatifs[:3]])
            if negatifs else "   Aucun"
        )

        # Liens utiles
        dex_url = data.get("url", "")
        contract = data.get("contract", "N/A")
        rugcheck_url = (
            f"https://rugcheck.xyz/tokens/{contract}"
        )
        dexscreener_url = (
            dex_url or
            f"https://dexscreener.com/solana/{contract}"
        )
        birdeye_url = (
            f"https://birdeye.so/token/{contract}"
            f"?chain=solana"
        )

        message = (
            f"{'='*35}\n"
            f"🎯 *${data.get('symbol', '???')}* "
            f"— {data.get('name', 'Inconnu')}\n"
            f"📊 *SCORE : {score}/10 {emoji}*\n"
            f"💡 *{reco}* | {urgence}\n"
            f"{'='*35}\n\n"
            f"📍 *CONTRACT :*\n"
            f"`{contract}`\n\n"
            f"{'─'*30}\n"
            f"💰 *MARCHÉ*\n"
            f"{'─'*30}\n"
            f"💲 Prix     : ${data.get('price_usd', 0):.8f}\n"
            f"💧 Liq.     : ${data.get('liquidity_usd', 0):,.0f}\n"
            f"📊 Vol 24h  : ${data.get('volume_24h', 0):,.0f}\n"
            f"📊 Vol 1h   : ${data.get('volume_1h', 0):,.0f}\n"
            f"🏦 Mkt Cap  : ${data.get('market_cap', 0):,.0f}\n"
            f"⏰ Âge      : {age_str}\n\n"
            f"{'─'*30}\n"
            f"📈 *MOMENTUM*\n"
            f"{'─'*30}\n"
            f"5min  : {data.get('price_change_5m', 0):+.1f}%\n"
            f"1h    : {data.get('price_change_1h', 0):+.1f}%\n"
            f"24h   : {data.get('price_change_24h', 0):+.1f}%\n"
            f"B/S 5m: {ratio_str} "
            f"({data.get('buys_5m', 0)}B/"
            f"{data.get('sells_5m', 0)}S)\n\n"
            f"{'─'*30}\n"
            f"🛡️ *SÉCURITÉ*\n"
            f"{'─'*30}\n"
            f"Honeypot  : {honeypot}\n"
            f"Liq. Lock : {liq_lock}\n"
            f"Mint      : {mint}\n"
            f"Freeze    : {freeze}\n"
            f"Holders   : {top10_str} (top10)\n"
            f"Count     : {data.get('holder_count', '?')}\n\n"
            f"{'─'*30}\n"
            f"✅ *POINTS FORTS*\n"
            f"{positifs_str}\n\n"
            f"❌ *POINTS FAIBLES*\n"
            f"{negatifs_str}\n\n"
            f"{'─'*30}\n"
            f"🐋 *BALEINES*\n"
            f"{whale_str}\n\n"
            f"{'─'*30}\n"
            f"💰 *MONTANT SUGGÉRÉ : {montant}*\n"
            f"{'─'*30}\n\n"
            f"🔗 [DexScreener]({dexscreener_url})\n"
            f"🔗 [RugCheck]({rugcheck_url})\n"
            f"🔗 [Birdeye]({birdeye_url})\n\n"
            f"🕐 {datetime.utcnow().strftime('%H:%M:%S')} UTC\n"
            f"{'='*35}"
        )
        return message

    def _send_message(self, text):
        """Envoie le message via l'API Telegram"""
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False,
            }
            response = requests.post(
                url, json=payload, timeout=10
            )
            if response.status_code == 200:
                logger.info("✅ Alerte Telegram envoyée")
                return True
            else:
                logger.error(
                    f"❌ Telegram erreur "
                    f"{response.status_code} : "
                    f"{response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"❌ Envoi impossible : {e}")
            return False

    def send_simple_message(self, text):
        """Envoie un message simple"""
        self._send_message(text)

    def send_whale_alert(self, whale_data, token_data):
        """Alerte spéciale quand une baleine est détectée"""
        message = (
            f"🚨🐋 *SMART MONEY ALERT* 🐋🚨\n\n"
            f"Une baleine connue vient d'acheter !\n\n"
            f"🐋 Wallet : {whale_data.get('name')}\n"
            f"📈 Win Rate : {whale_data.get('win_rate')}\n"
            f"🎯 Spécialité : {whale_data.get('specialty')}\n\n"
            f"💎 Token : *${token_data.get('symbol')}*\n"
            f"📊 Score : {token_data.get('score')}/10\n"
            f"💧 Liquidité : "
            f"${token_data.get('liquidity_usd', 0):,.0f}\n\n"
            f"⚡ *ANALYSE IMMÉDIATE RECOMMANDÉE*"
        )
        self._send_message(message)

    def send_stats(self):
        """Envoie les statistiques de session"""
        uptime = datetime.utcnow() - self.session_start
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)

        message = (
            f"📊 *STATS SESSION*\n\n"
            f"⏰ Uptime : {hours}h {minutes}min\n"
            f"🔔 Alertes envoyées : {self.alerts_sent}\n"
            f"🔍 Source : DexScreener\n"
            f"✅ Statut : Actif"
        )
        self._send_message(message)

    def send_test(self):
        """Test de connexion Telegram"""
        self._send_message(
            "🤖 *Bot Sniper Memecoin*\n"
            "✅ Connexion Telegram OK !\n\n"
            "📊 Configuration :\n"
            "   🔍 Source : DexScreener\n"
            "   🛡️ Sécurité : RugCheck\n"
            "   🐋 Baleines : Actif\n"
            "   ⏰ Scan : toutes les 30s\n"
            "   🎯 Score min : 5/10\n\n"
            "🚀 *Prêt à chasser les gems !*"
        )