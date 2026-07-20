# modules/alert_sender.py — v7.0 v12.7
# ═══════════════════════════════════════════════
# v7.0 CHANGEMENTS :
# + Support envoi de PHOTOS (charts DexScreener)
# + Méthode _send_telegram_photo() ajoutée
# + Fallback automatique texte si photo échoue
# + Nouveau paramètre `chart_url` dans send_alert()
#
# HÉRITÉ v6.3 :
# + Score sécurité affiché (avec emoji dynamique)
# + Warnings sécurité affichés (top 3)
# + Bouton Jupiter, Solscan, Twitter Search

import os
import asyncio
import aiohttp
from utils.logger import logger
from modules.decision_engine import DecisionEngine


class AlertSender:

    def __init__(self, market_context=None):
        self.bot_token      = None
        self.chat_id        = None
        self.session        = None
        self.market_context = market_context
        self.decision_eng   = DecisionEngine(
            market_context=market_context
        )
        self._load_credentials()

    def _load_credentials(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id   = os.getenv("TELEGRAM_CHAT_ID", "")

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # STARTUP
    # ═══════════════════════════════════════════════════

    async def send_startup_message(self) -> bool:
        self._load_credentials()
        if not self.bot_token or not self.chat_id:
            logger.error("[ALERT] Credentials Telegram manquants")
            return False

        message = (
            "🤖 *BOT v12\\.7 démarré*\n"
            "━━━━━━━━━━━━━━\n"
            "✅ Prêt à sniper\n"
            "⭐ Score min : 7\\.5/10\n"
            "🛡️ Anti\\-Rug : ON\n"
            "💰 Capital : 100€\n"
            "🌍 Filtre macro : ON\n"
            "🐋 Alpha wallets : ON \\(15\\)\n"
            "🐦 Twitter : ON \\(7 comptes\\)\n"
            "📊 Performance : ON\n"
            "🎯 Bull Analyzer : ON\n"
            "💰 Sell Signals : ON\n"
            "📸 Charts photos : ON\n\n"
            "⏳ En attente\\.\\.\\."
        )
        return await self._send_telegram(message, buttons=None)

    # ═══════════════════════════════════════════════════
    # ENVOI PRINCIPAL v7.0
    # + support chart_url pour envoi photo
    # ═══════════════════════════════════════════════════

    async def send_alert(
        self,
        token_data: dict,
        decision:   dict | None = None,
        chart_url:  str  | None = None,
    ) -> bool:
        """
        Envoie une alerte Telegram.

        Args:
          token_data : données du token
          decision   : décision (optionnel, sinon recalculée)
          chart_url  : URL image du chart (optionnel)
                       Si fournie → envoi en PHOTO au lieu de texte
        """
        self._load_credentials()
        if not self.bot_token or not self.chat_id:
            return False

        if decision is None:
            decision = self.decision_eng.decide(token_data)

        if decision["action"] == "IGNORE":
            logger.info(
                f"[ALERT] Token IGNORÉ: {decision.get('reason', '')}"
            )
            return False

        message = self._build_message(token_data, decision)
        buttons = self._build_buttons(token_data, decision)

        # v7.0 : Si chart_url fourni, envoi en PHOTO
        if chart_url:
            return await self._send_telegram_photo(
                photo_url=chart_url,
                caption=message,
                buttons=buttons,
            )

        # Sinon envoi texte normal
        return await self._send_telegram(message, buttons)

    # ═══════════════════════════════════════════════════
    # CONSTRUCTION DU MESSAGE
    # ═══════════════════════════════════════════════════

    def _build_message(self, data: dict, decision: dict) -> str:

        score        = data.get("score", 0)
        name         = data.get("name", "Unknown")
        symbol       = data.get("symbol", "???")
        market_cap   = data.get("market_cap", 0)
        liquidity    = data.get("liquidity", 0)
        price_1h     = data.get("price_change_1h", 0)
        age_minutes  = data.get("age_minutes", 0)
        holders      = data.get("holders", 0)
        vol_accel    = data.get("vol_acceleration", 1)
        smart_count  = data.get("smart_count", 0)
        has_critical = data.get("has_critical", False)
        alpha_count  = data.get("alpha_wallets", 0)

        tier       = decision.get("tier", "NORMAL")
        amount_eur = decision.get("amount_eur", 0)
        profit_pct = decision.get("expected_profit_pct", 0)
        tp_levels  = decision.get("tp_levels", [])
        sl_pct     = decision.get("sl_pct", 0)

        # ── Sécurité v12.0 ────────────────────────────
        safety_data = data.get("safety", {})

        if safety_data:
            safety_score    = safety_data.get("score", 10)
            safety_warnings = safety_data.get("warnings", [])

            if safety_score >= 8:
                safety_emoji = "🛡️ EXCELLENT"
            elif safety_score >= 6:
                safety_emoji = "✅ OK"
            elif safety_score >= 4:
                safety_emoji = "⚠️ ATTENTION"
            else:
                safety_emoji = "🚨 RISQUÉ"
        else:
            safety_score    = 10
            safety_warnings = []
            is_safe = (
                not data.get("is_honeypot")
                and not data.get("freeze_auth")
                and data.get("top_10_holders_pct", 0) < 50
            )
            safety_emoji = "✅ OK" if is_safe else "⚠️ ATTENTION"

        title = self._get_title(tier, has_critical, alpha_count)

        if age_minutes < 60:
            age_str = f"{age_minutes:.0f}min"
        elif age_minutes < 1440:
            age_str = f"{age_minutes/60:.1f}h"
        else:
            age_str = f"{age_minutes/1440:.1f}j"

        name_safe   = self._escape_md(name)
        symbol_safe = self._escape_md(symbol)

        lines = []

        # 1. Titre
        lines.append(title)
        lines.append("━━━━━━━━━━━━━━")
        lines.append(f"🪙 *{name_safe}* \\(${symbol_safe}\\)")
        lines.append("")

        # 2. Score + Sécurité + montant
        lines.append(f"⭐ Score: *{score}/10*  |  💰 *{amount_eur}€*")
        lines.append(
            f"🛡️ Sécurité: *{safety_score}/10*  {safety_emoji}"
        )
        lines.append(f"🎯 Profit espéré : *\\+{profit_pct:.0f}%*")

        if safety_warnings:
            lines.append("")
            lines.append("⚠️ *Points d'attention:*")
            for warning in safety_warnings[:3]:
                warning_safe = self._escape_md(str(warning))
                lines.append(f"  • {warning_safe}")

        lines.append("")

        # 3. Stratégie de sortie
        lines.append("━━━━━━━━━━━━━━")
        lines.append("🎯 *VENDRE À :*")
        if tp_levels:
            for i, tp in enumerate(tp_levels, 1):
                mult     = tp.get("multiplier", 1)
                pct      = tp.get("sell_pct", 0)
                note     = " _\\(récupère ta mise\\)_" if i == 1 else ""
                lines.append(f"  x{mult}  →  {pct:.0f}%{note}")
        lines.append(f"🛑 *STOP :* {sl_pct}%")
        lines.append("━━━━━━━━━━━━━━")
        lines.append("")

        # 4. Métriques essentielles
        lines.append("📊 *En bref :*")

        liq_str = self._fmt_number(liquidity)
        mc_str  = self._fmt_number(market_cap)
        lines.append(f"  💧 Liq: ${liq_str}  |  MC: ${mc_str}")
        lines.append(f"  ⏰ {age_str}  |  👥 {holders} holders")

        vol_emoji  = "🚀" if vol_accel >= 2 else "📊"
        price_sign = "\\+" if price_1h >= 0 else ""
        lines.append(
            f"  {vol_emoji} Vol x{vol_accel:.1f}  |  "
            f"Prix {price_sign}{price_1h:.0f}% \\(1h\\)"
        )

        if alpha_count > 0:
            lines.append(
                f"  🐋 *{alpha_count} alpha wallet\\(s\\) détecté\\(s\\)*"
            )

        tw = data.get("twitter_signal")
        if tw:
            tw_user = self._escape_md(tw.get("username", ""))
            tw_tier = self._escape_md(tw.get("best_tier", ""))
            lines.append(f"  🐦 *@{tw_user}* \\({tw_tier}\\)")

        if has_critical:
            lines.append("  🚨 *SIGNAL CRITIQUE*")
        elif smart_count >= 3:
            lines.append(f"  🧠 {smart_count} smart signals")

        if self.market_context:
            try:
                sig    = self.market_context.get_market_signal()
                regime = self._escape_md(sig["regime"])
                btc    = sig["btc_change_24h"]
                emoji  = {
                    "BULLISH": "🚀",
                    "NEUTRAL": "😐",
                    "BEARISH": "🔴",
                }.get(sig["regime"], "⚪")
                btc_sign = "\\+" if btc >= 0 else ""
                lines.append(
                    f"  🌍 Marché {emoji} *{regime}* "
                    f"\\(BTC {btc_sign}{btc:.0f}%\\)"
                )
            except Exception:
                pass

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════
    # TITRE SELON TIER
    # ═══════════════════════════════════════════════════

    def _get_title(
        self, tier: str, has_critical: bool, alpha_count: int
    ) -> str:
        if alpha_count >= 3:
            return "🚨🚨🚨 *ALPHA WALLETS ACHÈTENT \\!*"
        if alpha_count >= 2:
            return "🐋🐋 *2 BALEINES DÉTECTÉES*"
        if tier == "ULTIMATE":
            return "💎💎💎 *ULTIMATE — ACHÈTE MAX \\!*"
        if has_critical:
            return "🚨 *SIGNAL CRITIQUE — ACHÈTE*"
        titles = {
            "STRONG": "🔥🔥 *ACHÈTE — Opportunité forte*",
            "GOOD":   "🟢🟢 *ACHÈTE — Bonne opportunité*",
            "NORMAL": "🟢 *ACHÈTE — Opportunité correcte*",
        }
        return titles.get(tier, "⚪ *À examiner*")

    # ═══════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════

    def _fmt_number(self, num: float) -> str:
        try:
            num = float(num or 0)
            if num >= 1_000_000:
                return f"{num/1_000_000:.1f}M"
            elif num >= 1_000:
                return f"{num/1_000:.0f}K"
            return f"{num:.0f}"
        except Exception:
            return "0"

    def _escape_md(self, text: str) -> str:
        if not text:
            return ""
        special = r"\_*[]()~`>#+-=|{}.!"
        result  = ""
        for char in str(text):
            if char in special:
                result += "\\" + char
            else:
                result += char
        return result

    # ═══════════════════════════════════════════════════
    # BOUTONS
    # ═══════════════════════════════════════════════════

    def _build_buttons(
        self, data: dict, decision: dict
    ) -> dict:
        address = data.get("address", "")
        symbol  = data.get("symbol", "")

        if symbol and symbol != "???":
            twitter_button = {
                "text": f"🐦 Twitter ${symbol}",
                "url":  f"https://twitter.com/search?q=%24{symbol}&f=live",
            }
        else:
            twitter_button = {
                "text": "🐦 Twitter Search",
                "url":  f"https://twitter.com/search?q={address}&f=live",
            }

        return {
            "inline_keyboard": [
                [{
                    "text": "🚀 ACHETER SUR PHOTON",
                    "url":  f"https://photon-sol.tinyastro.io/en/lp/{address}",
                }],
                [
                    {
                        "text": "📊 Chart",
                        "url":  f"https://dexscreener.com/solana/{address}",
                    },
                    {
                        "text": "🔍 Safety",
                        "url":  f"https://rugcheck.xyz/tokens/{address}",
                    },
                ],
                [
                    {
                        "text": "💱 Jupiter",
                        "url":  f"https://jup.ag/swap/SOL-{address}",
                    },
                    {
                        "text": "🔎 Solscan",
                        "url":  f"https://solscan.io/token/{address}",
                    },
                ],
                [twitter_button],
            ]
        }

    # ═══════════════════════════════════════════════════
    # ENVOI TELEGRAM TEXTE
    # ═══════════════════════════════════════════════════

    async def _send_telegram(
        self,
        message: str,
        buttons: dict | None = None,
    ) -> bool:
        """Envoie un message texte Telegram."""
        if not self.bot_token or not self.chat_id:
            logger.error("[ALERT] Credentials manquants")
            return False

        try:
            session = await self._get_session()
            url     = (
                f"https://api.telegram.org/bot"
                f"{self.bot_token}/sendMessage"
            )
            payload: dict = {
                "chat_id":                  self.chat_id,
                "text":                     message,
                "parse_mode":               "MarkdownV2",
                "disable_web_page_preview": True,
            }

            if buttons:
                payload["reply_markup"] = buttons

            for attempt in range(3):
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get("ok"):
                        logger.info("[ALERT] ✅ Message Telegram envoyé")
                        return True

                    if resp.status == 429:
                        retry_after = result.get(
                            "parameters", {}
                        ).get("retry_after", 5)
                        logger.warning(
                            f"[ALERT] ⏳ Rate limit, attente "
                            f"{retry_after}s (tentative {attempt+1}/3)"
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status == 400:
                        error_desc = result.get(
                            "description", ""
                        )
                        if "can't parse" in error_desc.lower():
                            logger.warning(
                                "[ALERT] ⚠️ Erreur Markdown, "
                                "retry sans formatage"
                            )
                            payload["parse_mode"] = ""
                            payload["text"]       = self._strip_markdown(
                                message
                            )
                            continue

                    logger.error(
                        f"[ALERT] ❌ Telegram erreur "
                        f"{resp.status}: {result}"
                    )
                    return False

            return False

        except Exception as e:
            logger.error(f"[ALERT] Exception: {e}")
            return False

    # ═══════════════════════════════════════════════════
    # ENVOI TELEGRAM PHOTO v7.0 🆕
    # ═══════════════════════════════════════════════════

    async def _send_telegram_photo(
        self,
        photo_url: str,
        caption:   str,
        buttons:   dict | None = None,
    ) -> bool:
        """
        Envoie une PHOTO Telegram avec caption.
        Utilisé pour envoyer les charts DexScreener.

        Si l'envoi photo échoue → fallback vers envoi texte.
        """
        if not self.bot_token or not self.chat_id:
            logger.error("[ALERT] Credentials manquants")
            return False

        try:
            session = await self._get_session()
            url     = (
                f"https://api.telegram.org/bot"
                f"{self.bot_token}/sendPhoto"
            )

            # Telegram limite le caption à 1024 caractères
            # Si trop long, on tronque et on ajoute "..."
            if len(caption) > 1024:
                caption = caption[:1020] + "\\.\\.\\."

            payload: dict = {
                "chat_id":    self.chat_id,
                "photo":      photo_url,
                "caption":    caption,
                "parse_mode": "MarkdownV2",
            }

            if buttons:
                payload["reply_markup"] = buttons

            for attempt in range(2):  # 2 tentatives seulement
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get("ok"):
                        logger.info(
                            "[ALERT] ✅ Photo Telegram envoyée"
                        )
                        return True

                    if resp.status == 429:
                        retry_after = result.get(
                            "parameters", {}
                        ).get("retry_after", 5)
                        logger.warning(
                            f"[ALERT] ⏳ Rate limit photo, "
                            f"attente {retry_after}s"
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    # Photo failed → fallback texte
                    logger.warning(
                        f"[ALERT] ⚠️ Photo échec ({resp.status}), "
                        f"fallback texte"
                    )
                    return await self._send_telegram(caption, buttons)

            # Toutes tentatives échouées → fallback texte
            logger.warning("[ALERT] Photo échec total, fallback texte")
            return await self._send_telegram(caption, buttons)

        except Exception as e:
            logger.error(f"[ALERT] Photo exception: {e}")
            # Fallback texte en cas d'erreur
            return await self._send_telegram(caption, buttons)

    def _strip_markdown(self, text: str) -> str:
        """Supprime les caractères Markdown pour le fallback."""
        import re
        text = re.sub(r'\\([_*\[\]()~`>#\+\-=|{}.!])', r'\1', text)
        text = re.sub(r'[*_`]', '', text)
        return text

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()