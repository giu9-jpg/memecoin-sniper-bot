# modules/alert_sender.py — v6.3 v12.0
# FIX v6.2 : send_alert() accepte decision en paramètre
# FIX v6.2 : _send_telegram() ne plante plus avec buttons=None
# FIX v6.2 : messages Markdown échappés correctement
# FIX v6.2 : twitter_signal affiché dans le message
#
# NOUVEAU v12.0 :
# + Score sécurité affiché (avec emoji dynamique)
# + Warnings sécurité affichés (top 3)
# + Bouton Jupiter ajouté (backup Photon)
# + Bouton Solscan ajouté
# + Bouton Twitter Search dynamique

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
            "🤖 *BOT v12\\.0 SAFETY démarré*\n"
            "━━━━━━━━━━━━━━\n"
            "✅ Prêt à sniper\n"
            "⭐ Score min : 7\\.5/10\n"
            "🛡️ Anti\\-Rug : ON\n"
            "💰 Capital : 100€\n"
            "🌍 Filtre macro : ON\n"
            "🐋 Alpha wallets : ON \\(15\\)\n"
            "🐦 Twitter : ON \\(7 comptes\\)\n"
            "📊 Performance : ON\n\n"
            "⏳ En attente\\.\\.\\."
        )
        return await self._send_telegram(message, buttons=None)

    # ═══════════════════════════════════════════════════
    # ENVOI PRINCIPAL
    # FIX : accepte decision en paramètre optionnel
    # ═══════════════════════════════════════════════════

    async def send_alert(
        self,
        token_data: dict,
        decision:   dict | None = None,
    ) -> bool:
        """
        Envoie une alerte Telegram.
        FIX : si decision est fournie (depuis main.py), on ne rappelle
        pas decide() pour éviter le double appel.
        """
        self._load_credentials()
        if not self.bot_token or not self.chat_id:
            return False

        # Calcule la décision seulement si pas déjà fournie
        if decision is None:
            decision = self.decision_eng.decide(token_data)

        if decision["action"] == "IGNORE":
            logger.info(
                f"[ALERT] Token IGNORÉ: {decision.get('reason', '')}"
            )
            return False

        message = self._build_message(token_data, decision)
        buttons = self._build_buttons(token_data, decision)

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
        # Utilise le safety check si dispo, sinon fallback ancien
        safety_data = data.get("safety", {})

        if safety_data:
            # Nouveau système v12.0 - score sécurité détaillé
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
            # Fallback ancien système
            safety_score    = 10
            safety_warnings = []
            is_safe = (
                not data.get("is_honeypot")
                and not data.get("freeze_auth")
                and data.get("top_10_holders_pct", 0) < 50
            )
            safety_emoji = "✅ OK" if is_safe else "⚠️ ATTENTION"

        # ── Titre ─────────────────────────────────────
        title = self._get_title(tier, has_critical, alpha_count)

        # ── Âge formaté ───────────────────────────────
        if age_minutes < 60:
            age_str = f"{age_minutes:.0f}min"
        elif age_minutes < 1440:
            age_str = f"{age_minutes/60:.1f}h"
        else:
            age_str = f"{age_minutes/1440:.1f}j"

        # ── Noms échappés pour Markdown ───────────────
        name_safe   = self._escape_md(name)
        symbol_safe = self._escape_md(symbol)

        lines = []

        # 1. Titre
        lines.append(title)
        lines.append("━━━━━━━━━━━━━━")
        lines.append(f"🪙 *{name_safe}* \\(${symbol_safe}\\)")
        lines.append("")

        # 2. Score + Sécurité + montant  (v12.0)
        lines.append(f"⭐ Score: *{score}/10*  |  💰 *{amount_eur}€*")
        lines.append(
            f"🛡️ Sécurité: *{safety_score}/10*  {safety_emoji}"
        )
        lines.append(f"🎯 Profit espéré : *\\+{profit_pct:.0f}%*")

        # Warnings sécurité si présents (v12.0)
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

        # Alpha wallets
        if alpha_count > 0:
            lines.append(
                f"  🐋 *{alpha_count} alpha wallet\\(s\\) détecté\\(s\\)*"
            )

        # Twitter signal
        tw = data.get("twitter_signal")
        if tw:
            tw_user = self._escape_md(tw.get("username", ""))
            tw_tier = self._escape_md(tw.get("best_tier", ""))
            lines.append(f"  🐦 *@{tw_user}* \\({tw_tier}\\)")

        # Smart signals
        if has_critical:
            lines.append("  🚨 *SIGNAL CRITIQUE*")
        elif smart_count >= 3:
            lines.append(f"  🧠 {smart_count} smart signals")

        # Contexte marché
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
        """Formate un nombre : 85000 → 85K, 1200000 → 1.2M"""
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
        """
        FIX : échappe les caractères spéciaux Telegram MarkdownV2.
        Sans ça, les noms de tokens avec des - . ( ) etc font planter.
        """
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
    # BOUTONS v12.0
    # + Jupiter (backup si Photon down)
    # + Solscan (analyse on-chain)
    # + Twitter Search (buzz check dynamique)
    # ═══════════════════════════════════════════════════

    def _build_buttons(
        self, data: dict, decision: dict
    ) -> dict:
        address = data.get("address", "")
        symbol  = data.get("symbol", "")

        # Bouton Twitter dynamique selon si on a un symbole
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
                # Ligne 1 - Achat rapide Photon (le plus rapide)
                [{
                    "text": "🚀 ACHETER SUR PHOTON",
                    "url":  f"https://photon-sol.tinyastro.io/en/lp/{address}",
                }],
                # Ligne 2 - Chart + Safety
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
                # Ligne 3 - Jupiter (backup) + Solscan (v12.0)
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
                # Ligne 4 - Twitter search (v12.0)
                [twitter_button],
            ]
        }

    # ═══════════════════════════════════════════════════
    # ENVOI TELEGRAM
    # FIX : buttons=None ne plante plus
    # FIX : parse_mode MarkdownV2 pour meilleur rendu
    # ═══════════════════════════════════════════════════

    async def _send_telegram(
        self,
        message: str,
        buttons: dict | None = None,
    ) -> bool:
        """
        Envoie un message Telegram.
        FIX : n'inclut reply_markup que si buttons est fourni.
        FIX : retry automatique si rate limit (429).
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

            # FIX : n'ajoute reply_markup QUE si buttons est fourni
            if buttons:
                payload["reply_markup"] = buttons

            # FIX : retry sur rate limit
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

                    # Rate limit → attendre et réessayer
                    if resp.status == 429:
                        retry_after = result.get(
                            "parameters", {}
                        ).get("retry_after", 5)
                        logger.warning(
                            f"[ALERT] ⏳ Rate limit, attente "
                            f"{retry_after}s (tentative {attempt+1}/3)"
                        )
                        import asyncio
                        await asyncio.sleep(retry_after)
                        continue

                    # Erreur Markdown → fallback sans formatage
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

    def _strip_markdown(self, text: str) -> str:
        """
        FIX : supprime tous les caractères Markdown pour le fallback.
        Utilisé quand MarkdownV2 échoue.
        """
        import re
        # Supprime les échappements MarkdownV2
        text = re.sub(r'\\([_*\[\]()~`>#\+\-=|{}.!])', r'\1', text)
        # Supprime les balises restantes
        text = re.sub(r'[*_`]', '', text)
        return text

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()