# modules/token_analyzer.py — v9.2 CALIBRÉ
# ═══════════════════════════════════════════════
# v9.2 :
# + LIMITE les bonus volume/momentum
#   (vol x182 ne donne plus 10/10 automatiquement)
# + PÉNALISE fortement liq $0 dans le score
# + PÉNALISE top holder concentré dans le score
# + PÉNALISE 0 holders dans le score
# + Score reflète maintenant la QUALITÉ, pas juste le pump
# + Plafond de bonus volume à +2.0 max (était illimité)
# + Plafond momentum à +2.0 max
# ═══════════════════════════════════════════════

import aiohttp
import asyncio
import time
from utils.logger import logger
from modules.smart_signals import SmartSignalDetector

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"
RUGCHECK_URL    = "https://api.rugcheck.xyz/v1/tokens/{address}/report/summary"


class TokenAnalyzer:

    def __init__(
        self,
        alpha_tracker=None,
        early_detector=None,
        whale_inflow=None,
    ):
        self.session        = None
        self.smart_detector = SmartSignalDetector()
        self.alpha_tracker  = alpha_tracker
        self.early_detector = early_detector
        self.whale_inflow   = whale_inflow

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def analyze_token(self, token_address: str) -> dict | None:

        dex_data, rug_data = await asyncio.gather(
            self._get_dexscreener_data(token_address),
            self._get_rugcheck_data(token_address),
            return_exceptions=True,
        )

        if isinstance(dex_data, Exception) or not dex_data:
            return None
        if isinstance(rug_data, Exception):
            rug_data = {}

        liquidity        = dex_data.get("liquidity_usd", 0)
        volume_24h       = dex_data.get("volume_24h", 0)
        volume_6h        = dex_data.get("volume_6h", 0)
        volume_1h        = dex_data.get("volume_1h", 0)
        volume_5m        = dex_data.get("volume_5m", 0)
        market_cap       = dex_data.get("market_cap", 0)
        price            = dex_data.get("price_usd", 0)
        price_change_5m  = dex_data.get("price_change_5m", 0)
        price_change_1h  = dex_data.get("price_change_1h", 0)
        price_change_6h  = dex_data.get("price_change_6h", 0)
        price_change_24h = dex_data.get("price_change_24h", 0)
        txns_5m          = dex_data.get("txns_5m", {})
        txns_1h          = dex_data.get("txns_1h", {})
        age_minutes      = dex_data.get("age_minutes", 9999)
        holders          = dex_data.get("holders", 0)

        mint_renounced = rug_data.get("mint_renounced", False)
        lp_locked      = rug_data.get("lp_locked", False)
        freeze_auth    = rug_data.get("freeze_authority", False)
        top10_pct      = rug_data.get("top_10_holders_pct", 0)
        is_honeypot    = rug_data.get("is_honeypot", False)

        # ════════════════════════════════════════
        # SCORE DE BASE : 5.0
        # Objectif : mesurer la QUALITÉ, pas juste le pump
        # ════════════════════════════════════════
        score   = 5.0
        reasons = []

        # ── SÉCURITÉ (forte influence négative) ──
        if is_honeypot:
            score -= 6.0
            reasons.append("🚨 HONEYPOT DÉTECTÉ")
        if freeze_auth:
            score -= 3.0
            reasons.append("🔴 Freeze authority active")
        if top10_pct > 80:
            score -= 3.0
            reasons.append(f"🔴 Top 10 holders : {top10_pct:.0f}%")
        elif top10_pct > 50:
            score -= 2.0
            reasons.append(f"🟡 Top 10 : {top10_pct:.0f}%")
        elif top10_pct > 35:
            score -= 1.0
            reasons.append(f"⚠️ Top 10 : {top10_pct:.0f}%")

        if not mint_renounced:
            score -= 1.5
            reasons.append("🔴 Mint NON renoncé")
        else:
            score += 0.5
            reasons.append("✅ Mint renoncé")
        if lp_locked:
            score += 0.5
            reasons.append("✅ Liquidité lockée")

        # ── LIQUIDITÉ (très important) ─────────────
        # v9.2 : liq $0 pénalisée directement dans le score
        if liquidity == 0:
            score -= 2.0
            reasons.append("🔴 Liquidité $0 (bonding curve)")
        elif liquidity < 5_000:
            score -= 2.5
            reasons.append(f"🔴 Liq très faible : ${liquidity:,.0f}")
        elif liquidity < 10_000:
            score -= 1.0
            reasons.append(f"⚠️ Liq faible : ${liquidity:,.0f}")
        elif liquidity < 20_000:
            score += 0.3
        elif liquidity > 50_000:
            score += 1.0
            reasons.append(f"✅ Bonne liq : ${liquidity:,.0f}")
        elif liquidity > 100_000:
            score += 1.5
            reasons.append(f"✅ Liq solide : ${liquidity:,.0f}")

        # ── MARKET CAP ──────────────────────────
        if market_cap < 50_000 and market_cap > 0:
            score += 1.5
            reasons.append(f"🔥 MC ultra low : ${market_cap:,.0f}")
        elif market_cap < 200_000 and market_cap > 0:
            score += 1.0
            reasons.append(f"💎 MC très bas : ${market_cap:,.0f}")
        elif market_cap < 500_000 and market_cap > 0:
            score += 0.5
            reasons.append(f"✅ MC bas : ${market_cap:,.0f}")
        elif market_cap > 10_000_000:
            score -= 2.0
            reasons.append("🔴 MC trop élevé")

        # ── VOLUME ACCELERATION (PLAFONNÉ à +2.0) ──
        # v9.2 : était illimité, causait des 10/10 automatiques
        vol_acceleration = self._calc_volume_acceleration(
            volume_5m, volume_1h, volume_6h, volume_24h
        )
        if vol_acceleration >= 5.0:
            score += 2.0   # PLAFOND — était +2.5 sans limite
            reasons.append(f"🚀 Volume EXPLOSION x{vol_acceleration:.1f}")
        elif vol_acceleration >= 3.0:
            score += 1.5
            reasons.append(f"📈 Volume fort x{vol_acceleration:.1f}")
        elif vol_acceleration >= 2.0:
            score += 1.0
            reasons.append(f"📊 Volume hausse x{vol_acceleration:.1f}")
        elif vol_acceleration < 0.5 and volume_24h > 0:
            score -= 0.5
            reasons.append("📉 Volume en baisse")

        # ── BUY/SELL RATIO ────────────────────────
        buys_5m  = txns_5m.get("buys",  0)
        sells_5m = txns_5m.get("sells", 1)
        buys_1h  = txns_1h.get("buys",  0)
        sells_1h = txns_1h.get("sells", 1)
        ratio_5m = buys_5m  / max(sells_5m,  1)
        ratio_1h = buys_1h  / max(sells_1h,  1)

        if ratio_5m >= 3 and ratio_1h >= 2:
            score += 1.5   # était +2.5
            reasons.append(f"🟢 Pression FORTE 5m={ratio_5m:.1f}x")
        elif ratio_5m >= 3:
            score += 1.0   # était +1.5
            reasons.append(f"🟢 Fort buy 5m : {ratio_5m:.1f}x")
        elif ratio_1h >= 2:
            score += 0.5   # était +1.0
            reasons.append(f"🟢 Bon buy 1h : {ratio_1h:.1f}x")
        elif ratio_5m < 0.5:
            score -= 1.0
            reasons.append(f"🔴 Vente : {ratio_5m:.1f}x")

        # ── MOMENTUM (PLAFONNÉ à +2.0) ─────────────
        # v9.2 : momentum seul ne peut plus exploser le score
        momentum_signal = self._detect_price_momentum(
            price_change_5m, price_change_1h,
            price_change_6h, price_change_24h,
        )
        if momentum_signal == "EARLY_PUMP":
            score += 1.5   # était +2.5
            reasons.append("🚀 EARLY PUMP")
        elif momentum_signal == "BREAKOUT":
            score += 1.0   # était +1.5
            reasons.append("📈 BREAKOUT")
        elif momentum_signal == "ACCUMULATION":
            score += 1.5   # était +2.0
            reasons.append("💎 ACCUMULATION détectée")
        elif momentum_signal == "TROP_TARD":
            score -= 2.0
            reasons.append("🔴 TROP TARD")
        elif momentum_signal == "DUMP":
            score -= 1.5
            reasons.append("🔴 DUMP")

        # ── MULTI-TIMEFRAME (PLAFONNÉ à +1.5) ──────
        mtf_bonus, mtf_signal = self._analyze_multi_timeframe(
            price_change_5m, price_change_1h,
            price_change_6h, price_change_24h,
        )
        # Plafonne le bonus MTF
        mtf_bonus = max(-2.0, min(1.5, mtf_bonus))
        if mtf_bonus != 0:
            score += mtf_bonus
            if mtf_signal:
                reasons.append(mtf_signal)

        # ── AGE ─────────────────────────────────────
        # v9.2 : bonus réduits, age seul ne doit pas booster
        if age_minutes < 5:
            score += 0.5   # était +1.5
            reasons.append(f"⚡ ULTRA EARLY : {age_minutes:.0f}min")
        elif age_minutes < 15:
            score += 0.8   # était +2.0
            reasons.append(f"🔥 Très early : {age_minutes:.0f}min")
        elif age_minutes < 30:
            score += 0.5   # était +1.5
            reasons.append(f"✅ Early : {age_minutes:.0f}min")
        elif age_minutes < 60:
            score += 0.2
        elif age_minutes > 1440:
            score -= 1.0
            reasons.append(f"📅 Vieux : {age_minutes/1440:.1f}j")

        # ── HOLDERS ──────────────────────────────────
        # v9.2 : 0 holders = grosse pénalité
        if holders == 0:
            score -= 1.5
            reasons.append("⚠️ 0 holders (DexScreener)")
        elif holders < 20:
            score -= 0.5
            reasons.append(f"⚠️ Peu holders : {holders}")
        elif holders > 100:
            score += 0.5
            reasons.append(f"✅ {holders} holders")
        elif holders > 500:
            score += 1.0
            reasons.append(f"🔥 {holders} holders")

        # ── SOCIALS ────────────────────────────────
        if dex_data.get("has_socials"):
            score += 0.5
            reasons.append("✅ Socials")
        else:
            score -= 0.3
            reasons.append("⚠️ Pas de socials")

        # Plafond intermédiaire avant smart signals
        score = max(0.0, min(10.0, score))

        # ════════════════════════════════════════
        # SMART SIGNALS (plafonné à +1.5)
        # v9.2 : ne peut plus exploser le score final
        # ════════════════════════════════════════
        current_data = {
            "price_usd":        price,
            "market_cap":       market_cap,
            "liquidity":        liquidity,
            "volume_1h":        volume_1h,
            "volume_5m":        volume_5m,
            "holders":          holders,
            "score":            score,
            "txns_5m":          txns_5m,
            "txns_1h":          txns_1h,
            "price_change_1h":  price_change_1h,
            "vol_acceleration": vol_acceleration,
            "ratio_buy_5m":     ratio_5m,
        }

        smart_result  = await self.smart_detector.analyze_all_signals(
            token_address, current_data
        )
        smart_bonus   = smart_result.get("total_bonus", 0)
        smart_signals = smart_result.get("signals", [])
        smart_count   = smart_result.get("signal_count", 0)
        has_critical  = smart_result.get("has_critical", False)

        # v9.2 : plafonne le bonus smart signals
        smart_bonus = min(smart_bonus, 1.5)
        score += smart_bonus
        for sig in smart_signals:
            reasons.append(
                f"{sig.get('emoji', '⚡')} {sig.get('message', '')}"
            )

        # ════════════════════════════════════════
        # ALPHA WALLETS (bonus conservé)
        # ════════════════════════════════════════
        alpha_signal = None
        if self.alpha_tracker:
            alpha_signal = self.alpha_tracker.get_alpha_signal(
                token_address
            )
            if alpha_signal["has_alpha"]:
                score += alpha_signal["bonus"]
                reasons.append(f"🐋 {alpha_signal['message']}")

        # ════════════════════════════════════════
        # EARLY DETECTOR (bonus conservé)
        # ════════════════════════════════════════
        early_signal = None
        if self.early_detector and age_minutes < 5:
            early_signal = await self.early_detector.analyze_early_token(
                token_address,
                {
                    "name":   dex_data.get("name"),
                    "symbol": dex_data.get("symbol"),
                },
            )
            if early_signal.get("bonus", 0) > 0:
                score += early_signal["bonus"]
                reasons.append(early_signal["message"])

        # ════════════════════════════════════════
        # WHALE INFLOW (bonus conservé)
        # ════════════════════════════════════════
        whale_inflow_signal = None
        if self.whale_inflow:
            whale_inflow_signal = await self.whale_inflow.check_token_inflows(
                token_address
            )
            if whale_inflow_signal.get("bonus", 0) > 0:
                score += whale_inflow_signal["bonus"]
                reasons.append(whale_inflow_signal["message"])

        # Plafond final
        score = max(0.0, min(10.0, score))

        signal_type = self._get_signal_type(
            score, momentum_signal, vol_acceleration,
            ratio_5m, ratio_1h, market_cap,
        )

        return {
            "address":            token_address,
            "name":               dex_data.get("name", "Unknown"),
            "symbol":             dex_data.get("symbol", "???"),
            "price":              price,
            "price_usd":          price,
            "market_cap":         market_cap,
            "liquidity":          liquidity,
            "volume_24h":         volume_24h,
            "volume_1h":          volume_1h,
            "volume_5m":          volume_5m,
            "price_change_5m":    price_change_5m,
            "price_change_1h":    price_change_1h,
            "price_change_6h":    price_change_6h,
            "price_change_24h":   price_change_24h,
            "holders":            holders,
            "age_minutes":        age_minutes,
            "mint_renounced":     mint_renounced,
            "lp_locked":          lp_locked,
            "freeze_auth":        freeze_auth,
            "top_10_holders_pct": top10_pct,
            "is_honeypot":        is_honeypot,
            "vol_acceleration":   vol_acceleration,
            "ratio_buy_5m":       ratio_5m,
            "ratio_buy_1h":       ratio_1h,
            "momentum_signal":    momentum_signal,
            "signal_type":        signal_type,
            "has_socials":        dex_data.get("has_socials", False),
            "score":              round(score, 1),
            "score_reasons":      reasons,
            "whale_count":        0,
            "smart_signals":      smart_signals,
            "smart_count":        smart_count,
            "has_critical":       has_critical,
            "smart_bonus":        round(smart_bonus, 1),
            "alpha_signal":       alpha_signal,
            "alpha_wallets":      (
                alpha_signal["wallet_count"] if alpha_signal else 0
            ),
            "early_signal":       early_signal,
            "whale_inflow":       whale_inflow_signal,
            "whale_inflow_count": (
                whale_inflow_signal.get("whale_count", 0)
                if whale_inflow_signal else 0
            ),
            "giga_whale_count":   (
                whale_inflow_signal.get("giga_count", 0)
                if whale_inflow_signal else 0
            ),
        }

    def _calc_volume_acceleration(
        self, vol_5m, vol_1h, vol_6h, vol_24h
    ) -> float:
        try:
            avg_hourly = vol_24h / 24 if vol_24h > 0 else 0
            if avg_hourly == 0:
                return 1.0
            recent_rate  = vol_1h / avg_hourly if vol_1h > 0 else 0
            rate_5m      = (vol_5m * 12) / avg_hourly if vol_5m > 0 else 0
            acceleration = (rate_5m * 0.6) + (recent_rate * 0.4)
            return round(acceleration, 2)
        except Exception:
            return 1.0

    def _detect_price_momentum(
        self, change_5m, change_1h, change_6h, change_24h
    ) -> str:
        if change_24h > 2000:
            return "TROP_TARD"
        if change_1h < -20 and change_5m < -10:
            return "DUMP"
        if (
            change_5m > 5 and change_1h > 10
            and change_6h > 0 and change_24h < 500
        ):
            return "EARLY_PUMP"
        if change_5m > 10 and change_1h > 5:
            return "BREAKOUT"
        if (
            abs(change_1h) < 5
            and abs(change_6h) < 10
            and change_24h < 100
        ):
            return "ACCUMULATION"
        return "NEUTRE"

    def _analyze_multi_timeframe(
        self, change_5m, change_1h, change_6h, change_24h
    ) -> tuple[float, str]:
        if (
            abs(change_24h) < 30 and abs(change_6h) < 20
            and change_1h > 15 and change_5m > 5
        ):
            return 1.5, "🎯 BREAKOUT depuis consolidation"
        if (
            0 < change_24h < 100 and 0 < change_6h < 50
            and 0 < change_1h < 30 and change_5m > 0
        ):
            return 1.0, "💎 Accumulation multi-TF alignée"
        if (
            change_5m > 10 and change_1h > 20
            and change_6h > 30 and change_24h < 500
        ):
            return 1.5, "🚀 Momentum ALIGNÉ tous TF"
        if change_24h < -40 and change_1h > 10:
            return -1.5, "🔴 Dead cat bounce détecté"
        if change_24h > 500 and change_1h < 0:
            return -1.0, "🔴 Pump épuisé"
        if 0 < change_5m < 20 and change_1h > 5 and change_24h < 200:
            return 0.5, "📈 Early momentum"
        return 0.0, ""

    def _analyze_holders(
        self, holders, age_minutes, market_cap
    ) -> str:
        if holders == 0:
            return "INCONNU"
        holder_rate = holders / age_minutes if age_minutes > 0 else holders
        if holder_rate > 5:
            return "VIRAL"
        elif holder_rate > 1:
            return "BON"
        elif holders < 50:
            return "FAIBLE"
        return "NORMAL"

    def _get_signal_type(
        self, score, momentum, vol_accel, ratio_5m, ratio_1h, market_cap
    ) -> str:
        if score >= 8.5:
            return "GEM_ULTIME"
        elif score >= 7.5:
            if momentum == "ACCUMULATION":
                return "ACCUMULATION_FORTE"
            elif momentum == "EARLY_PUMP":
                return "EARLY_PUMP"
            return "GEM_FORTE"
        elif score >= 6.5:
            if vol_accel >= 2.0:
                return "VOLUME_EXPLOSION"
            elif ratio_5m >= 3:
                return "PRESSION_ACHETEUSE"
            return "BON_TOKEN"
        elif score >= 5.0:
            return "A_SURVEILLER"
        return "RISQUE"

    async def _get_dexscreener_data(self, address: str) -> dict:
        try:
            session = await self._get_session()
            url     = DEXSCREENER_URL.format(address=address)
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()

            pairs     = data.get("pairs") or []
            sol_pairs = [
                p for p in pairs
                if p.get("chainId") == "solana"
                and not p.get("baseToken", {})
                          .get("address", "")
                          .startswith("0x")
            ]
            if not sol_pairs:
                return {}

            pair = max(
                sol_pairs,
                key=lambda p: p.get("liquidity", {}).get("usd", 0),
            )

            created_at  = (
                pair.get("pairCreatedAt", int(time.time() * 1000)) / 1000
            )
            age_minutes = (time.time() - created_at) / 60
            info        = pair.get("info", {})
            has_socials = bool(
                info.get("socials", []) or info.get("websites", [])
            )
            volume  = pair.get("volume",      {})
            txns    = pair.get("txns",        {})
            changes = pair.get("priceChange", {})

            return {
                "name":             pair.get("baseToken", {}).get("name",   "Unknown"),
                "symbol":           pair.get("baseToken", {}).get("symbol", "???"),
                "price_usd":        float(pair.get("priceUsd", 0) or 0),
                "market_cap":       pair.get("marketCap",  0) or 0,
                "liquidity_usd":    pair.get("liquidity",  {}).get("usd", 0),
                "volume_24h":       volume.get("h24", 0),
                "volume_6h":        volume.get("h6",  0),
                "volume_1h":        volume.get("h1",  0),
                "volume_5m":        volume.get("m5",  0),
                "price_change_5m":  changes.get("m5",  0),
                "price_change_1h":  changes.get("h1",  0),
                "price_change_6h":  changes.get("h6",  0),
                "price_change_24h": changes.get("h24", 0),
                "txns_5m":          txns.get("m5", {}),
                "txns_1h":          txns.get("h1", {}),
                "age_minutes":      age_minutes,
                "holders":          pair.get("holders", 0),
                "has_socials":      has_socials,
                "deployer":         pair.get("deployer", ""),
            }

        except Exception as e:
            logger.debug(f"[DEXSCREENER] Erreur {address[:8]}: {e}")
            return {}

    async def _get_rugcheck_data(self, address: str) -> dict:
        try:
            session = await self._get_session()
            url     = RUGCHECK_URL.format(address=address)
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status != 200:
                    return {}
                return await resp.json()
        except Exception as e:
            logger.debug(f"[RUGCHECK] Erreur {address[:8]}: {e}")
            return {}

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()