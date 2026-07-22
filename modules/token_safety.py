# modules/token_safety.py — v1.4 FINAL
# ═══════════════════════════════════════════════
# v1.4 :
# + Score minimum relevé à 5.5 (était 4.0)
# + Liq $0 après 8 min = BLOQUÉ
# + Token < 3 min = BLOQUÉ
# + Top holder > 35% = BLOQUÉ
# + Noms suspects fortement pénalisés
# + Absence de socials pénalisée
# ═══════════════════════════════════════════════

import asyncio
import aiohttp
import re
import time
from utils.logger import get_logger

logger = get_logger("token_safety")

SUSPICIOUS_NAME_PATTERNS = [
    r'(inu|elon|trump|biden|pepe2|shib2|doge2)',
    r'(assfarted|memehouse|fartcoon|psyopcoon)',
    r'(safe|fair|based|legit|rewards)',
    r'\d{4,}',
]

GENERIC_NAME_WORDS = {
    "coin", "token", "inu", "doge", "cat", "fish",
    "ai", "gpt", "meme", "moon", "safe", "pump",
}


class TokenSafety:

    def __init__(self, rpc_url: str):
        self.rpc_url       = rpc_url
        self.session       = None
        self.cache         = {}
        self.CACHE_TTL     = 60
        self.total_checked = 0
        self.total_blocked = 0

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        )
        logger.info("✅ TokenSafety v1.4 démarré")

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

        self._rules_rugcheck(result)
        self._rules_liquidity(result)
        self._rules_mint(result)
        self._rules_age(result)
        self._rules_name(result)
        self._rules_socials(result)
        self._rules_concentration(result)

        result["score"] = round(
            max(0.0, min(10.0, result["score"])), 1
        )

        # v1.4 : seuil à 5.5
        if result["score"] < 5.5:
            result["safe"] = False
            if not result["reasons"]:
                result["reasons"].append(
                    f"Score sécurité insuffisant: {result['score']}/10"
                )

        if not result["safe"]:
            self.total_blocked += 1

        icon = "✅" if result["safe"] else "❌"
        logger.info(
            f"{icon} Safety v1.4 | {token_mint[:8]}... | "
            f"Score: {result['score']}/10 | "
            f"❌{len(result['reasons'])} ⚠️{len(result['warnings'])}"
        )

        self.cache[token_mint] = (time.time(), result)
        return result

    def _rules_rugcheck(self, r: dict):
        d = r["details"].get("rugcheck", {})
        if not d or "error" in d:
            r["score"] -= 0.5
            return

        if d.get("is_honeypot"):
            r["safe"]   = False
            r["score"] -= 10.0
            r["reasons"].append("🍯 HONEYPOT détecté")

        if d.get("has_freeze"):
            r["safe"]   = False
            r["score"] -= 10.0
            r["reasons"].append("🥶 Freeze Authority active")

        risk_count = d.get("risk_count", 0)
        if risk_count >= 3:
            r["score"]   -= 2.0
            r["warnings"].append(
                f"⚠️ {risk_count} risques RugCheck"
            )
        elif risk_count >= 1:
            r["score"] -= 0.8

    def _rules_liquidity(self, r: dict):
        d   = r["details"].get("liquidity", {})
        liq = float(d.get("liquidity_usd", 0) or 0)
        age = float(
            r["details"].get("age_meta", {}).get("age_minutes", 999) or 999
        )

        if liq == 0:
            if age < 5:
                r["score"]   -= 1.5
                r["warnings"].append("Liquidité non visible (bonding curve)")
            elif age < 8:
                r["score"]   -= 3.0
                r["warnings"].append(f"⚠️ Liq $0 après {age:.1f}min")
            else:
                r["safe"]   = False
                r["score"] -= 5.0
                r["reasons"].append(
                    f"🔴 Liquidité $0 après {age:.0f}min"
                )

        elif liq < 5_000:
            r["score"]   -= 3.0
            r["warnings"].append(
                f"⚠️ Liquidité très faible: ${liq:,.0f}"
            )

        elif liq < 10_000:
            r["score"] -= 1.5
            r["warnings"].append(f"⚠️ Liquidité faible: ${liq:,.0f}")

        elif liq < 20_000:
            r["score"] -= 0.3

        elif liq > 50_000:
            r["score"] += 0.5

    def _rules_mint(self, r: dict):
        d = r["details"].get("mint_auth", {})
        if d.get("has_mint_authority"):
            r["score"]   -= 2.0
            r["warnings"].append("⚠️ Mint Authority active")

    def _rules_age(self, r: dict):
        d   = r["details"].get("age_meta", {})
        age = float(d.get("age_minutes", 999) or 999)

        if age < 3:
            r["safe"]   = False
            r["score"] -= 3.0
            r["reasons"].append(
                f"🔴 Token trop jeune: {age:.1f}min"
            )
        elif age < 5:
            r["score"]   -= 1.0
            r["warnings"].append(f"⚠️ Très jeune: {age:.1f}min")
        elif age < 8:
            r["score"] -= 0.3

    def _rules_name(self, r: dict):
        d      = r["details"].get("age_meta", {})
        name   = str(d.get("name",   "") or "").lower()
        symbol = str(d.get("symbol", "") or "").lower()

        if not name and not symbol:
            return

        text = f"{name} {symbol}"

        suspicious_count = 0
        for pattern in SUSPICIOUS_NAME_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                suspicious_count += 1

        if suspicious_count >= 2:
            r["score"]   -= 3.0
            r["warnings"].append(
                f"⚠️ Nom très suspect: {d.get('symbol', '?')}"
            )
        elif suspicious_count == 1:
            r["score"]   -= 1.0
            r["warnings"].append(
                f"⚠️ Nom suspect: {d.get('symbol', '?')}"
            )

        words = re.split(r'[^a-zA-Z0-9]+', text)
        generic_count = sum(
            1 for w in words if w in GENERIC_NAME_WORDS
        )
        if generic_count >= 2:
            r["score"] -= 1.0
            r["warnings"].append("⚠️ Nom générique")

    def _rules_socials(self, r: dict):
        d = r["details"].get("age_meta", {})
        if not d.get("has_socials", False):
            r["score"] -= 1.0
            r["warnings"].append("⚠️ Aucun social détecté")
        else:
            r["score"] += 0.3

    def _rules_concentration(self, r: dict):
        d       = r["details"].get("rugcheck", {})
        top_pct = float(d.get("top_holder_pct", 0) or 0)
        top10   = float(d.get("top_10_holders_pct", 0) or 0)

        if top_pct > 35:
            r["safe"]   = False
            r["score"] -= 5.0
            r["reasons"].append(
                f"🔴 Top holder: {top_pct:.0f}% (rug facile)"
            )
        elif top_pct > 25:
            r["score"]   -= 1.5
            r["warnings"].append(
                f"⚠️ Top holder concentré: {top_pct:.0f}%"
            )

        if top10 > 80:
            r["score"]   -= 1.5
            r["warnings"].append(f"⚠️ Top 10: {top10:.0f}%")
        elif top10 > 60:
            r["score"] -= 0.5

    async def _check_rugcheck(self, mint: str) -> dict:
        try:
            url = f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    risks = data.get("risks", [])
                    names = [r.get("name", "").lower() for r in risks]

                    top_holders = data.get("topHolders", [])
                    top_pct     = 0
                    top10_pct   = 0
                    if top_holders:
                        pcts      = [h.get("pct", 0) for h in top_holders]
                        top_pct   = pcts[0] if pcts else 0
                        top10_pct = sum(pcts[:10])

                    return {
                        "is_honeypot": any(
                            x in names
                            for x in ["honeypot", "trading disabled"]
                        ),
                        "has_freeze":         any("freeze" in x for x in names),
                        "risk_count":         len(risks),
                        "top_holder_pct":     top_pct,
                        "top_10_holders_pct": top10_pct,
                    }
        except Exception:
            pass
        return {}

    async def _check_liquidity(self, mint: str) -> dict:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
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
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data  = await resp.json()
                    pairs = data.get("pairs") or []
                    if pairs:
                        pair    = pairs[0]
                        created = pair.get("pairCreatedAt", 0)
                        base    = pair.get("baseToken", {})
                        info    = pair.get("info", {}) or {}

                        age_minutes = 999
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
        return {
            "age_minutes": 999,
            "name":        "",
            "symbol":      "",
            "has_socials": False,
        }

    def summary(self, result: dict) -> str:
        icon  = "✅" if result["safe"] else "❌"
        lines = [f"{icon} Sécurité: {result['score']}/10"]
        for r in result.get("reasons", []):
            lines.append(f"🚫 {r}")
        for w in result.get("warnings", []):
            lines.append(f"⚠️ {w}")
        lines.append(
            f"\n📊 Checkés: {self.total_checked} | "
            f"Bloqués: {self.total_blocked} "
            f"({self.total_blocked/max(self.total_checked,1)*100:.0f}%)"
        )
        return "\n".join(lines)