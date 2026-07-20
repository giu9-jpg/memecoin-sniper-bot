# modules/position_tracker.py — v7.1 CORRIGÉ
# FIX AUDIT :
# - import asyncio au niveau module (plus en local dans _send_telegram)
# - buttons sérialisés avec json.dumps dans _send_telegram
# - Protection division par zéro dans _check_position

import asyncio
import json
import time
import os
import aiohttp
from utils.logger import logger

POSITION_TIMEOUT_MIN = 10_080   # 7 jours en minutes


class PositionTracker:

    def __init__(self, alert_sender=None):
        self.positions    = {}
        self.alert_sender = alert_sender
        self.bot_token    = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id      = os.getenv("TELEGRAM_CHAT_ID", "")
        self.session      = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    def add_position(
        self,
        token_data: dict,
        decision:   dict,
        amount_eur: float,
    ):
        address     = token_data.get("address", "")
        # FIX : cherche price_usd ET price pour compatibilité
        price_entry = float(
            token_data.get("price_usd", 0)
            or token_data.get("price", 0)
            or 0
        )

        if not address:
            logger.warning("[POS] add_position : adresse vide")
            return

        if address in self.positions and not self.positions[address].get("closed"):
            logger.debug(
                f"[POS] Position déjà ouverte : "
                f"{token_data.get('symbol')}"
            )
            return

        if price_entry <= 0:
            logger.warning(
                f"[POS] Prix d'entrée invalide pour "
                f"{token_data.get('symbol')} : {price_entry}"
            )
            return

        tp_levels = decision.get("tp_levels", [])

        self.positions[address] = {
            "address":     address,
            "symbol":      token_data.get("symbol", "???"),
            "name":        token_data.get("name", "Unknown"),
            "price_entry": price_entry,
            "price_high":  price_entry,
            "amount_eur":  float(amount_eur or 0),
            "remaining":   100,
            "tp_levels":   tp_levels,
            "tp_hit":      [],
            "sl_pct":      float(decision.get("sl_pct", -30)),
            "entry_time":  time.time(),
            "last_check":  time.time(),
            "closed":      False,
            "tier":        decision.get("tier", ""),
            "score":       float(token_data.get("score", 0)),
        }

        logger.info(
            f"[POS] ➕ Ouverte : "
            f"{token_data.get('symbol')} | "
            f"{amount_eur}€ | "
            f"entrée ${price_entry:.8f} | "
            f"tier {decision.get('tier')}"
        )

    async def check_all_positions(self):
        open_positions = [
            (addr, pos)
            for addr, pos in self.positions.items()
            if not pos.get("closed")
        ]

        if not open_positions:
            return

        logger.info(
            f"[POS] Vérification {len(open_positions)} position(s)"
        )

        for address, position in open_positions:
            try:
                current_price = await self._get_current_price(address)
                if current_price and current_price > 0:
                    await self._check_position(address, position, current_price)
            except Exception as e:
                logger.error(f"[POS] Erreur check {address[:8]}: {e}")

    async def _check_position(
        self,
        address:       str,
        position:      dict,
        current_price: float,
    ):
        entry = float(position.get("price_entry", 0))
        # FIX : protection division par zéro
        if not entry or entry <= 0:
            return

        multiplier = current_price / entry
        change_pct = (multiplier - 1) * 100
        age_min    = (time.time() - position["entry_time"]) / 60
        sl_pct     = float(position.get("sl_pct", -30))
        symbol     = position.get("symbol", "???")

        if current_price > position.get("price_high", 0):
            self.positions[address]["price_high"] = current_price

        logger.debug(
            f"[POS] {symbol} : "
            f"x{multiplier:.3f} ({change_pct:+.1f}%) | "
            f"SL:{sl_pct}% | âge:{age_min:.0f}min"
        )

        # ── STOP LOSS ─────────────────────────────────
        if change_pct <= sl_pct and position.get("remaining", 0) > 0:
            logger.info(
                f"[POS] 🛑 SL touché {symbol}: "
                f"{change_pct:.1f}% ≤ {sl_pct}%"
            )
            await self._send_sl_alert(position, current_price, change_pct)
            self.positions[address]["closed"]    = True
            self.positions[address]["remaining"] = 0
            return

        # ── TAKE PROFITS ──────────────────────────────
        tp_levels = position.get("tp_levels", [])
        tp_hit    = position.get("tp_hit", [])

        for i, tp in enumerate(tp_levels):
            if i in tp_hit:
                continue

            tp_mult  = float(tp.get("multiplier", 999))
            sell_pct = int(tp.get("sell_pct", 0))

            if multiplier >= tp_mult:
                logger.info(
                    f"[POS] 🎯 TP{i+1} touché {symbol}: "
                    f"x{multiplier:.2f} ≥ x{tp_mult}"
                )
                await self._send_tp_alert(
                    position, i + 1, tp,
                    current_price, multiplier, sell_pct,
                )
                self.positions[address]["tp_hit"].append(i)
                self.positions[address]["remaining"] = max(
                    0,
                    self.positions[address]["remaining"] - sell_pct,
                )

                if (
                    i == len(tp_levels) - 1
                    or self.positions[address]["remaining"] <= 0
                ):
                    self.positions[address]["closed"] = True

        # ── TIMEOUT (7 jours) ─────────────────────────
        if age_min > POSITION_TIMEOUT_MIN:
            self.positions[address]["closed"] = True
            logger.info(f"[POS] ⏰ Timeout (7j) : {symbol}")

    async def _send_tp_alert(
        self,
        position:      dict,
        tp_num:        int,
        tp_level:      dict,
        current_price: float,
        multiplier:    float,
        sell_pct:      int,
    ):
        symbol      = position.get("symbol", "???")
        amount_eur  = float(position.get("amount_eur", 0))
        entry_price = float(position.get("price_entry", 0))
        tier        = position.get("tier", "")
        profit_eur  = round(amount_eur * multiplier - amount_eur, 2)
        remaining   = max(0, position.get("remaining", 100) - sell_pct)
        address     = position.get("address", "")
        age_min     = int(
            (time.time() - position.get("entry_time", time.time())) / 60
        )

        tier_emoji = {
            "ULTIMATE": "💎", "STRONG": "🔥",
            "GOOD": "✅", "NORMAL": "📊",
        }.get(tier, "⚪")

        message = (
            f"🎯 *TAKE PROFIT {tp_num} ATTEINT \\!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{tier_emoji} *{self._esc(symbol)}* — {tier}\n\n"
            f"✅ *x{multiplier:.2f}* atteint \\!\n"
            f"💰 *VENDS {sell_pct}% de ta position*\n\n"
            f"📊 *Détails :*\n"
            f"  Prix entrée  : `${entry_price:.8f}`\n"
            f"  Prix actuel  : `${current_price:.8f}`\n"
            f"  Gain         : *\\+{(multiplier-1)*100:.0f}%*\n"
            f"  Profit       : *\\+{profit_eur:.1f}€*\n"
            f"  Reste à hold : {remaining}%\n\n"
            f"⏰ Hold : {age_min} min"
        )

        buttons = {
            "inline_keyboard": [[
                {
                    "text": f"🚀 Vendre {sell_pct}% sur Photon",
                    "url":  f"https://photon-sol.tinyastro.io/en/lp/{address}",
                }
            ], [
                {
                    "text": "📊 DexScreener",
                    "url":  f"https://dexscreener.com/solana/{address}",
                }
            ]]
        }

        await self._send_telegram(message, buttons)

    async def _send_sl_alert(
        self,
        position:      dict,
        current_price: float,
        change_pct:    float,
    ):
        symbol      = position.get("symbol", "???")
        amount_eur  = float(position.get("amount_eur", 0))
        entry_price = float(position.get("price_entry", 0))
        loss_eur    = round(amount_eur * abs(change_pct) / 100, 2)
        address     = position.get("address", "")
        price_high  = float(position.get("price_high", 0))
        age_min     = int(
            (time.time() - position.get("entry_time", time.time())) / 60
        )

        if entry_price > 0 and price_high > 0:
            high_mult = price_high / entry_price
            high_str  = f"x{high_mult:.2f}"
        else:
            high_str = "N/A"

        message = (
            f"🛑 *STOP LOSS TOUCHÉ \\!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *{self._esc(symbol)}*\n\n"
            f"❌ *VENDS TOUT MAINTENANT*\n\n"
            f"📊 *Détails :*\n"
            f"  Prix entrée  : `${entry_price:.8f}`\n"
            f"  Prix actuel  : `${current_price:.8f}`\n"
            f"  Baisse       : *{change_pct:.1f}%*\n"
            f"  Perte est\\.  : *\\-{loss_eur:.1f}€*\n"
            f"  Plus haut    : {high_str}\n\n"
            f"⏰ Hold : {age_min} min\n\n"
            f"💡 *Ne laisse pas courir les pertes \\!*"
        )

        buttons = {
            "inline_keyboard": [[
                {
                    "text": "🛑 VENDRE TOUT sur Photon",
                    "url":  f"https://photon-sol.tinyastro.io/en/lp/{address}",
                }
            ], [
                {
                    "text": "📊 DexScreener",
                    "url":  f"https://dexscreener.com/solana/{address}",
                }
            ]]
        }

        await self._send_telegram(message, buttons)

    async def _send_telegram(
        self,
        message: str,
        buttons: dict | None = None,
    ):
        """
        Envoie un message Telegram.
        FIX : buttons sérialisés avec json.dumps
        FIX : import asyncio au niveau module (pas en local)
        """
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id   = os.getenv("TELEGRAM_CHAT_ID", "")

        if not bot_token or not chat_id:
            return

        try:
            session = await self._get_session()
            url     = f"https://api.telegram.org/bot{bot_token}/sendMessage"

            payload: dict = {
                "chat_id":                  chat_id,
                "text":                     message,
                "parse_mode":               "MarkdownV2",
                "disable_web_page_preview": True,
            }
            # FIX : json.dumps obligatoire pour les boutons
            if buttons:
                payload["reply_markup"] = json.dumps(buttons)

            for attempt in range(3):
                async with session.post(
                    url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        logger.info("[POS] ✅ Alerte Telegram envoyée")
                        return

                    if resp.status == 429:
                        result    = await resp.json()
                        wait      = result.get("parameters", {}).get("retry_after", 5)
                        logger.warning(f"[POS] ⏳ Rate limit, attente {wait}s")
                        # FIX : asyncio importé au niveau module
                        await asyncio.sleep(wait)
                        continue

                    result = await resp.json()
                    logger.error(f"[POS] ❌ Telegram {resp.status}: {result}")
                    return

        except Exception as e:
            logger.error(f"[POS] Exception telegram: {e}")

    def _esc(self, text: str) -> str:
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

    async def _get_current_price(self, address: str) -> float | None:
        try:
            session = await self._get_session()
            url     = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return None
                data      = await resp.json()
                pairs     = data.get("pairs") or []
                sol_pairs = [
                    p for p in pairs
                    if p.get("chainId") == "solana"
                ]
                if not sol_pairs:
                    return None
                pair = max(
                    sol_pairs,
                    key=lambda p: p.get("liquidity", {}).get("usd", 0),
                )
                return float(pair.get("priceUsd", 0) or 0)
        except Exception as e:
            logger.debug(f"[POS] Prix introuvable {address[:8]}: {e}")
            return None

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()