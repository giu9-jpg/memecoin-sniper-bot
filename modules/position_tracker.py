# modules/position_tracker.py — v7.0
# Suivi des positions + alertes TP/SL enrichies

import time
import os
import aiohttp
from utils.logger import logger


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

    # ═══════════════════════════════════════════════════
    # GESTION DES POSITIONS
    # ═══════════════════════════════════════════════════

    def add_position(
        self,
        token_data: dict,
        decision:   dict,
        amount_eur: float
    ):
        """Ajoute une nouvelle position à surveiller."""
        address = token_data.get("address", "")
        if not address:
            return

        tp_levels = decision.get("tp_levels", [])

        self.positions[address] = {
            "address":     address,
            "symbol":      token_data.get("symbol", "???"),
            "name":        token_data.get("name", "Unknown"),
            "price_entry": token_data.get("price_usd", 0),
            "price_high":  token_data.get("price_usd", 0),
            "amount_eur":  amount_eur,
            "remaining":   100,
            "tp_levels":   tp_levels,
            "tp_hit":      [],
            "sl_pct":      decision.get("sl_pct", -30),
            "entry_time":  time.time(),
            "last_check":  time.time(),
            "closed":      False,
            "tier":        decision.get("tier", ""),
            "score":       token_data.get("score", 0),
        }

        logger.info(
            f"[POS] ➕ Position ouverte : "
            f"{token_data.get('symbol')} | "
            f"{amount_eur}€ | "
            f"Entry: ${token_data.get('price_usd', 0):.8f}"
        )

    # ═══════════════════════════════════════════════════
    # VÉRIFICATION DES POSITIONS
    # ═══════════════════════════════════════════════════

    async def check_all_positions(self):
        """Vérifie toutes les positions ouvertes."""
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
                    await self._check_position(
                        address, position, current_price
                    )
            except Exception as e:
                logger.error(f"[POS] Erreur {address[:8]}: {e}")

    async def _check_position(
        self,
        address:       str,
        position:      dict,
        current_price: float
    ):
        """Vérifie TP/SL pour une position."""
        entry = position.get("price_entry", 0)
        if not entry or entry == 0:
            return

        multiplier = current_price / entry
        change_pct = (multiplier - 1) * 100
        sl_pct     = position.get("sl_pct", -30)
        age_min    = (time.time() - position["entry_time"]) / 60

        if current_price > position.get("price_high", 0):
            self.positions[address]["price_high"] = current_price

        symbol = position.get("symbol", "???")

        # ── STOP LOSS ─────────────────────────────────
        if change_pct <= sl_pct and position["remaining"] > 0:
            logger.info(
                f"[POS] 🛑 SL touché {symbol}: "
                f"{change_pct:.1f}% (seuil {sl_pct}%)"
            )
            await self._send_sl_alert(
                position, current_price, change_pct
            )
            self.positions[address]["closed"]    = True
            self.positions[address]["remaining"] = 0
            return

        # ── TAKE PROFITS ──────────────────────────────
        tp_levels = position.get("tp_levels", [])
        tp_hit    = position.get("tp_hit", [])

        for i, tp in enumerate(tp_levels):
            if i in tp_hit:
                continue

            tp_mult = tp.get("multiplier", 999)
            if multiplier >= tp_mult:
                sell_pct = tp.get("sell_pct", 0)
                logger.info(
                    f"[POS] 🎯 TP{i+1} touché {symbol}: "
                    f"x{multiplier:.2f} (cible x{tp_mult})"
                )
                await self._send_tp_alert(
                    position, i + 1, tp, current_price,
                    multiplier, sell_pct
                )
                self.positions[address]["tp_hit"].append(i)
                self.positions[address]["remaining"] -= sell_pct

                if i == len(tp_levels) - 1:
                    self.positions[address]["closed"] = True

        # ── TIMEOUT (7 jours) ─────────────────────────
        if age_min > 10_080:
            self.positions[address]["closed"] = True
            logger.info(
                f"[POS] ⏰ Position fermée (timeout) : {symbol}"
            )

    # ═══════════════════════════════════════════════════
    # ALERTES TELEGRAM
    # ═══════════════════════════════════════════════════

    async def _send_tp_alert(
        self,
        position:      dict,
        tp_num:        int,
        tp_level:      dict,
        current_price: float,
        multiplier:    float,
        sell_pct:      int
    ):
        """Alerte TP enrichie."""
        symbol      = position.get("symbol", "???")
        amount_eur  = position.get("amount_eur", 0)
        entry_price = position.get("price_entry", 0)
        tier        = position.get("tier", "")
        profit_eur  = amount_eur * multiplier - amount_eur
        remaining   = position.get("remaining", 100) - sell_pct

        tier_emoji = {
            "ULTIMATE": "💎",
            "STRONG":   "🔥",
            "GOOD":     "✅",
            "NORMAL":   "📊",
        }.get(tier, "⚪")

        address = position.get("address", "")

        message = (
            f"🎯 *TAKE PROFIT {tp_num} ATTEINT !*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{tier_emoji} *{symbol}* — {tier}\n\n"
            f"✅ *x{multiplier:.2f}* atteint !\n"
            f"💰 *VENDS {sell_pct}% de ta position*\n\n"
            f"📊 *Détails :*\n"
            f"  Prix entrée  : ${entry_price:.8f}\n"
            f"  Prix actuel  : ${current_price:.8f}\n"
            f"  Gain         : *+{(multiplier-1)*100:.0f}%*\n"
            f"  Profit       : *+{profit_eur:.1f}€*\n"
            f"  Reste à hold : {max(remaining, 0)}%\n\n"
            f"⏰ Temps de hold : "
            f"{(time.time()-position['entry_time'])/60:.0f} min"
        )

        buttons = {
            "inline_keyboard": [[
                {
                    "text": f"🚀 Vendre {sell_pct}% sur Photon",
                    "url":  f"https://photon-sol.tinyastro.io/en/lp/{address}"
                }
            ], [
                {
                    "text": "📊 Voir sur DexScreener",
                    "url":  f"https://dexscreener.com/solana/{address}"
                }
            ]]
        }

        await self._send_telegram(message, buttons)

    async def _send_sl_alert(
        self,
        position:      dict,
        current_price: float,
        change_pct:    float
    ):
        """Alerte Stop Loss enrichie."""
        symbol      = position.get("symbol", "???")
        amount_eur  = position.get("amount_eur", 0)
        entry_price = position.get("price_entry", 0)
        loss_eur    = amount_eur * abs(change_pct) / 100
        address     = position.get("address", "")
        price_high  = position.get("price_high", 0)

        if entry_price > 0:
            high_mult = price_high / entry_price
            high_str  = f"x{high_mult:.2f}"
        else:
            high_str  = "N/A"

        message = (
            f"🛑 *STOP LOSS TOUCHÉ !*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *{symbol}*\n\n"
            f"❌ *VENDS TOUT MAINTENANT*\n\n"
            f"📊 *Détails :*\n"
            f"  Prix entrée  : ${entry_price:.8f}\n"
            f"  Prix actuel  : ${current_price:.8f}\n"
            f"  Baisse       : *{change_pct:.1f}%*\n"
            f"  Perte max    : *-{loss_eur:.1f}€*\n"
            f"  Plus haut    : {high_str}\n\n"
            f"⏰ Temps de hold : "
            f"{(time.time()-position['entry_time'])/60:.0f} min\n\n"
            f"💡 *Ne laisse pas courir les pertes !*"
        )

        buttons = {
            "inline_keyboard": [[
                {
                    "text": "🛑 VENDRE TOUT sur Photon",
                    "url":  f"https://photon-sol.tinyastro.io/en/lp/{address}"
                }
            ], [
                {
                    "text": "📊 DexScreener",
                    "url":  f"https://dexscreener.com/solana/{address}"
                }
            ]]
        }

        await self._send_telegram(message, buttons)

    async def _send_telegram(
        self, message: str, buttons: dict = None
    ):
        """Envoie un message Telegram."""
        if not self.bot_token or not self.chat_id:
            return
        try:
            session = await self._get_session()
            url     = (
                f"https://api.telegram.org/bot"
                f"{self.bot_token}/sendMessage"
            )
            payload = {
                "chat_id":                  self.chat_id,
                "text":                     message,
                "parse_mode":               "Markdown",
                "disable_web_page_preview": True,
            }
            if buttons:
                payload["reply_markup"] = buttons

            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    logger.info("[POS] ✅ Alerte Telegram envoyée")
                else:
                    result = await resp.json()
                    logger.error(f"[POS] ❌ Telegram: {result}")

        except Exception as e:
            logger.error(f"[POS] Exception telegram: {e}")

    # ═══════════════════════════════════════════════════
    # PRIX ACTUEL
    # ═══════════════════════════════════════════════════

    async def _get_current_price(
        self, address: str
    ) -> float | None:
        """Récupère le prix actuel depuis DexScreener."""
        try:
            session = await self._get_session()
            url = (
                f"https://api.dexscreener.com/latest/dex/tokens/"
                f"{address}"
            )
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return None
                data  = await resp.json()
                pairs = data.get("pairs") or []
                sol_pairs = [
                    p for p in pairs
                    if p.get("chainId") == "solana"
                ]
                if not sol_pairs:
                    return None
                pair = max(
                    sol_pairs,
                    key=lambda p: p.get("liquidity", {}).get("usd", 0)
                )
                return float(pair.get("priceUsd", 0) or 0)
        except Exception as e:
            logger.debug(f"[POS] Prix introuvable {address[:8]}: {e}")
            return None

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()