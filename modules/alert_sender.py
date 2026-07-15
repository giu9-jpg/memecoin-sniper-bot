# modules/alert_sender.py — v5.2
# Alertes Telegram optimisées mobile avec décision d'achat

import os
import aiohttp
from utils.logger import logger
from modules.decision_engine import DecisionEngine


class AlertSender:

    def __init__(self):
        self.bot_token    = None
        self.chat_id      = None
        self.session      = None
        self.decision_eng = DecisionEngine()
        self._load_credentials()

    def _load_credentials(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id   = os.getenv("TELEGRAM_CHAT_ID", "")

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # MESSAGE DE DÉMARRAGE
    # ═══════════════════════════════════════════════════
    async def send_startup_message(self) -> bool:
        """Envoie un message quand le bot démarre."""
        self._load_credentials()
        if not self.bot_token or not self.chat_id:
            logger.error("[ALERT] Credentials Telegram manquants")
            return False

        message = (
            "🤖 *BOT SNIPER MEMECOIN v5.2*\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Bot démarré avec succès\n\n"
            "📡 WebSocket PumpPortal actif\n"
            "🔍 Polling DexScreener actif\n"
            "🧠 Smart Signals activés (8 signaux)\n"
            "🎯 Decision Engine v5.2 (filtres stricts)\n"
            "🐋 Whale Tracker actif\n"
            "📊 Position Tracker actif\n\n"
            "⭐ *Score minimum : 7.5/10*\n"
            "💰 Capital : 100€\n"
            "🎯 Mode : Semi-automatique\n"
            "🚫 Blacklist SOL/USDC/BONK\n\n"
            "⏳ En attente de tokens..."
        )

        try:
            session = await self._get_session()
            url     = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

            payload = {
                "chat_id":                  self.chat_id,
                "text":                     message,
                "parse_mode":               "Markdown",
                "disable_web_page_preview": True,
            }

            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    logger.info("[ALERT] ✅ Message de démarrage envoyé")
                    return True
                else:
                    logger.error(f"[ALERT] ❌ Erreur startup: {resp.status}")
                    return False

        except Exception as e:
            logger.error(f"[ALERT] Exception startup: {e}")
            return False

    # ═══════════════════════════════════════════════════
    # ENVOI PRINCIPAL
    # ═══════════════════════════════════════════════════
    async def send_alert(self, token_data: dict) -> bool:
        """Point d'entrée principal — construit et envoie l'alerte."""

        self._load_credentials()
        if not self.bot_token or not self.chat_id:
            logger.error("[ALERT] Credentials Telegram manquants")
            return False

        # Décision du moteur
        decision = self.decision_eng.decide(token_data)

        if decision["action"] == "IGNORE":
            logger.info(f"[ALERT] Token IGNORÉ: {decision.get('reason','')}")
            return False

        # Construire message et boutons
        message = self._build_message(token_data, decision)
        buttons = self._build_buttons(token_data, decision)

        # Envoyer
        return await self._send_telegram(message, buttons)

    # ═══════════════════════════════════════════════════
    # CONSTRUCTION DU MESSAGE
    # ═══════════════════════════════════════════════════
    def _build_message(self, data: dict, decision: dict) -> str:

        score        = data.get("score", 0)
        name         = data.get("name", "Unknown")
        symbol       = data.get("symbol", "???")
        address      = data.get("address", "")
        market_cap   = data.get("market_cap", 0)
        liquidity    = data.get("liquidity", 0)
        volume_5m    = data.get("volume_5m", 0)
        volume_1h    = data.get("volume_1h", 0)
        price_5m     = data.get("price_change_5m", 0)
        price_1h     = data.get("price_change_1h", 0)
        age_minutes  = data.get("age_minutes", 0)
        holders      = data.get("holders", 0)
        smart_count  = data.get("smart_count", 0)
        has_critical = data.get("has_critical", False)
        smart_signals= data.get("smart_signals", [])

        action      = decision.get("action", "SURVEILLE")
        tier        = decision.get("tier", "WATCH")
        amount_eur  = decision.get("amount_eur", 0)
        profit_pct  = decision.get("expected_profit_pct", 0)
        profit_eur  = decision.get("expected_profit_eur", 0)
        tp_levels   = decision.get("tp_levels", [])
        sl_pct      = decision.get("sl_pct", 0)
        price_usd   = data.get("price_usd", 0)

        action_emoji = {
            "ACHÈTE":    "🟢",
            "SURVEILLE": "🟡",
            "IGNORE":    "🔴",
        }.get(action, "⚪")

        tier_emoji = {
            "ULTIMATE": "💎",
            "STRONG":   "🔥",
            "GOOD":     "✅",
            "NORMAL":   "📊",
            "SMALL":    "🎯",
            "WATCH":    "👀",
        }.get(tier, "⚪")

        lines = []
        lines.append(f"{action_emoji} *{action}* — {tier_emoji} {tier}")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"🪙 *{name}* (${symbol})")
        lines.append(f"📍 `{address[:8]}...{address[-6:]}`")
        lines.append(f"")

        score_bar = self._score_bar(score)
        lines.append(f"⭐ *Score : {score}/10* {score_bar}")
        if smart_count > 0:
            lines.append(f"🧠 Smart Signals : *{smart_count}* détectés")
        if has_critical:
            lines.append(f"🚨 *SIGNAL CRITIQUE ACTIF*")
        lines.append(f"")

        if action == "ACHÈTE" and amount_eur > 0:
            lines.append(f"💰 *MONTANT SUGGÉRÉ : {amount_eur}€*")
            lines.append(f"📈 Profit espéré : *+{profit_pct:.0f}%* ({profit_eur:.1f}€)")
            lines.append(f"")

            if tp_levels and price_usd > 0:
                lines.append(f"🎯 *TAKE PROFITS :*")
                for i, tp in enumerate(tp_levels, 1):
                    tp_mult  = tp.get("multiplier", 1)
                    tp_pct   = tp.get("sell_pct", 0)
                    tp_price = price_usd * tp_mult
                    lines.append(
                        f"   TP{i} : x{tp_mult} → "
                        f"${tp_price:.6f} "
                        f"({tp_pct:.0f}% de ta pos)"
                    )

            if sl_pct and price_usd > 0:
                sl_price = price_usd * (1 + sl_pct / 100)
                lines.append(f"🛑 *STOP LOSS : {sl_pct}%* → ${sl_price:.6f}")
            lines.append(f"")

        lines.append(f"📊 *MÉTRIQUES*")
        lines.append(f"💹 MC : ${market_cap:,.0f}")
        lines.append(f"💧 Liq : ${liquidity:,.0f}")
        lines.append(f"📦 Vol 5m : ${volume_5m:,.0f} | 1h : ${volume_1h:,.0f}")
        lines.append(
            f"📈 Prix : "
            f"{'+' if price_5m >= 0 else ''}{price_5m:.1f}% (5m) | "
            f"{'+' if price_1h >= 0 else ''}{price_1h:.1f}% (1h)"
        )

        age_str = f"{age_minutes:.0f} min" if age_minutes < 60 else f"{age_minutes/60:.1f}h"
        lines.append(f"⏰ Âge : {age_str} | 👥 Holders : {holders}")
        lines.append(f"")

        mint  = "✅" if data.get("mint_renounced") else "🔴"
        lp    = "✅" if data.get("lp_locked") else "⚠️"
        honey = "🔴 HONEYPOT" if data.get("is_honeypot") else "✅ OK"
        top10 = data.get("top_10_holders_pct", 0)
        lines.append(f"🔒 *SÉCURITÉ*")
        lines.append(f"Mint:{mint} LP:{lp} Honey:{honey} Top10:{top10:.0f}%")
        lines.append(f"")

        if smart_signals:
            lines.append(f"🧠 *SMART SIGNALS :*")
            for sig in smart_signals[:4]:
                emoji   = sig.get("emoji", "⚡")
                message = sig.get("message", "")
                lines.append(f"  {emoji} {message}")
            lines.append(f"")

        reasons = data.get("score_reasons", [])
        if reasons:
            lines.append(f"📋 *TOP SIGNAUX :*")
            for r in reasons[:3]:
                lines.append(f"  {r}")

        return "\n".join(lines)

    def _score_bar(self, score: float) -> str:
        filled = int(score)
        empty  = 10 - filled
        return "🟩" * filled + "⬜" * empty

    # ═══════════════════════════════════════════════════
    # BOUTONS TELEGRAM
    # ═══════════════════════════════════════════════════
    def _build_buttons(self, data: dict, decision: dict) -> dict:
        address = data.get("address", "")
        action  = decision.get("action", "SURVEILLE")

        buttons = []

        if action == "ACHÈTE":
            buttons.append([{
                "text": "🚀 ACHETER sur Photon",
                "url":  f"https://photon-sol.tinyastro.io/en/lp/{address}"
            }])

        buttons.append([
            {"text": "📊 DexScreener", "url": f"https://dexscreener.com/solana/{address}"},
            {"text": "🔍 RugCheck",    "url": f"https://rugcheck.xyz/tokens/{address}"},
        ])

        buttons.append([
            {"text": "🦅 Birdeye",       "url": f"https://birdeye.so/token/{address}?chain=solana"},
            {"text": "📈 Birdeye Chart", "url": f"https://birdeye.so/token/{address}?chain=solana&tab=chart"},
        ])

        return {"inline_keyboard": buttons}

    # ═══════════════════════════════════════════════════
    # ENVOI TELEGRAM
    # ═══════════════════════════════════════════════════
    async def _send_telegram(self, message: str, buttons: dict) -> bool:
        try:
            session = await self._get_session()
            url     = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

            payload = {
                "chat_id":                  self.chat_id,
                "text":                     message,
                "parse_mode":               "Markdown",
                "reply_markup":             buttons,
                "disable_web_page_preview": True,
            }

            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                result = await resp.json()

                if resp.status == 200 and result.get("ok"):
                    logger.info("[ALERT] ✅ Message Telegram envoyé")
                    return True
                else:
                    logger.error(f"[ALERT] ❌ Erreur Telegram: {result}")
                    return False

        except Exception as e:
            logger.error(f"[ALERT] Exception: {e}")
            return False

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()