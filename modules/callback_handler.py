# modules/callback_handler.py — v1.2
# ═══════════════════════════════════════════════
# v1.2 CORRECTIONS :
# + FIX DÉFAUT #1 : ajout auto au sell_signal_generator
#   après confirmation achat (bouton ✅)
# + sell_generator injecté dans __init__
# + _add_to_sell_tracker() : récupère prix + ajoute position
# + Message de confirmation mis à jour

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
        sell_generator=None,      # ← v1.2 NOUVEAU
    ):
        self.token               = bot_token
        self.trade_assistant     = trade_assistant
        self.ml_scorer           = ml_scorer
        self.performance_tracker = performance_tracker
        self.portfolio_tracker   = portfolio_tracker
        self.sell_generator      = sell_generator   # ← v1.2
        self.base_url            = f"https://api.telegram.org/bot{bot_token}"

    # ════════════════════════════════════════
    # POINT D'ENTRÉE
    # ════════════════════════════════════════

    async def handle(self, callback_query: dict):
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
        mint, amount = self._parse_mint_amount(data, prefix="buy_")
        if mint is None:
            await self._answer(callback_id, "❌ Erreur format callback")
            return

        symbol     = "TOKEN"
        photon_url = (
            f"https://photon-sol.tinyastro.io/en/lp/{mint}"
            f"?amount={amount:.6f}"
        )

        if self.trade_assistant:
            pending   = self.trade_assistant.pending_buys.get(mint, {})
            symbol    = pending.get("symbol", "TOKEN")
            sol_price = getattr(self.trade_assistant, "SOL_PRICE_USD", 200)
            amount_sol = (amount * 1.08) / max(sol_price, 1)
            photon_url = (
                f"https://photon-sol.tinyastro.io/en/lp/{mint}"
                f"?amount={amount_sol:.6f}"
            )

        await self._answer(
            callback_id,
            f"🚀 Ouvre Photon et achète {symbol} !",
            show_alert=True,
        )

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
        v1.2 : Confirme l'achat ET ajoute au sell_signal_generator
        pour surveillance SL/TP automatique.
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
                logger.error(
                    "[CALLBACK] confirm_buy_from_callback() manquant"
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

        symbol = trade.get("symbol", "TOKEN")
        score  = trade.get("score", 0)
        tier   = trade.get("tier", "NORMAL")
        mc     = trade.get("market_cap", 0)
        price  = trade.get("entry_price", 0)

        # ── v1.2 : Ajouter au sell_signal_generator ───
        # FIX DÉFAUT #1 : SL/TP automatique sur les vrais achats
        sell_tracker_added = False
        if self.sell_generator and mint and price > 0:
            try:
                # Récupère les données actuelles pour buy_ratio/volume
                token_data = await self._fetch_token_data(mint)

                entry_liquidity = 0
                entry_buy_ratio = 60  # valeur par défaut
                entry_volume_1h = 0

                if token_data:
                    entry_liquidity = token_data.get("liquidity", 0)
                    entry_buy_ratio = token_data.get("buy_ratio", 60)
                    entry_volume_1h = token_data.get("volume_1h", 0)
                    # Si pas de prix depuis le trade, prend le live
                    if price == 0:
                        price = token_data.get("price", 0)

                if price > 0:
                    self.sell_generator.add_position(
                        mint=mint,
                        symbol=symbol,
                        entry_price=price,
                        entry_mc=mc,
                        entry_liquidity=entry_liquidity,
                        entry_buy_ratio=entry_buy_ratio,
                        entry_volume_1h=entry_volume_1h,
                        source="inline_buy",
                    )
                    sell_tracker_added = True
                    logger.info(
                        f"[CALLBACK] ✅ SL/TP activé : "
                        f"${symbol} @ ${price:.8f} | "
                        f"SL: {self.sell_generator.SL_PCT}%"
                    )
                else:
                    logger.warning(
                        f"[CALLBACK] Prix = 0, SL non activé pour {symbol}"
                    )

            except Exception as e:
                logger.error(f"[CALLBACK] sell_generator error: {e}")

        # ── Répondre au callback ──────────────────────
        await self._answer(
            callback_id,
            f"✅ {symbol} enregistré ! SL à {self.sell_generator.SL_PCT if self.sell_generator else -25}%",
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

        sl_pct = (
            self.sell_generator.SL_PCT
            if self.sell_generator
            else -25
        )

        # ── Message de confirmation ───────────────────
        msg = (
            f"✅ <b>Achat enregistré — {symbol}</b>\n\n"
            f"💰 Investi : <b>{amount}€</b>\n"
            f"🎯 Score : <b>{score:.1f}/10</b> "
            f"{tier_emoji} <b>{tier}</b>\n"
            f"📊 MC au buy : <b>{mc_str}</b>\n"
            f"⏰ {datetime.now().strftime('%H:%M:%S')}\n\n"
            f"━━━━━━━━━━━━━━\n"
        )

        # Infos SL/TP
        if sell_tracker_added:
            msg += (
                f"🛡️ <b>Protection automatique activée :</b>\n"
                f"  🛑 Stop Loss : <b>{sl_pct}%</b> → alerte auto\n"
                f"  🎯 TP1 à <b>+50%</b> | TP2 à <b>+100%</b>\n"
                f"  🎯 TP3 à <b>+200%</b> | TP4 à <b>+500%</b>\n\n"
            )
        else:
            msg += (
                f"⚠️ <b>SL non activé</b> (prix indisponible)\n"
                f"Tape <code>/watch {mint}</code> manuellement\n\n"
            )

        msg += (
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
            f"[CALLBACK] ✅ Achat complet: {symbol} {amount}€ "
            f"| SL actif: {sell_tracker_added} "
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
    # v1.2 : Fetch prix live pour le sell tracker
    # ════════════════════════════════════════

    async def _fetch_token_data(self, mint: str) -> dict | None:
        """
        Récupère prix + données pour initialiser le sell tracker.
        """
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()

            pairs = data.get("pairs") or []
            if not pairs:
                return None

            pair     = pairs[0]
            txns     = pair.get("txns", {}) or {}
            h1       = txns.get("h1", {}) or {}
            buys_1h  = h1.get("buys", 0)
            sells_1h = h1.get("sells", 0)
            txns_1h  = buys_1h + sells_1h
            buy_ratio = round(buys_1h / txns_1h * 100, 1) if txns_1h > 0 else 60

            return {
                "price":      float(pair.get("priceUsd", 0) or 0),
                "market_cap": pair.get("marketCap", 0) or pair.get("fdv", 0) or 0,
                "liquidity":  pair.get("liquidity", {}).get("usd", 0) or 0,
                "volume_1h":  pair.get("volume", {}).get("h1", 0) or 0,
                "buy_ratio":  buy_ratio,
            }
        except Exception as e:
            logger.debug(f"[CALLBACK] _fetch_token_data: {e}")
            return None

    # ════════════════════════════════════════
    # HELPERS PARSING
    # ════════════════════════════════════════

    def _parse_mint_amount(
        self,
        data:   str,
        prefix: str,
    ) -> tuple[str | None, float]:
        try:
            without_prefix = data[len(prefix):]
            parts          = without_prefix.rsplit("_", 1)
            if len(parts) != 2:
                raise ValueError(f"Format invalide: {data}")
            mint   = parts[0]
            amount = float(parts[1])
            if not mint:
                raise ValueError("Mint vide")
            return mint, amount
        except (ValueError, IndexError) as e:
            logger.error(
                f"[CALLBACK] _parse_mint_amount error: {e} | data={data}"
            )
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
        url     = f"{self.base_url}/answerCallbackQuery"
        payload = {
            "callback_query_id": callback_id,
            "text":              text[:200],
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