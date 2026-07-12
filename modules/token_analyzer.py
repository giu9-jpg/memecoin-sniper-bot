"""
Module d'analyse de tokens
Récupère les données depuis DexScreener + RugCheck
Calcule un score de confiance sur 10
"""

import requests
from utils.logger import logger
from config.settings import (
    MIN_LIQUIDITY,
    MIN_VOLUME_24H,
    SCORE_BUY,
    SCORE_WATCH,
)


class TokenAnalyzer:
    def __init__(self):
        self.dexscreener_base = (
            "https://api.dexscreener.com/latest"
        )
        self.rugcheck_base = (
            "https://api.rugcheck.xyz/v1"
        )

    def analyze_token(self, contract_address):
        """Analyse complète d'un token"""
        data = {}

        # 1. Données marché via DexScreener
        dex_data = self._get_dexscreener_data(contract_address)
        if dex_data:
            data.update(dex_data)

        # 2. Données sécurité via RugCheck
        rug_data = self._get_rugcheck_data(contract_address)
        if rug_data:
            data.update(rug_data)

        # 3. Calcule le score final
        data["score"] = self._calculate_score(data)
        data["score_details"] = self._get_score_details(data)
        return data

    def _get_dexscreener_data(self, contract_address):
        """Récupère prix, volume, liquidité depuis DexScreener"""
        try:
            url = (
                f"{self.dexscreener_base}"
                f"/dex/tokens/{contract_address}"
            )
            response = requests.get(url, timeout=10)
            result = response.json()

            if not result.get("pairs"):
                return None

            # Prend la paire avec le plus de liquidité
            pair = sorted(
                result["pairs"],
                key=lambda x: float(
                    x.get("liquidity", {}).get("usd", 0)
                ),
                reverse=True
            )[0]

            # Calcule l'âge du token
            created_at = pair.get("pairCreatedAt", 0)
            age_hours = 0
            if created_at:
                import time
                age_hours = (
                    time.time() - created_at / 1000
                ) / 3600

            # Récupère les transactions
            txns = pair.get("txns", {})
            buys_5m = txns.get("m5", {}).get("buys", 0)
            sells_5m = txns.get("m5", {}).get("sells", 0)
            buys_1h = txns.get("h1", {}).get("buys", 0)
            sells_1h = txns.get("h1", {}).get("sells", 0)

            # Ratio achat/vente
            buy_sell_ratio_5m = (
                buys_5m / max(sells_5m, 1)
            )
            buy_sell_ratio_1h = (
                buys_1h / max(sells_1h, 1)
            )

            return {
                "name": pair.get(
                    "baseToken", {}
                ).get("name", "Inconnu"),
                "symbol": pair.get(
                    "baseToken", {}
                ).get("symbol", "???"),
                "price_usd": float(
                    pair.get("priceUsd", 0) or 0
                ),
                "volume_24h": float(
                    pair.get("volume", {}).get("h24", 0)
                ),
                "volume_1h": float(
                    pair.get("volume", {}).get("h1", 0)
                ),
                "volume_5m": float(
                    pair.get("volume", {}).get("m5", 0)
                ),
                "liquidity_usd": float(
                    pair.get("liquidity", {}).get("usd", 0)
                ),
                "market_cap": float(
                    pair.get("fdv", 0) or 0
                ),
                "price_change_5m": float(
                    pair.get("priceChange", {}).get("m5", 0)
                ),
                "price_change_1h": float(
                    pair.get("priceChange", {}).get("h1", 0)
                ),
                "price_change_24h": float(
                    pair.get("priceChange", {}).get("h24", 0)
                ),
                "buys_5m": buys_5m,
                "sells_5m": sells_5m,
                "buys_1h": buys_1h,
                "sells_1h": sells_1h,
                "buy_sell_ratio_5m": round(buy_sell_ratio_5m, 2),
                "buy_sell_ratio_1h": round(buy_sell_ratio_1h, 2),
                "age_hours": round(age_hours, 1),
                "url": pair.get("url", ""),
                "dex": pair.get("dexId", "unknown"),
                "has_socials": bool(
                    pair.get("info", {}).get("socials", [])
                ),
                "has_website": bool(
                    pair.get("info", {}).get("websites", [])
                ),
            }

        except Exception as e:
            logger.error(f"DexScreener erreur : {e}")
            return None

    def _get_rugcheck_data(self, contract_address):
        """Vérification sécurité via RugCheck"""
        try:
            url = (
                f"{self.rugcheck_base}"
                f"/tokens/{contract_address}/report"
            )
            response = requests.get(url, timeout=10)
            data = response.json()

            risks = data.get("risks", [])
            markets = data.get("markets", [])
            top_holders = data.get("topHolders", [])

            # Détecte les risques critiques
            is_dangerous = any(
                r.get("level") in ["danger", "critical"]
                for r in risks
            )

            # Risques warnings
            has_warnings = any(
                r.get("level") == "warn"
                for r in risks
            )

            # Vérifie si la liquidité est lockée (>50%)
            lp_locked = any(
                m.get("lp", {}).get("lpLockedPct", 0) > 50
                for m in markets
            )

            # Calcule la concentration des top 10 holders
            top10_percent = sum(
                float(h.get("pct", 0))
                for h in top_holders[:10]
            )

            # Détails des risques
            risk_names = [
                r.get("name", "") for r in risks
            ]

            return {
                "is_honeypot": is_dangerous,
                "has_warnings": has_warnings,
                "liquidity_locked": lp_locked,
                "mint_renounced": not data.get(
                    "mintAuthority", True
                ),
                "freeze_authority": bool(
                    data.get("freezeAuthority", False)
                ),
                "top10_holders_percent": top10_percent,
                "holder_count": len(top_holders),
                "rugcheck_score": data.get("score", 0),
                "risk_names": risk_names,
                "honeypot_verdict": (
                    "🔴 DANGER"
                    if is_dangerous
                    else "🟢 PROPRE"
                ),
            }

        except Exception as e:
            logger.error(f"RugCheck erreur : {e}")
            return {
                "is_honeypot": None,
                "liquidity_locked": None,
                "mint_renounced": None,
                "honeypot_verdict": "⚠️ NON VÉRIFIÉ",
            }

    def _calculate_score(self, data):
        """
        Calcule un score de 0 à 10
        basé sur tous les critères
        """
        score = 5.0  # Score de base

        # ==========================================
        # LIQUIDITÉ
        # ==========================================
        liquidity = data.get("liquidity_usd", 0)
        if liquidity >= 100000:
            score += 2.0
        elif liquidity >= 50000:
            score += 1.5
        elif liquidity >= 20000:
            score += 1.0
        elif liquidity >= 10000:
            score += 0.5
        elif liquidity < 5000:
            score -= 2.0

        # ==========================================
        # VOLUME
        # ==========================================
        volume = data.get("volume_24h", 0)
        if volume >= 200000:
            score += 2.0
        elif volume >= 100000:
            score += 1.5
        elif volume >= 50000:
            score += 1.0
        elif volume >= 25000:
            score += 0.5
        elif volume < 10000:
            score -= 1.0

        # ==========================================
        # RATIO ACHATS/VENTES (momentum)
        # ==========================================
        ratio_5m = data.get("buy_sell_ratio_5m", 1)
        if ratio_5m >= 3:
            score += 1.5    # Beaucoup plus d'achats que ventes
        elif ratio_5m >= 2:
            score += 1.0
        elif ratio_5m >= 1.5:
            score += 0.5
        elif ratio_5m < 0.5:
            score -= 1.0    # Plus de ventes = dump

        ratio_1h = data.get("buy_sell_ratio_1h", 1)
        if ratio_1h >= 2:
            score += 0.5
        elif ratio_1h < 0.7:
            score -= 0.5

        # ==========================================
        # ÂGE DU TOKEN (early = mieux)
        # ==========================================
        age = data.get("age_hours", 999)
        if age <= 1:
            score += 1.5    # Moins d'1h = très early
        elif age <= 6:
            score += 1.0    # Moins de 6h = early
        elif age <= 24:
            score += 0.5    # Moins d'1 jour
        elif age > 72:
            score -= 0.5    # Plus de 3 jours = late

        # ==========================================
        # SÉCURITÉ
        # ==========================================
        if data.get("mint_renounced") is True:
            score += 1.0
        elif data.get("mint_renounced") is False:
            score -= 2.0

        if data.get("liquidity_locked") is True:
            score += 1.0

        if data.get("freeze_authority") is True:
            score -= 2.0

        if data.get("is_honeypot") is True:
            score -= 5.0

        if data.get("has_warnings"):
            score -= 0.5

        # ==========================================
        # SOCIALS & WEBSITE
        # ==========================================
        if data.get("has_socials"):
            score += 0.5
        if data.get("has_website"):
            score += 0.5

        # ==========================================
        # CONCENTRATION DES HOLDERS
        # ==========================================
        top10 = data.get("top10_holders_percent", 0)
        if top10 > 80:
            score -= 3.0
        elif top10 > 50:
            score -= 2.0
        elif top10 > 30:
            score -= 1.0
        elif top10 < 20:
            score += 0.5    # Bien distribué

        # ==========================================
        # VARIATION DE PRIX (déjà trop pompé ?)
        # ==========================================
        change_24h = data.get("price_change_24h", 0)
        if change_24h > 2000:
            score -= 3.0    # Trop tard
        elif change_24h > 1000:
            score -= 2.0
        elif change_24h > 500:
            score -= 1.0
        elif 50 <= change_24h <= 300:
            score += 0.5    # Bonne hausse modérée

        # Borne le score entre 0 et 10
        return round(max(0, min(10, score)), 1)

    def _get_score_details(self, data):
        """Retourne les points forts et faibles du token"""
        positifs = []
        negatifs = []

        # Liquidité
        liq = data.get("liquidity_usd", 0)
        if liq >= 50000:
            positifs.append(f"💧 Bonne liquidité (${liq:,.0f})")
        elif liq < 10000:
            negatifs.append(f"💧 Liquidité faible (${liq:,.0f})")

        # Sécurité
        if data.get("mint_renounced"):
            positifs.append("✅ Mint renoncé")
        else:
            negatifs.append("❌ Mint non renoncé")

        if data.get("liquidity_locked"):
            positifs.append("✅ Liquidité lockée")
        else:
            negatifs.append("❌ Liquidité non lockée")

        if data.get("freeze_authority"):
            negatifs.append("🔴 Freeze authority active")

        # Momentum
        ratio = data.get("buy_sell_ratio_5m", 1)
        if ratio >= 2:
            positifs.append(f"📈 Fort momentum achat ({ratio}x)")
        elif ratio < 0.5:
            negatifs.append(f"📉 Momentum vente ({ratio}x)")

        # Âge
        age = data.get("age_hours", 0)
        if age <= 6:
            positifs.append(f"⏰ Token très récent ({age}h)")
        elif age > 48:
            negatifs.append(f"⏰ Token ancien ({age}h)")

        # Holders
        top10 = data.get("top10_holders_percent", 0)
        if top10 > 50:
            negatifs.append(f"🔴 Concentration holders ({top10:.0f}%)")
        elif top10 < 20:
            positifs.append(f"✅ Bonne distribution ({top10:.0f}%)")

        return {
            "positifs": positifs,
            "negatifs": negatifs
        }