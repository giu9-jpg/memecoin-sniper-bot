# modules/alert_sender.py — v8.0 CORRIGÉ FINAL
# ═══════════════════════════════════════════════
# FIXES v8.0 :
# + json.dumps(buttons) dans _send_telegram() — BUG CRITIQUE corrigé
# + send_alert() accepte mint/symbol/score/tier/suggested_amount/market_cap/price
# + Boutons BUY inline dans chaque alerte
# + send_simple() pour messages HTML
# + answer_callback() et edit_message()
# + register_pending() appelé auto à chaque alerte

import os
import json
import asyncio
import aiohttp
from utils.logger import logger
from modules.decision_engine import DecisionEngine


class AlertSender:

    def __init__(self, market_context=None, trade_assistant=None):
        self.bot_token       = None
        self.chat_id         = None
        self.session         = None
        self.market_context  = market_context
        self.trade_assistant = trade_assistant
        self.decision_eng    = DecisionEngine(
            market_context=market_context
        )
        self._load_credentials()

    def set_trade_assistant(self, ta):
        """Injecte le trade_assistant après init."""
        self.trade_assistant = ta

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
            "🤖 *BOT v13\\.4 démarré*\n"
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
            "📸 Charts photos : ON\n"
            "🛒 Boutons BUY inline : ON\n"
            "🎮 Paper Trading : ON\n\n"
            "⏳ En attente\\.\\.\\."
        )
        return await self._send_telegram(message, buttons=None)

    # ═══════════════════════════════════════════════════
    # ENVOI PRINCIPAL v8.0
    # ═══════════════════════════════════════════════════

    async def send_alert(
        self,
        token_data:       dict,
        decision:         dict | None = None,
        chart_url:        str  | None = None,
        mint:             str  | None = None,
        symbol:           str  | None = None,
        score:            float       = 0,
        tier:             str         = "NORMAL",
        suggested_amount: float       = 10,
        market_cap:       float       = 0,
        price:            float       = 0,
    ) -> bool:
        """
        Envoie une alerte Telegram avec boutons BUY inline.

        Les kwargs mint/symbol/score/tier/suggested_amount/market_cap/price
        sont passés par main.py v13.4 pour les boutons inline et
        register_pending(). Ils ont priorité sur token_data.
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

        # Résoudre les valeurs (kwargs > token_data)
        _mint   = mint   or token_data.get("address", "")
        _symbol = symbol or token_data.get("symbol", "???")
        _score  = score  or float(token_data.get("score", 0))
        _tier   = tier   or decision.get("tier", "NORMAL")
        _amount = suggested_amount or float(decision.get("amount_eur", 10))
        _mc     = market_cap or float(token_data.get("market_cap", 0))
        # FIX : cherche "price_usd" ET "price" pour compatibilité
        _price  = price or float(
            token_data.get("price_usd", 0)
            or token_data.get("price", 0)
        )

        # Enregistrer en pending pour callback_handler
        if _mint and self.trade_assistant:
            try:
                self.trade_assistant.register_pending(
                    mint=_mint,
                    symbol=_symbol,
                    score=_score,
                    tier=_tier,
                    amount=_amount,
                    market_cap=_mc,
                    price=_price,
                    alert_data=token_data,
                )
            except AttributeError:
                # trade_assistant sans register_pending → skip silencieux
                pass
            except Exception as e:
                logger.warning(f"[ALERT] register_pending échoué: {e}")

        message = self._build_message(token_data, decision)
        buttons = self._build_buttons_v8(
            data=token_data,
            decision=decision,
            suggested_amount=_amount,
            mint_override=_mint,
            symbol_override=_symbol,
        )

        if chart_url:
            return await self._send_telegram_photo(
                photo_url=chart_url,
                caption=message,
                buttons=buttons,
            )

        return await self._send_telegram(message, buttons)

    # ═══════════════════════════════════════════════════
    # BOUTONS v8.0
    # ═══════════════════════════════════════════════════

    def _build_buttons_v8(
        self,
        data:             dict,
        decision:         dict,
        suggested_amount: float      = 10,
        mint_override:    str | None = None,
        symbol_override:  str | None = None,
    ) -> dict:
        """
        Clavier inline :
          Ligne 0 : BUY 5€ | BUY 10€ | BUY 20€
          Ligne 1 : 🚀 ACHETER SUR PHOTON
          Ligne 2 : 📊 Chart | 🔍 Safety
          Ligne 3 : 💱 Jupiter | 🔎 Solscan
          Ligne 4 : 🐦 Twitter
          Ligne 5 : ✅ J'ai acheté ! | ❌ Ignorer
        """
        address = mint_override or data.get("address", "")
        symbol  = symbol_override or data.get("symbol", "???")

        amounts = self._get_amount_options(suggested_amount)
        buy_row = []
        for amt in amounts:
            emoji = "🟢" if float(amt) == float(suggested_amount) else "⚪"
            buy_row.append({
                "text":          f"{emoji} BUY {amt}€",
                "callback_data": f"buy_{address}_{amt}",
            })

        confirm_row = [
            {
                "text":          "✅ J'ai acheté !",
                "callback_data": f"bought_{address}_{suggested_amount}",
            },
            {
                "text":          "❌ Ignorer",
                "callback_data": f"ignore_{address}",
            },
        ]

        if symbol and symbol not in ("???", ""):
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
                buy_row,
                [{
                    "text": "🚀 ACHETER SUR PHOTON",
                    "url":  f"https://photon-sol.tinyastro.io/en/lp/{address}",
                }],
                [
                    {"text": "📊 Chart",
                     "url": f"https://dexscreener.com/solana/{address}"},
                    {"text": "🔍 Safety",
                     "url": f"https://rugcheck.xyz/tokens/{address}"},
                ],
                [
                    {"text": "💱 Jupiter",
                     "url": f"https://jup.ag/swap/SOL-{address}"},
                    {"text": "🔎 Solscan",
                     "url": f"https://solscan.io/token/{address}"},
                ],
                [twitter_button],
                confirm_row,
            ]
        }

    def _get_amount_options(self, suggested: float) -> list:
        """3 montants dont le suggéré au centre."""
        mapping = {
            10: [5,  10, 20],
            8:  [5,   8, 15],
            6:  [3,   6, 10],
            5:  [3,   5, 10],
        }
        if suggested in mapping:
            return mapping[suggested]
        low  = max(1, round(suggested * 0.5))
        high = round(suggested * 2)
        return [low, int(suggested), high]

    # ═══════════════════════════════════════════════════
    # UTILITAIRES v8.0
    # ═══════════════════════════════════════════════════

    async def send_simple(
        self,
        message:    str,
        keyboard:   dict | None = None,
        parse_mode: str = "HTML",
    ) -> bool:
        """Message simple en HTML (pour /sold, callbacks, etc.)."""
        self._load_credentials()
        if not self.bot_token or not self.chat_id:
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
                "parse_mode":               parse_mode,
                "disable_web_page_preview": True,
            }
            if keyboard:
                payload["reply_markup"] = json.dumps(keyboard)

            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()
                if resp.status == 200 and result.get("ok"):
                    return True
                logger.error(
                    f"[ALERT] send_simple {resp.status}: "
                    f"{result.get('description', '')}"
                )
                return False

        except Exception as e:
            logger.error(f"[ALERT] send_simple exception: {e}")
            return False

    async def answer_callback(
        self,
        callback_query_id: str,
        text:              str  = "",
        show_alert:        bool = False,
    ) -> bool:
        """Répond à un callback query."""
        self._load_credentials()
        try:
            session = await self._get_session()
            url     = (
                f"https://api.telegram.org/bot"
                f"{self.bot_token}/answerCallbackQuery"
            )
            payload = {
                "callback_query_id": callback_query_id,
                "text":              text,
                "show_alert":        show_alert,
            }
            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error(f"[ALERT] answer_callback: {e}")
            return False

    async def edit_message(
        self,
        chat_id:    str,
        message_id: int,
        text:       str,
        keyboard:   dict | None = None,
        parse_mode: str = "HTML",
    ) -> bool:
        """Édite un message existant."""
        self._load_credentials()
        try:
            session = await self._get_session()
            url     = (
                f"https://api.telegram.org/bot"
                f"{self.bot_token}/editMessageText"
            )
            payload: dict = {
                "chat_id":                  chat_id,
                "message_id":               message_id,
                "text":                     text,
                "parse_mode":               parse_mode,
                "disable_web_page_preview": True,
            }
            if keyboard:
                payload["reply_markup"] = json.dumps(keyboard)

            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                result = await resp.json()
                return resp.status == 200 and result.get("ok", False)
        except Exception as e:
            logger.error(f"[ALERT] edit_message: {e}")
            return False

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

        # Sécurité
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
        lines.append(title)
        lines.append("━━━━━━━━━━━━━━")
        lines.append(f"🪙 *{name_safe}* \\(${symbol_safe}\\)")
        lines.append("")
        lines.append(f"⭐ Score: *{score}/10*  |  💰 *{amount_eur}€*")
        lines.append(
            f"🛡️ Sécurité: *{safety_score}/10*  {safety_emoji}"
        )
        lines.append(f"🎯 Profit espéré : *\\+{profit_pct:.0f}%*")

        if safety_warnings:
            lines.append("")
            lines.append("⚠️ *Points d'attention:*")
            for warning in safety_warnings[:3]:
                lines.append(f"  • {self._escape_md(str(warning))}")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━")
        lines.append("🎯 *VENDRE À :*")
        if tp_levels:
            for i, tp in enumerate(tp_levels, 1):
                mult = tp.get("multiplier", 1)
                pct  = tp.get("sell_pct", 0)
                note = " _\\(récupère ta mise\\)_" if i == 1 else ""
                lines.append(f"  x{mult}  →  {pct:.0f}%{note}")
        lines.append(f"🛑 *STOP :* {sl_pct}%")
        lines.append("━━━━━━━━━━━━━━")
        lines.append("")
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
                sig       = self.market_context.get_market_signal()
                regime    = self._escape_md(sig["regime"])
                btc       = sig["btc_change_24h"]
                mkt_emoji = {
                    "BULLISH": "🚀",
                    "NEUTRAL": "😐",
                    "BEARISH": "🔴",
                }.get(sig["regime"], "⚪")
                btc_sign = "\\+" if btc >= 0 else ""
                lines.append(
                    f"  🌍 Marché {mkt_emoji} *{regime}* "
                    f"\\(BTC {btc_sign}{btc:.0f}%\\)"
                )
            except Exception:
                pass

        return "\n".join(lines)

    def _get_title(self, tier: str, has_critical: bool, alpha_count: int) -> str:
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
    # ENVOI TEXTE — FIX CRITIQUE : json.dumps(buttons)
    # ═══════════════════════════════════════════════════

    async def _send_telegram(
        self,
        message: str,
        buttons: dict | None = None,
    ) -> bool:
        """
        Envoie un message texte Telegram.
        FIX CRITIQUE : buttons est un dict → doit être sérialisé
        en JSON string pour l'API Telegram (reply_markup).
        """
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

            # FIX : json.dumps() obligatoire pour reply_markup
            if buttons:
                payload["reply_markup"] = (
                    json.dumps(buttons)
                    if isinstance(buttons, dict)
                    else buttons
                )

            for attempt in range(3):
                async with session.post(
                    url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get("ok"):
                        logger.info("[ALERT] ✅ Message Telegram envoyé")
                        return True

                    if resp.status == 429:
                        retry_after = (
                            result.get("parameters", {})
                            .get("retry_after", 5)
                        )
                        logger.warning(
                            f"[ALERT] ⏳ Rate limit {retry_after}s "
                            f"(tentative {attempt+1}/3)"
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status == 400:
                        err = result.get("description", "")
                        if "can't parse" in err.lower():
                            logger.warning(
                                "[ALERT] ⚠️ Erreur Markdown, retry sans formatage"
                            )
                            payload["parse_mode"] = ""
                            payload["text"]       = self._strip_markdown(message)
                            continue

                    logger.error(
                        f"[ALERT] ❌ Telegram {resp.status}: {result}"
                    )
                    return False

            return False

        except Exception as e:
            logger.error(f"[ALERT] Exception: {e}")
            return False

    # ═══════════════════════════════════════════════════
    # ENVOI PHOTO — FIX : json.dumps(buttons)
    # ═══════════════════════════════════════════════════

    async def _send_telegram_photo(
        self,
        photo_url: str,
        caption:   str,
        buttons:   dict | None = None,
    ) -> bool:
        """Envoie une PHOTO Telegram. Fallback texte si échec."""
        if not self.bot_token or not self.chat_id:
            logger.error("[ALERT] Credentials manquants")
            return False

        try:
            session = await self._get_session()
            url     = (
                f"https://api.telegram.org/bot"
                f"{self.bot_token}/sendPhoto"
            )

            if len(caption) > 1024:
                caption = caption[:1020] + "\\.\\.\\."

            payload: dict = {
                "chat_id":    self.chat_id,
                "photo":      photo_url,
                "caption":    caption,
                "parse_mode": "MarkdownV2",
            }

            # FIX : json.dumps() obligatoire
            if buttons:
                payload["reply_markup"] = (
                    json.dumps(buttons)
                    if isinstance(buttons, dict)
                    else buttons
                )

            for attempt in range(2):
                async with session.post(
                    url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get("ok"):
                        logger.info("[ALERT] ✅ Photo Telegram envoyée")
                        return True

                    if resp.status == 429:
                        retry_after = (
                            result.get("parameters", {})
                            .get("retry_after", 5)
                        )
                        logger.warning(
                            f"[ALERT] ⏳ Rate limit photo {retry_after}s"
                        )
                        await asyncio.sleep(retry_after)
                        continue

                    logger.warning(
                        f"[ALERT] ⚠️ Photo échec ({resp.status}), "
                        f"fallback texte"
                    )
                    return await self._send_telegram(caption, buttons)

            logger.warning("[ALERT] Photo échec total, fallback texte")
            return await self._send_telegram(caption, buttons)

        except Exception as e:
            logger.error(f"[ALERT] Photo exception: {e}")
            return await self._send_telegram(caption, buttons)

    def _strip_markdown(self, text: str) -> str:
        """Supprime le Markdown pour le fallback."""
        import re
        text = re.sub(r'\\([_*\[\]()~`>#\+\-=|{}.!])', r'\1', text)
        text = re.sub(r'[*_`]', '', text)
        return text

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()