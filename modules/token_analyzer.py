# modules/token_analyzer.py — Score Momentum v3.0
# Détecte les tokens AVANT les bull runs

import aiohttp
import asyncio
import time
import os
from utils.logger import logger

DEXSCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/{address}"
RUGCHECK_URL    = "https://api.rugcheck.xyz/v1/tokens/{address}/report/summary"


class TokenAnalyzer:

    def __init__(self):
        self.session       = None
        self.price_history = {}   # token → historique prix
        self.volume_history = {}  # token → historique volumes

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════════
    # ANALYSE PRINCIPALE
    # ═══════════════════════════════════════════════════════
    async def analyze_token(self, token_address: str) -> dict | None:
        """
        Analyse complète avec détection momentum pre-pump.
        """
        # Récupération données en parallèle
        dex_data, rug_data = await asyncio.gather(
            self._get_dexscreener_data(token_address),
            self._get_rugcheck_data(token_address),
            return_exceptions=True
        )

        if isinstance(dex_data, Exception) or not dex_data:
            return None
        if isinstance(rug_data, Exception):
            rug_data = {}

        # ── Extraction des métriques ─────────────────────
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

        # Sécurité
        mint_renounced = rug_data.get("mint_renounced", False)
        lp_locked      = rug_data.get("lp_locked", False)
        freeze_auth    = rug_data.get("freeze_authority", False)
        top10_pct      = rug_data.get("top_10_holders_pct", 0)
        is_honeypot    = rug_data.get("is_honeypot", False)

        # ── Score de base ────────────────────────────────
        score   = 5.0
        reasons = []

        # ═══════════════════════════════════════════════════
        # 🚨 DISQUALIFICATIONS IMMÉDIATES
        # ═══════════════════════════════════════════════════
        if is_honeypot:
            score -= 5.0
            reasons.append("🚨 HONEYPOT DÉTECTÉ")

        if freeze_auth:
            score -= 2.0
            reasons.append("🔴 Freeze authority active")

        if top10_pct > 80:
            score -= 3.0
            reasons.append(f"🔴 Top 10 holders : {top10_pct:.0f}% DANGER")
        elif top10_pct > 50:
            score -= 2.0
            reasons.append(f"🟡 Top 10 holders : {top10_pct:.0f}%")

        if not mint_renounced:
            score -= 2.0
            reasons.append("🔴 Mint NON renoncé")
        else:
            score += 1.0
            reasons.append("✅ Mint renoncé")

        if lp_locked:
            score += 1.0
            reasons.append("✅ Liquidité lockée")

        # ═══════════════════════════════════════════════════
        # 📊 SIGNAL 1 — MARKET CAP (fenêtre d'opportunité)
        # ═══════════════════════════════════════════════════
        if market_cap < 50_000:
            score += 2.0
            reasons.append(f"🔥 MC ultra low : ${market_cap:,.0f} (x100 possible)")
        elif market_cap < 200_000:
            score += 1.5
            reasons.append(f"💎 MC très bas : ${market_cap:,.0f} (x20 possible)")
        elif market_cap < 500_000:
            score += 1.0
            reasons.append(f"✅ MC bas : ${market_cap:,.0f} (x5 possible)")
        elif market_cap < 2_000_000:
            score += 0.5
            reasons.append(f"🟡 MC moyen : ${market_cap:,.0f}")
        elif market_cap > 10_000_000:
            score -= 2.0
            reasons.append(f"🔴 MC trop élevé : ${market_cap:,.0f} (trop tard)")

        # ═══════════════════════════════════════════════════
        # 📈 SIGNAL 2 — MOMENTUM DU VOLUME (accélération)
        # ═══════════════════════════════════════════════════
        # Calcul de l'accélération du volume
        vol_acceleration = self._calc_volume_acceleration(
            volume_5m, volume_1h, volume_6h, volume_24h
        )

        if vol_acceleration >= 3.0:
            score += 2.5
            reasons.append(
                f"🚀 Volume en EXPLOSION : x{vol_acceleration:.1f} "
                f"(signal pre-pump fort)"
            )
        elif vol_acceleration >= 2.0:
            score += 2.0
            reasons.append(
                f"📈 Volume en forte hausse : x{vol_acceleration:.1f}"
            )
        elif vol_acceleration >= 1.5:
            score += 1.0
            reasons.append(
                f"📊 Volume en hausse : x{vol_acceleration:.1f}"
            )
        elif vol_acceleration < 0.5 and volume_24h > 0:
            score -= 1.0
            reasons.append("📉 Volume en baisse (momentum négatif)")

        # ═══════════════════════════════════════════════════
        # 💹 SIGNAL 3 — RATIO BUY/SELL (pression acheteuse)
        # ═══════════════════════════════════════════════════
        buys_5m  = txns_5m.get("buys", 0)
        sells_5m = txns_5m.get("sells", 1)
        buys_1h  = txns_1h.get("buys", 0)
        sells_1h = txns_1h.get("sells", 1)

        ratio_5m = buys_5m / max(sells_5m, 1)
        ratio_1h = buys_1h / max(sells_1h, 1)

        # Les deux timeframes en même temps = signal fort
        if ratio_5m >= 3 and ratio_1h >= 2:
            score += 2.5
            reasons.append(
                f"🟢 Pression acheteuse FORTE : "
                f"5m={ratio_5m:.1f}x | 1h={ratio_1h:.1f}x"
            )
        elif ratio_5m >= 3:
            score += 1.5
            reasons.append(f"🟢 Fort ratio buy 5m : {ratio_5m:.1f}x")
        elif ratio_1h >= 2:
            score += 1.0
            reasons.append(f"🟢 Bon ratio buy 1h : {ratio_1h:.1f}x")
        elif ratio_5m < 0.5:
            score -= 1.5
            reasons.append(f"🔴 Pression vendeuse : ratio {ratio_5m:.1f}x")

        # ═══════════════════════════════════════════════════
        # 🕐 SIGNAL 4 — MOMENTUM DU PRIX (higher lows)
        # ═══════════════════════════════════════════════════
        momentum_signal = self._detect_price_momentum(
            price_change_5m,
            price_change_1h,
            price_change_6h,
            price_change_24h
        )

        if momentum_signal == "ACCUMULATION":
            score += 2.0
            reasons.append(
                "💎 ACCUMULATION détectée : prix stable + volume monte"
            )
        elif momentum_signal == "EARLY_PUMP":
            score += 2.5
            reasons.append(
                "🚀 EARLY PUMP : momentum haussier sur tous les TF"
            )
        elif momentum_signal == "BREAKOUT":
            score += 1.5
            reasons.append(
                "📈 BREAKOUT en cours : accélération du prix"
            )
        elif momentum_signal == "TROP_TARD":
            score -= 3.0
            reasons.append(
                "🔴 TROP TARD : pump déjà fait (+2000% en 24h)"
            )
        elif momentum_signal == "DUMP":
            score -= 2.0
            reasons.append("🔴 DUMP en cours : vente massive")

        # ═══════════════════════════════════════════════════
        # 👥 SIGNAL 5 — CROISSANCE DES HOLDERS
        # ═══════════════════════════════════════════════════
        holder_signal = self._analyze_holders(holders, age_minutes, market_cap)

        if holder_signal == "VIRAL":
            score += 2.0
            reasons.append(
                f"🔥 VIRAL : {holders} holders pour MC ${market_cap:,.0f}"
            )
        elif holder_signal == "BON":
            score += 1.0
            reasons.append(f"✅ Bon ratio holders : {holders}")
        elif holder_signal == "FAIBLE":
            score -= 0.5
            reasons.append(f"⚠️ Peu de holders : {holders}")

        # ═══════════════════════════════════════════════════
        # ⏰ SIGNAL 6 — ÂGE OPTIMAL (fenêtre early)
        # ═══════════════════════════════════════════════════
        if age_minutes < 10:
            score += 1.5
            reasons.append(
                f"⚡ ULTRA EARLY : {age_minutes:.0f} min "
                f"(fenêtre parfaite)"
            )
        elif age_minutes < 30:
            score += 2.0
            reasons.append(
                f"🔥 Très early : {age_minutes:.0f} min"
            )
        elif age_minutes < 60:
            score += 1.5
            reasons.append(f"✅ Early : {age_minutes:.0f} min")
        elif age_minutes < 360:
            score += 0.5
            reasons.append(f"⏱️ Récent : {age_minutes/60:.1f}h")
        elif age_minutes > 1440:
            score -= 1.0
            reasons.append(f"📅 Token âgé : {age_minutes/1440:.1f}j")

        # ═══════════════════════════════════════════════════
        # 💧 SIGNAL 7 — LIQUIDITÉ (sécurité + crédibilité)
        # ═══════════════════════════════════════════════════
        if liquidity > 100_000:
            score += 2.0
            reasons.append(f"✅ Liquidité solide : ${liquidity:,.0f}")
        elif liquidity > 50_000:
            score += 1.5
            reasons.append(f"✅ Bonne liquidité : ${liquidity:,.0f}")
        elif liquidity > 20_000:
            score += 1.0
            reasons.append(f"🟡 Liquidité correcte : ${liquidity:,.0f}")
        elif liquidity < 5_000:
            score -= 2.0
            reasons.append(f"🔴 Liquidité dangereuse : ${liquidity:,.0f}")

        # Socials
        if dex_data.get("has_socials"):
            score += 0.5
            reasons.append("✅ Présence sociale")

        # ═══════════════════════════════════════════════════
        # 🎯 DÉTERMINATION DU SIGNAL GLOBAL
        # ═══════════════════════════════════════════════════
        score = max(0.0, min(10.0, score))
        signal_type = self._get_signal_type(
            score, momentum_signal, vol_acceleration,
            ratio_5m, ratio_1h, market_cap
        )

        return {
            # Identité
            "address":          token_address,
            "name":             dex_data.get("name", "Unknown"),
            "symbol":           dex_data.get("symbol", "???"),
            # Métriques marché
            "price_usd":        price,
            "market_cap":       market_cap,
            "liquidity":        liquidity,
            "volume_24h":       volume_24h,
            "volume_1h":        volume_1h,
            "volume_5m":        volume_5m,
            "price_change_5m":  price_change_5m,
            "price_change_1h":  price_change_1h,
            "price_change_6h":  price_change_6h,
            "price_change_24h": price_change_24h,
            "holders":          holders,
            "age_minutes":      age_minutes,
            # Sécurité
            "mint_renounced":   mint_renounced,
            "lp_locked":        lp_locked,
            "freeze_auth":      freeze_auth,
            "top_10_holders_pct": top10_pct,
            "is_honeypot":      is_honeypot,
            # Signaux momentum
            "vol_acceleration": vol_acceleration,
            "ratio_buy_5m":     ratio_5m,
            "ratio_buy_1h":     ratio_1h,
            "momentum_signal":  momentum_signal,
            "signal_type":      signal_type,
            # Socials
            "has_socials":      dex_data.get("has_socials", False),
            # Score
            "score":            round(score, 1),
            "score_reasons":    reasons,
            "whale_count":      0,
        }

    # ═══════════════════════════════════════════════════════
    # 🧮 CALCULS MOMENTUM
    # ═══════════════════════════════════════════════════════

    def _calc_volume_acceleration(
        self, vol_5m, vol_1h, vol_6h, vol_24h
    ) -> float:
        """
        Calcule l'accélération du volume.
        Compare le volume récent au volume moyen.
        > 2.0 = volume en forte accélération = signal pre-pump
        """
        try:
            # Volume moyen par heure sur 24h
            avg_hourly = vol_24h / 24 if vol_24h > 0 else 0

            if avg_hourly == 0:
                return 1.0

            # Volume de la dernière heure vs moyenne
            recent_rate = vol_1h / avg_hourly if vol_1h > 0 else 0

            # Volume des 5 dernières minutes annualisé en heure
            rate_5m = (vol_5m * 12) / avg_hourly if vol_5m > 0 else 0

            # Moyenne pondérée (5m compte plus)
            acceleration = (rate_5m * 0.6) + (recent_rate * 0.4)
            return round(acceleration, 2)

        except Exception:
            return 1.0

    def _detect_price_momentum(
        self, change_5m, change_1h, change_6h, change_24h
    ) -> str:
        """
        Détecte le type de momentum du prix.
        Retourne : ACCUMULATION / EARLY_PUMP / BREAKOUT /
                   TROP_TARD / DUMP / NEUTRE
        """
        # Trop tard — déjà pompé
        if change_24h > 2000:
            return "TROP_TARD"

        # Dump en cours
        if change_1h < -20 and change_5m < -10:
            return "DUMP"

        # Early pump — momentum haussier sur tous les TF
        if (change_5m > 5
                and change_1h > 10
                and change_6h > 0
                and change_24h < 500):
            return "EARLY_PUMP"

        # Breakout — accélération récente
        if change_5m > 10 and change_1h > 5:
            return "BREAKOUT"

        # Accumulation — prix stable mais volume monte
        # (géré par volume_acceleration)
        if (abs(change_1h) < 5
                and abs(change_6h) < 10
                and change_24h < 100):
            return "ACCUMULATION"

        return "NEUTRE"

    def _analyze_holders(
        self, holders, age_minutes, market_cap
    ) -> str:
        """
        Analyse la santé de la base de holders.
        """
        if holders == 0:
            return "INCONNU"

        # Ratio holders / age (combien arrivent par minute)
        if age_minutes > 0:
            holder_rate = holders / age_minutes
        else:
            holder_rate = holders

        if holder_rate > 5:      # +5 holders/minute
            return "VIRAL"
        elif holder_rate > 1:    # +1 holder/minute
            return "BON"
        elif holders < 50:
            return "FAIBLE"
        else:
            return "NORMAL"

    def _get_signal_type(
        self, score, momentum, vol_accel,
        ratio_5m, ratio_1h, market_cap
    ) -> str:
        """
        Détermine le type de signal global pour l'alerte.
        """
        if score >= 8.5:
            return "GEM_ULTIME"
        elif score >= 7.5:
            if momentum == "ACCUMULATION":
                return "ACCUMULATION_FORTE"
            elif momentum == "EARLY_PUMP":
                return "EARLY_PUMP"
            else:
                return "GEM_FORTE"
        elif score >= 6.5:
            if vol_accel >= 2.0:
                return "VOLUME_EXPLOSION"
            elif ratio_5m >= 3:
                return "PRESSION_ACHETEUSE"
            else:
                return "BON_TOKEN"
        elif score >= 5.0:
            return "A_SURVEILLER"
        else:
            return "RISQUE"

    # ═══════════════════════════════════════════════════════
    # 📡 DEXSCREENER
    # ═══════════════════════════════════════════════════════
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

            pairs = data.get("pairs") or []
            if not pairs:
                return {}

            # Paire Solana avec le plus de liquidité
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
                key=lambda p: p.get("liquidity", {}).get("usd", 0)
            )

            # Âge
            created_at  = pair.get(
                "pairCreatedAt",
                int(time.time() * 1000)
            ) / 1000
            age_minutes = (time.time() - created_at) / 60

            # Socials
            info        = pair.get("info", {})
            has_socials = bool(
                info.get("socials", []) or info.get("websites", [])
            )

            # Volumes par timeframe
            volume  = pair.get("volume", {})
            txns    = pair.get("txns", {})
            changes = pair.get("priceChange", {})

            return {
                "name":             pair.get("baseToken", {}).get("name", "Unknown"),
                "symbol":           pair.get("baseToken", {}).get("symbol", "???"),
                "price_usd":        float(pair.get("priceUsd", 0) or 0),
                "market_cap":       pair.get("marketCap", 0) or 0,
                "liquidity_usd":    pair.get("liquidity", {}).get("usd", 0),
                # Volumes multi-timeframes
                "volume_24h":       volume.get("h24", 0),
                "volume_6h":        volume.get("h6", 0),
                "volume_1h":        volume.get("h1", 0),
                "volume_5m":        volume.get("m5", 0),
                # Variations de prix
                "price_change_5m":  changes.get("m5", 0),
                "price_change_1h":  changes.get("h1", 0),
                "price_change_6h":  changes.get("h6", 0),
                "price_change_24h": changes.get("h24", 0),
                # Transactions
                "txns_5m":          txns.get("m5", {}),
                "txns_1h":          txns.get("h1", {}),
                # Infos
                "age_minutes":      age_minutes,
                "holders":          pair.get("holders", 0),
                "has_socials":      has_socials,
                "deployer":         pair.get("deployer", ""),
            }

        except Exception as e:
            logger.debug(f"[DEXSCREENER] Erreur {address[:8]}: {e}")
            return {}

    # ═══════════════════════════════════════════════════════
    # 🔍 RUGCHECK
    # ═══════════════════════════════════════════════════════
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