# modules/callback_handler.py — v1.1
# ═══════════════════════════════════════════════
# v1.1 :
# + Utilise trade_assistant.confirm_buy_from_callback()
# + Compatible trade_assistant v1.1
# + Gestion erreurs robuste
#
# Callbacks supportés :
#   buy_{mint}_{amount}     → Prépare achat Photon + confirmation
#   bought_{mint}_{amount}  → Confirme achat + enregistre portfolio
#   ignore_{mint}           → Ignore l'alerte
# ═══════════════════════════════════════════════

import json
import aiohttp
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("callback_handler")


class CallbackHandler:

    def __init__(
        self,
        bot_token:           str,
        trade_assistant=None,
        ml_scorer=None,
        performance_tracker=None,
        portfolio_tracker=None,
    ):
        self.token               = bot_token
        self.trade_assistant     = trade_assistant
        self.ml_scorer           = ml_scorer
        self.performance_tracker = performance_tracker
        self.portfolio_tracker   = portfolio_tracker
        self.base_url            = f"https://api.telegram.org/bot{bot_token}"

    # ════════════════════════════════════════
    # POINT D'ENTRÉE
    # ════════════════════════════════════════

    async def handle(self, callback_query: dict):
        """
        Reçoit un callback_query Telegram.
        Route vers le bon handler selon callback_data.
        """
        try:
            callback_id = callback_query.get("id", "")
            data        = callback_query.get("data", "")
            message     = callback_query.get("message", {})
            chat_id     = str(message.get("chat", {}).get("id", ""))
            message_id  = message.get("message_id", 0)
            user        = callback_query.get("from", {})
            username    = (
                user.get("username")
                or user.get("first_name", "User")
            )

            logger.info(f"[CALLBACK] data='{data}' user=@{username}")

            if not data:
                await self._answer(callback_id, "❓ Données vides")
                return

            if data.startswith("buy_"):
                await self._handle_buy(
                    callback_id, chat_id, message_id, data, username
                )
            elif data.startswith("bought_"):
                await self._handle_bought(
                    callback_id, chat_id, message_id, data, username
                )
            elif data.startswith("ignore_"):
                await self._handle_ignore(
                    callback_id, chat_id, message_id, data, username
                )
            else:
                await self._answer(callback_id, "❓ Action inconnue")

        except Exception as e:
            logger.error(f"[CALLBACK] handle error: {e}")

    # ════════════════════════════════════════
    # HANDLER : buy_{mint}_{amount}
    # ════════════════════════════════════════

    async def _handle_buy(
        self,
        callback_id: str,
        chat_id:     str,
        message_id:  int,
        data:        str,
        username:    str,
    ):
        """
        Clic sur "🟢 BUY 10€"
        → Popup + message avec lien Photon + bouton de confirmation
        """
        mint, amount = self._parse_mint_amount(data, prefix="buy_")
        if mint is None:
            await self._answer(callback_id, "❌ Erreur format callback")
            return

        # Récupérer le symbole depuis pending_buys
        symbol = "TOKEN"
        photon_url = (
            f"https://photon-sol.tinyastro.io/en/lp/{mint}"
            f"?amount={amount:.6f}"
        )

        if self.trade_assistant:
            pending = self.trade_assistant.pending_buys.get(mint, {})
            symbol  = pending.get("symbol", "TOKEN")
            # Utiliser l'URL Photon avec le bon montant SOL
            sol_price = getattr(
                self.trade_assistant, "SOL_PRICE_USD", 200
            )
            amount_sol = (amount * 1.08) / max(sol_price, 1)
            photon_url = (
                f"https://photon-sol.tinyastro.io/en/lp/{mint}"
                f"?amount={amount_sol:.6f}"
            )

        # Popup de confirmation
        await self._answer(
            callback_id,
            f"🚀 Ouvre Photon et achète {symbol} !",
            show_alert=True,
        )

        # Message avec étapes + boutons
        keyboard = {
            "inline_keyboard": [
                [{
                    "text": f"⚡ Ouvrir Photon — {amount}€",
                    "url":  photon_url,
                }],
                [
                    {
                        "text":          f"✅ J'ai acheté {amount}€ !",
                        "callback_data": f"bought_{mint}_{amount}",
                    },
                    {
                        "text":          "❌ Annuler",
                        "callback_data": f"ignore_{mint}",
                    },
                ],
            ]
        }

        msg = (
            f"🛒 <b>Achat préparé — {symbol}</b>\n\n"
            f"💰 Montant sélectionné : <b>{amount}€</b>\n\n"
            f"📋 Étapes :\n"
            f"  1️⃣ Clique <b>Ouvrir Photon</b>\n"
            f"  2️⃣ Achète <b>{amount}€</b> de {symbol}\n"
            f"  3️⃣ Reviens ici → clique <b>✅ J'ai acheté</b>\n\n"
            f"<code>{mint[:20]}...</code>"
        )

        await self._send_message(chat_id, msg, keyboard)

    # ════════════════════════════════════════
    # HANDLER : bought_{mint}_{amount}
    # ════════════════════════════════════════

    async def _handle_bought(
        self,
        callback_id: str,
        chat_id:     str,
        message_id:  int,
        data:        str,
        username:    str,
    ):
        """
        Clic sur "✅ J'ai acheté X€ !"
        → Confirme via trade_assistant.confirm_buy_from_callback()
        → Enregistre dans portfolio
        → Envoie message de confirmation avec instructions /sold
        """
        mint, amount = self._parse_mint_amount(data, prefix="bought_")
        if mint is None:
            await self._answer(callback_id, "❌ Erreur format callback")
            return

        # ── Confirmer via trade_assistant ─────────────
        trade = None
        if self.trade_assistant:
            if hasattr(self.trade_assistant, "confirm_buy_from_callback"):
                trade = await self.trade_assistant.confirm_buy_from_callback(
                    mint=mint,
                    amount=amount,
                )
            else:
                # trade_assistant v1.0 sans la méthode → erreur claire
                logger.error(
                    "[CALLBACK] confirm_buy_from_callback() manquant "
                    "dans trade_assistant — mets à jour vers v1.1"
                )
                await self._answer(
                    callback_id,
                    "⚠️ Mise à jour requise (trade_assistant v1.1)",
                    show_alert=True,
                )
                return
        else:
            await self._answer(
                callback_id,
                "⚠️ TradeAssistant non disponible",
                show_alert=True,
            )
            return

        # ── Vérifier le résultat ──────────────────────
        if not trade or not trade.get("success"):
            reason = (
                trade.get("message", "Erreur inconnue")
                if trade else "trade_assistant None"
            )
            logger.warning(f"[CALLBACK] confirm_buy échoué: {reason}")
            await self._answer(
                callback_id,
                f"⚠️ {reason[:100]}",
                show_alert=True,
            )
            return

        # ── Extraire infos du trade ───────────────────
        symbol = trade.get("symbol", "TOKEN")
        score  = trade.get("score", 0)
        tier   = trade.get("tier", "NORMAL")
        mc     = trade.get("market_cap", 0)

        # ── Répondre au callback ──────────────────────
        await self._answer(
            callback_id,
            f"✅ {symbol} enregistré dans le portfolio !",
            show_alert=True,
        )

        # ── Formater market cap ───────────────────────
        if mc >= 1_000_000:
            mc_str = f"${mc / 1_000_000:.1f}M"
        elif mc >= 1_000:
            mc_str = f"${mc / 1_000:.0f}K"
        elif mc > 0:
            mc_str = f"${mc:.0f}"
        else:
            mc_str = "N/A"

        # ── Emoji tier ────────────────────────────────
        tier_emoji = {
            "ULTIMATE": "💎",
            "STRONG":   "🔥",
            "GOOD":     "🟢",
            "NORMAL":   "⚪",
            "MANUAL":   "✋",
        }.get(tier, "⚪")

        # ── Message de confirmation ───────────────────
        msg = (
            f"✅ <b>Achat enregistré — {symbol}</b>\n\n"
            f"💰 Investi : <b>{amount}€</b>\n"
            f"🎯 Score : <b>{score:.1f}/10</b> "
            f"{tier_emoji} <b>{tier}</b>\n"
            f"📊 MC au buy : <b>{mc_str}</b>\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"━━━━━━━━━━━━━━\n"
            f"📝 <b>Quand tu vends, tape :</b>\n"
            f"<code>/sold {symbol} +150</code>  → si +150%\n"
            f"<code>/sold {symbol} -30</code>   → si -30%\n\n"
            f"💼 <code>/portfolio</code> — voir tes positions\n"
            f"📊 <code>/positions</code> — sell signals actifs\n"
            f"🎮 <code>/simulate</code>  — paper trading"
        )

        await self._send_message(chat_id, msg)
        logger.info(
            f"[CALLBACK] ✅ Achat confirmé: {symbol} {amount}€ "
            f"par @{username}"
        )

    # ════════════════════════════════════════
    # HANDLER : ignore_{mint}
    # ════════════════════════════════════════

    async def _handle_ignore(
        self,
        callback_id: str,
        chat_id:     str,
        message_id:  int,
        data:        str,
        username:    str,
    ):
        """
        Clic sur "❌ Ignorer"
        → Retire le token des pending
        → Notification discrète
        """
        # Parse le mint (ignore_{mint})
        mint = data[len("ignore_"):] if data.startswith("ignore_") else ""

        if mint and self.trade_assistant:
            removed = self.trade_assistant.pending_buys.pop(mint, None)
            if removed:
                logger.info(
                    f"[CALLBACK] Ignoré: "
                    f"${removed.get('symbol', '?')} par @{username}"
                )

        await self._answer(callback_id, "⏭️ Alerte ignorée")

    # ════════════════════════════════════════
    # HELPERS PARSING
    # ════════════════════════════════════════

    def _parse_mint_amount(
        self,
        data:   str,
        prefix: str,
    ) -> tuple[str | None, float]:
        """
        Parse 'buy_{mint}_{amount}' ou 'bought_{mint}_{amount}'.

        Les adresses Solana sont en base58 (pas d'underscore).
        Le montant est toujours le dernier segment.

        Retourne (mint, amount) ou (None, 0) si erreur.
        """
        try:
            # Supprimer le préfixe
            without_prefix = data[len(prefix):]

            # Le montant est toujours le dernier segment
            parts  = without_prefix.rsplit("_", 1)
            if len(parts) != 2:
                raise ValueError(f"Format invalide: {data}")

            mint   = parts[0]
            amount = float(parts[1])

            if not mint:
                raise ValueError("Mint vide")

            return mint, amount

        except (ValueError, IndexError) as e:
            logger.error(f"[CALLBACK] _parse_mint_amount error: {e} | data={data}")
            return None, 0.0

    # ════════════════════════════════════════
    # HELPERS HTTP
    # ════════════════════════════════════════

    async def _answer(
        self,
        callback_id: str,
        text:        str  = "",
        show_alert:  bool = False,
    ):
        """
        answerCallbackQuery — OBLIGATOIRE dans les 10s après chaque clic.
        show_alert=True  → popup bloquant
        show_alert=False → notification discrète en haut
        """
        url     = f"{self.base_url}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_id,
            "text":              text[:200],  # max 200 chars Telegram
            "show_alert":        show_alert,
        }
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                )
        except Exception as e:
            logger.error(f"[CALLBACK] _answer error: {e}")

    async def _send_message(
        self,
        chat_id:  str,
        text:     str,
        keyboard: dict | None = None,
    ):
        """sendMessage en HTML."""
        url     = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id":                  chat_id,
            "text":                     text,
            "parse_mode":               "HTML",
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = json.dumps(keyboard)

        try:
            async with aiohttp.ClientSession() as s:
                resp = await s.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                )
                if resp.status != 200:
                    result = await resp.json()
                    logger.error(
                        f"[CALLBACK] _send_message {resp.status}: "
                        f"{result.get('description', '')}"
                    )
        except Exception as e:
            logger.error(f"[CALLBACK] _send_message error: {e}")