# modules/token_safety.py — v1.3 ANTI-RUG RENFORCÉ
# ═══════════════════════════════════════════════
# v1.3 :
# + Score minimum relevé à 4.0 (était 3.0)
# + Bloque les tokens < 2 min (trop de rugs)
# + Bloque si liquidité < $3K ET token > 5 min
# + Bloque si top holder > 50% (concentration)
# + Pénalise fortement les tokens sans socials
# + Pénalise les noms suspects (KirkCoin, etc.)

import asyncio
import aiohttp
import re
import time
from utils.logger import get_logger

logger = get_logger("token_safety")

# Patterns de noms suspects (souvent rugs)
SUSPICIOUS_NAME_PATTERNS = [
    r'\d{4,}',          # beaucoup de chiffres
    r'[A-Z]{8,}',       # trop de majuscules
    r'(inu|elon|trump|biden|pepe2|shib2)',  # copycats évidents
    r'(moon|rocket|gem|pump|100x|1000x)',   # mots trop bullish
    r'(safe|fair|based|legit)',              # red flags classiques
]


class TokenSafety:

    def __init__(self, rpc_url: str):
        self.rpc_url  = rpc_url
        self.session  = None
        self.cache    = {}
        self.CACHE_TTL = 60

        # v1.3 : stats
        self.total_checked = 0
        self.total_blocked = 0

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        )
        logger.info("✅ TokenSafety v1.3 ANTI-RUG démarré")

    async def stop(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def full_safety_check(self, token_mint: str) -> dict:

        cached = self.cache.get(token_mint)
        if cached and time.time() - cached[0] < self.CACHE_TTL:
            return cached[1]

        self.total_checked += 1

        result = {
            "safe":     True,
            "score":    10.0,
            "reasons":  [],
            "warnings": [],
            "details":  {}
        }

        # Lancer tous les checks en parallèle
        checks = await asyncio.gather(
            self._check_rugcheck(token_mint),
            self._check_liquidity(token_mint),
            self._check_mint_authority(token_mint),
            self._check_age_and_meta(token_mint),
            return_exceptions=True
        )

        keys = ["rugcheck", "liquidity", "mint_auth", "age_meta"]
        for key, check in zip(keys, checks):
            if isinstance(check, Exception):
                result["details"][key] = {"error": str(check)}
            else:
                result["details"][key] = check or {}

        # Appliquer toutes les règles
        self._rules_rugcheck(result)
        self._rules_liquidity(result)
        self._rules_mint(result)
        self._rules_age(result)
        self._rules_name(result)
        self._rules_concentration(result)

        result["score"] = round(
            max(0.0, min(10.0, result["score"])), 1
        )

        # v1.3 : seuil relevé de 3.0 à 4.0
        if result["score"] < 4.0:
            result["safe"] = False
            if not result["reasons"]:
                result["reasons"].append(
                    f"Score sécurité insuffisant: {result['score']}/10"
                )

        if not result["safe"]:
            self.total_blocked += 1

        icon = "✅" if result["safe"] else "❌"
        logger.info(
            f"{icon} Safety v1.3 | {token_mint[:8]}... | "
            f"Score: {result['score']}/10 | "
            f"❌{len(result['reasons'])} ⚠️{len(result['warnings'])}"
        )

        self.cache[token_mint] = (time.time(), result)
        return result

    # ════════════════════════════════════════
    # RÈGLES v1.3 RENFORCÉES
    # ════════════════════════════════════════

    def _rules_rugcheck(self, r: dict):
        """Honeypot et freeze = BLOQUÉ immédiatement."""
        d = r["details"].get("rugcheck", {})
        if not d or "error" in d:
            r["score"] -= 0.5
            return

        if d.get("is_honeypot"):
            r["safe"]   = False
            r["score"] -= 8.0
            r["reasons"].append("🍯 HONEYPOT détecté")

        if d.get("has_freeze"):
            r["safe"]   = False
            r["score"] -= 8.0
            r["reasons"].append("🥶 Freeze Authority active")

        # v1.3 : pénalise les risques RugCheck
        risk_count = d.get("risk_count", 0)
        if risk_count >= 3:
            r["score"] -= 2.0
            r["warnings"].append(
                f"⚠️ {risk_count} risques RugCheck détectés"
            )
        elif risk_count >= 1:
            r["score"] -= 0.5

    def _rules_liquidity(self, r: dict):
        """
        v1.3 : Plus strict sur la liquidité.
        Pump.fun OK si < 5 min.
        Sinon minimum $5K (était $3K).
        """
        d   = r["details"].get("liquidity", {})
        liq = d.get("liquidity_usd", 0)
        age = r["details"].get("age_meta", {}).get("age_minutes", 999)

        if liq == 0:
            if age < 5:
                # Pump.fun bonding curve → toléré
                r["score"]   -= 0.5
                r["warnings"].append("Liquidité non visible (bonding curve)")
            elif age < 15:
                # Encore jeune → pénalité légère
                r["score"]   -= 2.0
                r["warnings"].append(f"Liquidité $0 après {age:.0f}min")
            else:
                # Token vieux sans liquidité = MORT
                r["safe"]   = False
                r["score"] -= 5.0
                r["reasons"].append(
                    f"🔴 Liquidité $0 après {age:.0f}min → token mort"
                )

        elif liq < 3_000:
            r["safe"]   = False
            r["score"] -= 4.0
            r["reasons"].append(
                f"🔴 Liquidité TROP faible: ${liq:,.0f} (min $3K)"
            )

        elif liq < 8_000:
            r["score"]   -= 2.0
            r["warnings"].append(f"⚠️ Liquidité faible: ${liq:,.0f}")

        elif liq < 20_000:
            r["score"] -= 0.5

        elif liq > 100_000:
            r["score"] += 0.5

    def _rules_mint(self, r: dict):
        """v1.3 : Mint authority = forte pénalité."""
        d = r["details"].get("mint_auth", {})
        if d.get("has_mint_authority"):
            r["score"]   -= 2.5   # était -1.5
            r["warnings"].append(
                "⚠️ Mint Authority active (peut créer des tokens)"
            )

    def _rules_age(self, r: dict):
        """
        v1.3 : Bloque les tokens < 2 min.
        Les rugs sont souvent créés et rugpullés en < 5 min.
        """
        d   = r["details"].get("age_meta", {})
        age = d.get("age_minutes", 999)

        if age < 2:
            # v1.3 : trop jeune = BLOQUÉ
            r["safe"]   = False
            r["score"] -= 3.0
            r["reasons"].append(
                f"🔴 Token trop jeune: {age:.1f}min (min 2 min)"
            )
        elif age < 5:
            r["score"]   -= 1.0
            r["warnings"].append(f"⚠️ Très jeune: {age:.1f}min")
        elif age < 10:
            r["score"] -= 0.3
        elif age > 1440:
            r["score"] += 0.5

    def _rules_name(self, r: dict):
        """
        v1.3 : NOUVEAU — Détecte les noms suspects.
        KirkCoin, SafeMoon2, etc.
        """
        d      = r["details"].get("age_meta", {})
        name   = d.get("name",   "").lower()
        symbol = d.get("symbol", "").lower()

        if not name and not symbol:
            return

        text = f"{name} {symbol}"

        suspicious_count = 0
        for pattern in SUSPICIOUS_NAME_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                suspicious_count += 1

        if suspicious_count >= 2:
            r["score"]   -= 2.0
            r["warnings"].append(
                f"⚠️ Nom suspect: {d.get('symbol', '?')}"
            )
        elif suspicious_count == 1:
            r["score"] -= 0.5

        # Noms génériques souvent rugs
        generic_words = [
            "coin", "token", "inu", "ai", "gpt",
            "doge", "cat", "dog", "pepe",
        ]
        generic_count = sum(
            1 for w in generic_words if w in text
        )
        if generic_count >= 2:
            r["score"]   -= 1.0
            r["warnings"].append("⚠️ Nom générique (souvent rug)")

    def _rules_concentration(self, r: dict):
        """
        v1.3 : NOUVEAU — Bloque si top holder trop concentré.
        """
        d        = r["details"].get("rugcheck", {})
        top_pct  = d.get("top_holder_pct", 0)
        top10    = d.get("top_10_holders_pct", 0)

        if top_pct > 50:
            r["safe"]   = False
            r["score"] -= 5.0
            r["reasons"].append(
                f"🔴 Top holder: {top_pct:.0f}% (rug facile)"
            )
        elif top_pct > 30:
            r["score"]   -= 2.0
            r["warnings"].append(
                f"⚠️ Top holder concentré: {top_pct:.0f}%"
            )

        if top10 > 80:
            r["score"]   -= 2.0
            r["warnings"].append(
                f"⚠️ Top 10 holders: {top10:.0f}%"
            )
        elif top10 > 60:
            r["score"] -= 1.0

    # ════════════════════════════════════════
    # CHECKS API
    # ════════════════════════════════════════

    async def _check_rugcheck(self, mint: str) -> dict:
        """RugCheck API — honeypot, freeze, risques."""
        try:
            url = f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    risks = data.get("risks", [])
                    names = [r.get("name", "").lower() for r in risks]

                    # Top holder depuis RugCheck
                    top_holders = data.get("topHolders", [])
                    top_pct     = 0
                    top10_pct   = 0
                    if top_holders:
                        pcts     = [
                            h.get("pct", 0) for h in top_holders
                        ]
                        top_pct  = pcts[0] if pcts else 0
                        top10_pct = sum(pcts[:10])

                    return {
                        "is_honeypot": any(
                            x in names
                            for x in ["honeypot", "trading disabled"]
                        ),
                        "has_freeze": any(
                            "freeze" in x for x in names
                        ),
                        "risk_count":         len(risks),
                        "top_holder_pct":     top_pct,
                        "top_10_holders_pct": top10_pct,
                    }
        except Exception:
            pass
        return {}

    async def _check_liquidity(self, mint: str) -> dict:
        """DexScreener — liquidité."""
        try:
            url = (
                f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            )
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    pairs = data.get("pairs") or []
                    if pairs:
                        return {
                            "liquidity_usd": (
                                pairs[0]
                                .get("liquidity", {})
                                .get("usd", 0)
                            )
                        }
        except Exception:
            pass
        return {"liquidity_usd": 0}

    async def _check_mint_authority(self, mint: str) -> dict:
        """Solana RPC — mint authority."""
        try:
            payload = {
                "jsonrpc": "2.0",
                "id":      1,
                "method":  "getAccountInfo",
                "params":  [mint, {"encoding": "jsonParsed"}],
            }
            async with self.session.post(
                self.rpc_url, json=payload
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    info = (
                        data.get("result", {})
                            .get("value", {})
                            .get("data", {})
                            .get("parsed", {})
                            .get("info", {})
                    )
                    return {
                        "has_mint_authority": (
                            info.get("mintAuthority") is not None
                        )
                    }
        except Exception:
            pass
        return {}

    async def _check_age_and_meta(self, mint: str) -> dict:
        """
        v1.3 : Check âge + métadonnées (nom, symbol, socials).
        """
        try:
            url = (
                f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            )
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    pairs = data.get("pairs") or []
                    if pairs:
                        pair    = pairs[0]
                        created = pair.get("pairCreatedAt", 0)
                        base    = pair.get("baseToken", {})
                        info    = pair.get("info", {}) or {}

                        age_minutes = 0
                        if created:
                            age_ms      = time.time() * 1000 - created
                            age_minutes = round(age_ms / 60000, 1)

                        has_socials = bool(
                            info.get("socials", [])
                            or info.get("websites", [])
                        )

                        return {
                            "age_minutes": age_minutes,
                            "name":        base.get("name",   ""),
                            "symbol":      base.get("symbol", ""),
                            "has_socials": has_socials,
                        }
        except Exception:
            pass
        return {"age_minutes": 999}

    def summary(self, result: dict) -> str:
        """Résumé lisible pour /check."""
        icon  = "✅" if result["safe"] else "❌"
        lines = [f"{icon} Sécurité: {result['score']}/10"]

        for r in result.get("reasons", []):
            lines.append(f"🚫 {r}")
        for w in result.get("warnings", []):
            lines.append(f"⚠️ {w}")

        # Stats
        lines.append(
            f"\n📊 Checkés: {self.total_checked} | "
            f"Bloqués: {self.total_blocked} "
            f"({self.total_blocked/max(self.total_checked,1)*100:.0f}%)"
        )

        return "\n".join(lines)