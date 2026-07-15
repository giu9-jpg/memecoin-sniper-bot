# modules/position_tracker.py — v5.0
# Suit les positions ouvertes et alerte sur TP/SL

import time
import json
import os
import aiohttp
from utils.logger import logger

POSITIONS_FILE = "positions.json"
DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"


class PositionTracker:

    def __init__(self, alert_sender=None):
        self.positions    = {}
        self.session      = None
        self.alert_sender = alert_sender
        self._load()

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # PERSISTANCE
    # ═══════════════════════════════════════════════════
    def _load(self):
        if os.path.exists(POSITIONS_FILE):
            try:
                with open(POSITIONS_FILE, "r") as f:
                    self.positions = json.load(f)
                logger.info(f"[POSITIONS] {len(self.positions)} chargée(s)")
            except Exception as e:
                logger.error(f"[POSITIONS] Erreur load: {e}")

    def _save(self):
        try:
            with open(POSITIONS_FILE, "w") as f:
                json.dump(self.positions, f, indent=2)
        except Exception as e:
            logger.error(f"[POSITIONS] Erreur save: {e}")

    # ═══════════════════════════════════════════════════
    # AJOUTER UNE POSITION
    # ═══════════════════════════════════════════════════
    def add_position(self, token_data: dict, decision: dict, amount_eur: float):
        address = token_data.get("address", "")
        if not address:
            return

        self.positions[address] = {
            "address":       address,
            "name":          token_data.get("name", "Unknown"),
            "symbol":        token_data.get("symbol", "???"),
            "entry_price":   token_data.get("price_usd", 0),
            "entry_time":    time.time(),
            "amount_eur":    amount_eur,
            "tp_levels":     decision.get("tp_levels", []),
            "sl_pct":        decision.get("sl_pct", 0),
            "tp_hit":        [],   # TP déjà atteints
            "sl_hit":        False,
            "closed":        False,
        }
        self._save()
        logger.info(f"[POSITION] Ajouté: {token_data.get('symbol')} @ ${token_data.get('price_usd')}")

    # ═══════════════════════════════════════════════════
    # RETIRER UNE POSITION
    # ═══════════════════════════════════════════════════
    def remove_position(self, address: str):
        if address in self.positions:
            del self.positions[address]
            self._save()

    # ═══════════════════════════════════════════════════
    # VÉRIFIER LES POSITIONS (boucle principale)
    # ═══════════════════════════════════════════════════
    async def check_all_positions(self):
        """Vérifie chaque position et alerte si TP/SL atteint."""
        for address in list(self.positions.keys()):
            pos = self.positions[address]
            if pos.get("closed"):
                continue

            try:
                current_price = await self._get_current_price(address)
                if current_price == 0:
                    continue

                entry     = pos["entry_price"]
                if entry == 0:
                    continue

                mult      = current_price / entry
                change_pct = (mult - 1) * 100

                # Check SL
                if not pos["sl_hit"] and change_pct <= pos["sl_pct"]:
                    await self._send_sl_alert(pos, current_price, change_pct)
                    pos["sl_hit"] = True
                    pos["closed"] = True
                    self._save()
                    continue

                # Check TP
                for i, tp in enumerate(pos["tp_levels"]):
                    tp_mult = tp["multiplier"]
                    if i in pos["tp_hit"]:
                        continue
                    if mult >= tp_mult:
                        await self._send_tp_alert(pos, i+1, tp, current_price, mult)
                        pos["tp_hit"].append(i)
                        self._save()
                        # Si dernier TP → clôturer
                        if len(pos["tp_hit"]) == len(pos["tp_levels"]):
                            pos["closed"] = True
                            self._save()

            except Exception as e:
                logger.error(f"[POSITION] Erreur {address[:8]}: {e}")

    # ═══════════════════════════════════════════════════
    # PRIX ACTUEL
    # ═══════════════════════════════════════════════════
    async def _get_current_price(self, address: str) -> float:
        try:
            session = await self._get_session()
            url     = DEXSCREENER_URL.format(address=address)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return 0
                data = await resp.json()
            pairs = data.get("pairs") or []
            sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
            if not sol_pairs:
                return 0
            pair = max(sol_pairs, key=lambda p: p.get("liquidity", {}).get("usd", 0))
            return float(pair.get("priceUsd", 0) or 0)
        except Exception:
            return 0

    # ═══════════════════════════════════════════════════
    # ALERTES TP / SL
    # ═══════════════════════════════════════════════════
    async def _send_tp_alert(self, pos, tp_num, tp, price, mult):
        if not self.alert_sender:
            return
        symbol   = pos["symbol"]
        sell_pct = tp["sell_pct"]
        amount   = pos["amount_eur"]
        gain_eur = amount * (mult - 1) * (sell_pct / 100)

        message = (
            f"🎯 *TAKE PROFIT {tp_num} ATTEINT !*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *{symbol}*\n\n"
            f"📈 Prix actuel : *${price:.6f}*\n"
            f"🎯 Multiplicateur : *x{mult:.2f}*\n\n"
            f"💰 *VENDS {sell_pct}% MAINTENANT !*\n"
            f"💵 Gain estimé : +{gain_eur:.2f}€\n\n"
            f"📍 `{pos['address']}`"
        )

        buttons = {
            "inline_keyboard": [[
                {"text": "🚀 Vendre sur Photon",
                 "url":  f"https://photon-sol.tinyastro.io/en/lp/{pos['address']}"}
            ]]
        }
        await self.alert_sender._send_telegram(message, buttons)
        logger.info(f"[POSITION] TP{tp_num} alerte envoyée pour {symbol}")

    async def _send_sl_alert(self, pos, price, change_pct):
        if not self.alert_sender:
            return
        symbol   = pos["symbol"]
        loss_eur = pos["amount_eur"] * (change_pct / 100)

        message = (
            f"🛑 *STOP LOSS DÉCLENCHÉ !*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 *{symbol}*\n\n"
            f"📉 Prix actuel : *${price:.6f}*\n"
            f"🔴 Variation : *{change_pct:.1f}%*\n\n"
            f"⚠️ *VENDS TOUT MAINTENANT !*\n"
            f"💸 Perte estimée : {loss_eur:.2f}€\n\n"
            f"📍 `{pos['address']}`"
        )

        buttons = {
            "inline_keyboard": [[
                {"text": "🚀 Vendre sur Photon",
                 "url":  f"https://photon-sol.tinyastro.io/en/lp/{pos['address']}"}
            ]]
        }
        await self.alert_sender._send_telegram(message, buttons)
        logger.info(f"[POSITION] SL alerte envoyée pour {symbol}")

    # ═══════════════════════════════════════════════════
    # RÉSUMÉ
    # ═══════════════════════════════════════════════════
    def get_summary(self) -> str:
        active = [p for p in self.positions.values() if not p.get("closed")]
        if not active:
            return "Aucune position active"

        lines = [f"📊 *{len(active)} POSITIONS ACTIVES*", ""]
        for pos in active:
            symbol = pos["symbol"]
            tp_hit = len(pos["tp_hit"])
            total  = len(pos["tp_levels"])
            lines.append(f"🪙 {symbol} — TP {tp_hit}/{total}")
        return "\n".join(lines)

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()