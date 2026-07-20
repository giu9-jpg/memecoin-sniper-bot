# modules/token_safety.py v1.2
"""
TokenSafety v1.2
Fix définitif : ne bloque PLUS sur liquidité $0
Les tokens Pump.fun n'ont pas de liquidité DexScreener
tant qu'ils n'ont pas migré vers Raydium/PumpSwap.
On pénalise le score mais on ne bloque pas.
"""

import asyncio
import aiohttp
import time
from utils.logger import get_logger

logger = get_logger("token_safety")


class TokenSafety:

    def __init__(self, rpc_url: str):
        self.rpc_url = rpc_url
        self.session = None
        self.cache = {}
        self.CACHE_TTL = 60

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        )
        logger.info("✅ TokenSafety v1.2 démarré")

    async def stop(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def full_safety_check(self, token_mint: str) -> dict:

        cached = self.cache.get(token_mint)
        if cached and time.time() - cached[0] < self.CACHE_TTL:
            return cached[1]

        result = {
            "safe": True,
            "score": 10.0,
            "reasons": [],
            "warnings": [],
            "details": {}
        }

        checks = await asyncio.gather(
            self._check_rugcheck(token_mint),
            self._check_liquidity(token_mint),
            self._check_mint_authority(token_mint),
            self._check_age(token_mint),
            return_exceptions=True
        )

        keys = ["rugcheck", "liquidity", "mint_auth", "age"]
        for key, check in zip(keys, checks):
            if isinstance(check, Exception):
                result["details"][key] = {"error": str(check)}
            else:
                result["details"][key] = check or {}

        # Appliquer les règles
        self._rules_rugcheck(result)
        self._rules_liquidity(result)
        self._rules_mint(result)
        self._rules_age(result)

        result["score"] = round(max(0.0, min(10.0, result["score"])), 1)

        # Bloquer UNIQUEMENT si score < 3 à cause de honeypot/freeze
        if result["score"] < 3.0:
            result["safe"] = False
            if not result["reasons"]:
                result["reasons"].append(
                    f"Score sécurité trop bas: {result['score']}/10"
                )

        icon = "✅" if result["safe"] else "❌"
        logger.info(
            f"{icon} Safety | {token_mint[:8]}... | "
            f"Score: {result['score']}/10 | "
            f"❌{len(result['reasons'])} ⚠️{len(result['warnings'])}"
        )

        self.cache[token_mint] = (time.time(), result)
        return result

    # ════════════════════════════════════════
    # RÈGLES v1.2
    # ════════════════════════════════════════

    def _rules_rugcheck(self, r: dict):
        """Seuls les honeypots et freeze authority BLOQUENT"""
        d = r["details"].get("rugcheck", {})
        if not d or "error" in d:
            r["score"] -= 0.3
            return

        if d.get("is_honeypot"):
            r["safe"] = False
            r["score"] -= 5.0
            r["reasons"].append("🍯 HONEYPOT détecté")

        if d.get("has_freeze"):
            r["safe"] = False
            r["score"] -= 5.0
            r["reasons"].append("🥶 Freeze Authority active")

    def _rules_liquidity(self, r: dict):
        """
        v1.2 : NE BLOQUE PLUS sur liquidité $0
        Les tokens Pump.fun n'ont pas de liquidité DexScreener
        tant qu'ils sont sur la bonding curve.
        On pénalise le score, mais on laisse passer.
        """
        d = r["details"].get("liquidity", {})
        liq = d.get("liquidity_usd", 0)

        if liq == 0:
            # Pump.fun bonding curve : pas de liquidité visible
            r["score"] -= 1.0
            r["warnings"].append("Liquidité non visible (bonding curve)")
        elif liq < 5000:
            r["score"] -= 1.5
            r["warnings"].append(f"Liquidité faible: ${liq:,.0f}")
        elif liq < 20000:
            r["score"] -= 0.5
        elif liq > 100000:
            r["score"] += 0.5

    def _rules_mint(self, r: dict):
        d = r["details"].get("mint_auth", {})
        if d.get("has_mint_authority"):
            r["score"] -= 1.5
            r["warnings"].append("Mint Authority active")

    def _rules_age(self, r: dict):
        age = r["details"].get("age", {}).get("age_minutes", 999)
        if age < 1:
            r["warnings"].append("Token < 1 minute")
            r["score"] -= 0.5
        elif age > 1440:
            r["score"] += 0.5

    # ════════════════════════════════════════
    # CHECKS API
    # ════════════════════════════════════════

    async def _check_rugcheck(self, mint):
        try:
            url = f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    risks = data.get("risks", [])
                    names = [r.get("name", "").lower() for r in risks]
                    return {
                        "is_honeypot": any(
                            x in names
                            for x in ["honeypot", "trading disabled"]
                        ),
                        "has_freeze": any("freeze" in x for x in names),
                    }
        except Exception:
            pass
        return {}

    async def _check_liquidity(self, mint):
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs") or []
                    if pairs:
                        return {
                            "liquidity_usd": pairs[0].get("liquidity", {}).get("usd", 0)
                        }
        except Exception:
            pass
        return {"liquidity_usd": 0}

    async def _check_mint_authority(self, mint):
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getAccountInfo",
                "params": [mint, {"encoding": "jsonParsed"}]
            }
            async with self.session.post(self.rpc_url, json=payload) as resp:
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
                        "has_mint_authority": info.get("mintAuthority") is not None
                    }
        except Exception:
            pass
        return {}

    async def _check_age(self, mint):
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs") or []
                    if pairs:
                        created = pairs[0].get("pairCreatedAt", 0)
                        if created:
                            age_ms = time.time() * 1000 - created
                            return {"age_minutes": round(age_ms / 60000, 1)}
        except Exception:
            pass
        return {"age_minutes": 999}

    def summary(self, result: dict) -> str:
        icon = "✅" if result["safe"] else "❌"
        lines = [f"{icon} Sécurité: {result['score']}/10"]
        for r in result.get("reasons", []):
            lines.append(f"🚫 {r}")
        for w in result.get("warnings", []):
            lines.append(f"⚠️ {w}")
        return "\n".join(lines)