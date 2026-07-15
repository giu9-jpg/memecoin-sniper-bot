# modules/alert_sender.py — v6.0 ULTRA SIMPLE
# Alertes Telegram claires : décision en 3 secondes

import os
import aiohttp
from utils.logger import logger
from modules.decision_engine import DecisionEngine


class AlertSender:

    def __init__(self, market_context=None):
        self.bot_token      = None
        self.chat_id        = None
        self.session        = None
        self.market_context = market_context
        self.decision_eng   = DecisionEngine(market_context=market_context)
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
        self._load_credentials()
        if not self.bot_token or not self.chat_id:
            logger.error("[ALERT] Credentials Telegram manquants")
            return False

        message = (
            "🤖 *BOT v6.0 démarré*\n"
            "━━━━━━━━━━━━━━\n"
            "✅ Prêt à sniper\n"
            "⭐ Score min : 7.5/10\n"
            "💰 Capital : 100€\n"
            "🌍 Filtre macro : ON\n"
            "🐋 Alpha wallets : ON\n\n"
            "⏳ En attente..."
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
                return False
        except Exception as e:
            logger.error(f"[ALERT] Exception startup: {e}")
            return False

    # ═══════════════════════════════════════════════════
    # ENVOI PRINCIPAL
    # ═══════════════════════════════════════════════════
    async def send_alert(self, token_data: dict) -> bool:
        self._load_credentials()
        if not self.bot_token or not self.chat_id:
            return False

        decision = self.decision_eng.decide(token_data)

        if decision["action"] == "IGNORE":
            logger.info(f"[ALERT] Token IGNORÉ: {decision.get('reason','')}")
            return False

        message = self._build_message(token_data, decision)
        buttons = self._build_buttons(token_data, decision)

        return await self._send_telegram(message, buttons)

    # ═══════════════════════════════════════════════════
    # MESSAGE ULTRA SIMPLE
    # ═══════════════════════════════════════════════════
    def _build_message(self, data: dict, decision: dict) -> str:

        # ── Données ───────────────────────────────────
        score       = data.get("score", 0)
        name        = data.get("name", "Unknown")
        symbol      = data.get("symbol", "???")
        market_cap  = data.get("market_cap", 0)
        liquidity   = data.get("liquidity", 0)
        volume_1h   = data.get("volume_1h", 0)
        price_1h    = data.get("price_change_1h", 0)
        age_minutes = data.get("age_minutes", 0)
        holders     = data.get("holders", 0)
        vol_accel   = data.get("vol_acceleration", 1)
        smart_count = data.get("smart_count", 0)
        has_critical= data.get("has_critical", False)
        alpha_count = data.get("alpha_wallets", 0)
        price_usd   = data.get("price_usd", 0)

        tier        = decision.get("tier", "NORMAL")
        amount_eur  = decision.get("amount_eur", 0)
        profit_pct  = decision.get("expected_profit_pct", 0)
        tp_levels   = decision.get("tp_levels", [])
        sl_pct      = decision.get("sl_pct", 0)

        # ── Sécurité ──────────────────────────────────
        is_safe = (
            not data.get("is_honeypot")
            and not data.get("freeze_auth")
            and data.get("top_10_holders_pct", 0) < 50
        )
        safety_emoji = "✅ OK" if is_safe else "⚠️ ATTENTION"

        # ── Titre selon tier ──────────────────────────
        title = self._get_title(tier, has_critical, alpha_count)

        # ═══════════════════════════════════════════════
        # CONSTRUCTION DU MESSAGE
        # ═══════════════════════════════════════════════
        lines = []

        # 1. TITRE en gros
        lines.append(title)
        lines.append(f"━━━━━━━━━━━━━━")
        lines.append(f"🪙 *{name}* (${symbol})")
        lines.append(f"")

        # 2. SCORE + MONTANT (l'essentiel)
        lines.append(f"⭐ *{score}/10*  |  💰 *{amount_eur}€*")
        lines.append(f"🎯 Profit espéré : *+{profit_pct:.0f}%*")
        lines.append(f"")

        # 3. VENDRE À (la stratégie de sortie)
        lines.append(f"━━━━━━━━━━━━━━")
        lines.append(f"🎯 *VENDRE À :*")
        if tp_levels:
            for i, tp in enumerate(tp_levels, 1):
                mult = tp.get("multiplier", 1)
                pct  = tp.get("sell_pct", 0)
                note = ""
                if i == 1:
                    note = " *(récupère ta mise)*"
                lines.append(f"  x{mult}  →  {pct:.0f}%{note}")
        lines.append(f"🛑 *STOP :* {sl_pct}%")
        lines.append(f"━━━━━━━━━━━━━━")
        lines.append(f"")

        # 4. EN BREF (métriques essentielles)
        lines.append(f"📊 *En bref :*")

        # Liquidité + MC
        liq_str = self._fmt_number(liquidity)
        mc_str  = self._fmt_number(market_cap)
        lines.append(f"  💧 Liq: ${liq_str}  |  MC: ${mc_str}")

        # Âge + Holders
        age_str = f"{age_minutes:.0f}min" if age_minutes < 60 else f"{age_minutes/60:.1f}h"
        lines.append(f"  ⏰ {age_str}  |  👥 {holders} holders")

        # Volume + Prix
        vol_emoji = "🚀" if vol_accel >= 2 else "📊"
        lines.append(
            f"  {vol_emoji} Vol x{vol_accel:.1f}  |  "
            f"Prix {'+' if price_1h >= 0 else ''}{price_1h:.0f}% (1h)"
        )

        # Alpha wallets (si présent)
        if alpha_count > 0:
            lines.append(f"  🐋 *{alpha_count} alpha wallet(s) détecté(s)*")

        # Smart signals critiques
        if has_critical:
            lines.append(f"  🚨 *SIGNAL CRITIQUE*")
        elif smart_count >= 3:
            lines.append(f"  🧠 {smart_count} smart signals")

        # Contexte marché
        if self.market_context:
            sig = self.market_context.get_market_signal()
            regime = sig["regime"]
            btc    = sig["btc_change_24h"]
            emoji  = {"BULLISH": "🚀", "NEUTRAL": "😐", "BEARISH": "🔴"}.get(regime, "⚪")
            lines.append(
                f"  🌍 Marché {emoji} *{regime}* "
                f"(BTC {btc:+.0f}%)"
            )

        lines.append(f"")

        # 5. SÉCURITÉ
        lines.append(f"🔒 Sécurité : *{safety_emoji}*")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════
    # TITRE SELON QUALITÉ
    # ═══════════════════════════════════════════════════
    def _get_title(self, tier: str, has_critical: bool, alpha_count: int) -> str:
        """Titre gros et clair selon la qualité de l'opportunité."""

        # Cas spéciaux (priorité)
        if alpha_count >= 3:
            return "🚨🚨🚨 *ALPHA WALLETS ACHÈTENT !*"
        if alpha_count >= 2:
            return "🐋🐋 *2 BALEINES DÉTECTÉES*"
        if tier == "ULTIMATE":
            return "💎💎💎 *ULTIMATE — ACHÈTE MAX !*"
        if has_critical:
            return "🚨 *SIGNAL CRITIQUE — ACHÈTE*"

        # Tiers normaux
        titles = {
            "STRONG": "🔥🔥 *ACHÈTE — Opportunité forte*",
            "GOOD":   "🟢🟢 *ACHÈTE — Bonne opportunité*",
            "NORMAL": "🟢 *ACHÈTE — Opportunité correcte*",
        }
        return titles.get(tier, "⚪ *À examiner*")

    # ═══════════════════════════════════════════════════
    # FORMAT DES NOMBRES (85000 → "85K")
    # ═══════════════════════════════════════════════════
    def _fmt_number(self, num: float) -> str:
        if num >= 1_000_000:
            return f"{num/1_000_000:.1f}M"
        elif num >= 1_000:
            return f"{num/1_000:.0f}K"
        return f"{num:.0f}"

    # ═══════════════════════════════════════════════════
    # BOUTONS TELEGRAM
    # ═══════════════════════════════════════════════════
    def _build_buttons(self, data: dict, decision: dict) -> dict:
        address = data.get("address", "")

        return {
            "inline_keyboard": [
                # Bouton principal : ACHETER
                [{
                    "text": "🚀 ACHETER SUR PHOTON",
                    "url":  f"https://photon-sol.tinyastro.io/en/lp/{address}"
                }],
                # Analyse rapide
                [
                    {"text": "📊 Chart",   "url": f"https://dexscreener.com/solana/{address}"},
                    {"text": "🔍 Safety", "url": f"https://rugcheck.xyz/tokens/{address}"},
                ],
            ]
        }

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