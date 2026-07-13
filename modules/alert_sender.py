# modules/alert_sender.py — v3.0
# Alertes catégorisées selon le type de signal

import os
import json
import time
import asyncio
import aiohttp
from utils.logger import logger

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
BASE_URL           = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

DEXSCREENER_URL = "https://dexscreener.com/solana/{address}"
BIRDEYE_URL     = "https://birdeye.so/token/{address}?chain=solana"
RUGCHECK_URL    = "https://rugcheck.xyz/tokens/{address}"
SOLSCAN_URL     = "https://solscan.io/token/{address}"
TROJAN_URL      = "https://t.me/TrojanOnSolana_bot?start=snipe_{address}"


class AlertSender:

    def __init__(self):
        self.session = None

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ── DÉMARRAGE ────────────────────────────────────────
    async def send_startup_message(self):
        text = (
            "🤖 *MemeSniper v3\\.0 démarré \\!*\n\n"
            "✅ WebSocket PumpPortal actif\n"
            "✅ Détection momentum pre\\-pump\n"
            "✅ 7 signaux analysés par token\n"
            "✅ Whale Tracker actif\n\n"
            "📡 _En chasse\\.\\.\\._"
        )
        await self._send_message(text)

    # ── ALERTE PRINCIPALE ─────────────────────────────────
    async def send_token_alert(self, analysis: dict):
        text    = self._build_message(analysis)
        buttons = self._build_buttons(analysis)
        await self._send_message(text, reply_markup=buttons)

    # ── MESSAGE ───────────────────────────────────────────
    def _build_message(self, a: dict) -> str:
        score       = a.get("score", 0)
        signal_type = a.get("signal_type", "A_SURVEILLER")
        address     = a.get("address", "")

        # ── Header selon le signal ──────────────────────
        headers = {
            "GEM_ULTIME":         "💎 *GEM ULTIME DÉTECTÉE*",
            "ACCUMULATION_FORTE": "🤫 *ACCUMULATION SILENCIEUSE*",
            "EARLY_PUMP":         "🚀 *EARLY PUMP DÉTECTÉ*",
            "VOLUME_EXPLOSION":   "💥 *EXPLOSION DE VOLUME*",
            "PRESSION_ACHETEUSE": "🟢 *FORTE PRESSION ACHETEUSE*",
            "GEM_FORTE":          "💎 *GEM POTENTIELLE*",
            "BON_TOKEN":          "✅ *BON TOKEN*",
            "A_SURVEILLER":       "👀 *TOKEN À SURVEILLER*",
        }
        header = headers.get(signal_type, "📊 *TOKEN DÉTECTÉ*")

        # ── Barre de score ───────────────────────────────
        score_bar = "█" * int(score) + "░" * (10 - int(score))

        # ── Conseil selon le signal ──────────────────────
        conseils = {
            "GEM_ULTIME":
                "🎯 _Tous les signaux au vert \\— Forte conviction_",
            "ACCUMULATION_FORTE":
                "🤫 _Accumulation avant pump \\— Fenêtre rare_",
            "EARLY_PUMP":
                "⚡ _Momentum haussier \\— Agis vite_",
            "VOLUME_EXPLOSION":
                "💥 _Volume x{:.0f} \\— Intérêt croissant_".format(
                    a.get("vol_acceleration", 1)
                ),
            "PRESSION_ACHETEUSE":
                "🟢 _Ratio buy/sell {:.1f}x \\— Accumulateurs actifs_".format(
                    a.get("ratio_buy_5m", 0)
                ),
            "GEM_FORTE":
                "💎 _Bons fondamentaux \\— Position possible_",
            "BON_TOKEN":
                "✅ _Token correct \\— Petite position_",
            "A_SURVEILLER":
                "👀 _Surveille sans acheter pour l'instant_",
        }
        conseil = conseils.get(signal_type, "")

        # ── Métriques ────────────────────────────────────
        age = a.get("age_minutes", 0)
        if age < 60:
            age_str = f"{age:.0f} min"
        elif age < 1440:
            age_str = f"{age/60:.1f}h"
        else:
            age_str = f"{age/1440:.1f}j"

        mc = a.get("market_cap", 0)
        if mc < 1_000_000:
            mc_str = f"${mc/1000:.0f}K"
        else:
            mc_str = f"${mc/1_000_000:.1f}M"

        # Variations de prix
        c5m  = a.get("price_change_5m", 0)
        c1h  = a.get("price_change_1h", 0)
        c24h = a.get("price_change_24h", 0)

        def fmt_pct(v):
            sign = "\\+" if v >= 0 else ""
            return f"{sign}{v:.1f}%"

        # Sécurité
        mint   = "✅" if a.get("mint_renounced") else "❌"
        freeze = "✅" if not a.get("freeze_auth") else "⚠️"
        lp     = "✅" if a.get("lp_locked")       else "❓"
        top10  = a.get("top_10_holders_pct", 0)

        # Baleines
        wc = a.get("whale_count", 0)
        whale_line = (
            f"🐋 *{wc} baleine\\(s\\) détectée\\(s\\) \\!*\n"
            if wc > 0 else ""
        )

        # Raisons (max 4)
        reasons     = a.get("score_reasons", [])
        reasons_str = ""
        if reasons:
            reasons_str = "\n📋 *Signaux détectés :*\n"
            for r in reasons[:4]:
                reasons_str += f"  {self._esc(r)}\n"

        return (
            f"{header}\n\n"
            f"🪙 *{self._esc(a.get('name','?'))}* "
            f"\\(\\${self._esc(a.get('symbol','?'))}\\)\n"
            f"`{address}`\n\n"
            f"📊 *Score : {score_bar} {score:.1f}/10*\n"
            f"{conseil}\n\n"
            f"{whale_line}"
            f"━━━━━━━━━━━━━━━━\n"
            f"💎 Market Cap  : *{mc_str}*\n"
            f"💰 Liquidité   : *${a.get('liquidity',0):,.0f}*\n"
            f"📈 Volume 1h   : *${a.get('volume_1h',0):,.0f}*\n"
            f"⏰ Âge         : *{age_str}*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📉 5m : *{fmt_pct(c5m)}* \\| "
            f"1h : *{fmt_pct(c1h)}* \\| "
            f"24h : *{fmt_pct(c24h)}*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🔒 Mint  : {mint} \\| "
            f"Freeze : {freeze} \\| "
            f"LP : {lp}\n"
            f"👛 Top 10 holders : *{top10:.0f}%*\n"
            f"{reasons_str}\n"
            f"⏰ _{self._timestamp()}_"
        )

    # ── BOUTONS ───────────────────────────────────────────
    def _build_buttons(self, a: dict) -> dict:
        addr = a.get("address", "")
        return {
            "inline_keyboard": [
                [
                    {"text": "🛒 Buy 10$ — Trojan",
                     "url": TROJAN_URL.format(address=addr)},
                    {"text": "🛒 Buy 20$ — Trojan",
                     "url": TROJAN_URL.format(address=addr)},
                ],
                [
                    {"text": "📊 DexScreener",
                     "url": DEXSCREENER_URL.format(address=addr)},
                    {"text": "🦅 Birdeye",
                     "url": BIRDEYE_URL.format(address=addr)},
                ],
                [
                    {"text": "🔍 RugCheck",
                     "url": RUGCHECK_URL.format(address=addr)},
                    {"text": "📋 Solscan",
                     "url": SOLSCAN_URL.format(address=addr)},
                ],
            ]
        }

    # ── ALERTE BALEINE ────────────────────────────────────
    async def send_whale_alert(self, whale_data: dict):
        addr   = whale_data.get("token_address", "")
        action = whale_data.get("action", "buy")
        emoji  = "🐋🟢" if action == "buy" else "🐋🔴"
        verb   = "ACHÈTE" if action == "buy" else "VEND"

        text = (
            f"{emoji} *MOUVEMENT BALEINE*\n\n"
            f"👛 *{self._esc(whale_data.get('whale_label','?'))}*\n"
            f"📌 *{verb}* "
            f"\\${self._esc(whale_data.get('token_symbol','?'))}\n"
            f"💵 Montant : *${whale_data.get('amount_usd',0):,.0f}*\n\n"
            f"`{addr}`\n\n"
            f"⚡ _Signal fort \\— Agis vite_"
        )

        buttons = None
        if addr:
            buttons = {"inline_keyboard": [[
                {"text": "🛒 Buy — Trojan",
                 "url": TROJAN_URL.format(address=addr)},
                {"text": "📊 DexScreener",
                 "url": DEXSCREENER_URL.format(address=addr)},
            ]]}

        await self._send_message(text, reply_markup=buttons)

    # ── COMPATIBILITÉ ANCIEN CODE ─────────────────────────
    def send_simple_message(self, text: str):
        """Compatibilité avec l'ancien code synchrone."""
        import requests
        try:
            clean = text.replace("*", "").replace("_", "")
            requests.post(
                f"{BASE_URL}/sendMessage",
                json={
                    "chat_id":    TELEGRAM_CHAT_ID,
                    "text":       clean,
                    "parse_mode": "Markdown",
                },
                timeout=10
            )
        except Exception as e:
            logger.error(f"[TELEGRAM] send_simple_message: {e}")

    def send_alert(self, data: dict):
        """Compatibilité avec l'ancien code synchrone."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.send_token_alert(data))
            else:
                loop.run_until_complete(self.send_token_alert(data))
        except Exception as e:
            logger.error(f"[TELEGRAM] send_alert: {e}")

    # ── ENVOI HTTP ────────────────────────────────────────
    async def _send_message(
        self, text: str,
        reply_markup: dict = None,
        retries: int = 3
    ):
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            logger.error("[TELEGRAM] Token ou Chat ID manquant !")
            return

        payload = {
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       text,
            "parse_mode": "MarkdownV2",
        }
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        session = await self._get_session()
        for attempt in range(retries):
            try:
                async with session.post(
                    f"{BASE_URL}/sendMessage",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        logger.debug("[TELEGRAM] ✅ Envoyé")
                        return
                    body = await resp.text()
                    logger.warning(
                        f"[TELEGRAM] {resp.status}: {body[:150]}"
                    )
            except Exception as e:
                logger.error(f"[TELEGRAM] Tentative {attempt+1}: {e}")
                await asyncio.sleep(2 ** attempt)

    # ── UTILS ─────────────────────────────────────────────
    @staticmethod
    def _esc(text: str) -> str:
        """Échappe les caractères MarkdownV2."""
        for ch in r"\_*[]()~`>#+-=|{}.!":
            text = str(text).replace(ch, f"\\{ch}")
        return text

    @staticmethod
    def _timestamp() -> str:
        from datetime import datetime
        return datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")