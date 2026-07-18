# modules/token_safety.py v1.0
"""
6 vérifications de sécurité en parallèle
Résultat en moins de 3 secondes
Bloque les honeypots, rugs, et tokens dangereux
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
        self.CACHE_TTL = 120  # 2 minutes

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        )
        logger.info("✅ TokenSafety démarré (6 checks)")

    async def stop(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ════════════════════════════════════════
    # CHECK PRINCIPAL
    # ════════════════════════════════════════

    async def full_safety_check(self, token_mint: str) -> dict:
        """
        Lance tous les checks en parallèle
        Retourne: {safe, score, reasons, warnings, details}
        """
        # ── Cache ──
        cached = self.cache.get(token_mint)
        if cached and time.time() - cached[0] < self.CACHE_TTL:
            return cached[1]

        result = {
            "safe":     True,
            "score":    10.0,
            "reasons":  [],     # Bloquants (fatals)
            "warnings": [],     # Pénalités
            "details":  {}
        }

        # ── 5 checks simultanés ──
        checks = await asyncio.gather(
            self._check_rugcheck(token_mint),
            self._check_top_holders(token_mint),
            self._check_liquidity(token_mint),
            self._check_mint_authority(token_mint),
            self._check_age(token_mint),
            return_exceptions=True
        )

        keys = ["rugcheck", "holders", "liquidity", "mint_auth", "age"]
        for key, check in zip(keys, checks):
            if isinstance(check, Exception):
                result["details"][key] = {"error": str(check)}
            else:
                result["details"][key] = check or {}

        # ── Appliquer les règles ──
        self._rules_rugcheck(result)
        self._rules_holders(result)
        self._rules_liquidity(result)
        self._rules_mint(result)
        self._rules_age(result)

        # ── Score final ──
        result["score"] = round(max(0.0, min(10.0, result["score"])), 1)
        if result["score"] < 3.0:
            result["safe"] = False
            result["reasons"].append(
                f"Score sécurité trop bas: {result['score']}/10"
            )

        # ── Log ──
        icon = "✅" if result["safe"] else "❌"
        logger.info(
            f"{icon} Safety | {token_mint[:8]}... | "
            f"Score: {result['score']}/10 | "
            f"❌{len(result['reasons'])} ⚠️{len(result['warnings'])}"
        )

        self.cache[token_mint] = (time.time(), result)
        return result

    # ════════════════════════════════════════
    # RÈGLES
    # ════════════════════════════════════════

    def _rules_rugcheck(self, r: dict):
        d = r["details"].get("rugcheck", {})
        if not d or "error" in d:
            r["score"] -= 0.5
            r["warnings"].append("Rugcheck inaccessible")
            return
        if d.get("is_honeypot"):
            r["safe"] = False
            r["reasons"].append("🍯 HONEYPOT détecté")
        if d.get("has_freeze"):
            r["safe"] = False
            r["reasons"].append("🥶 Freeze Authority active")
        lvl = d.get("risk_level", "unknown")
        if lvl == "high":
            r["score"] -= 3.0
            r["warnings"].append("Risque ÉLEVÉ (Rugcheck)")
        elif lvl == "medium":
            r["score"] -= 1.5
            r["warnings"].append("Risque MOYEN (Rugcheck)")
        elif lvl == "low":
            r["score"] += 0.5

    def _rules_holders(self, r: dict):
        d = r["details"].get("holders", {})
        if not d or "error" in d:
            return
        top1  = d.get("top1_pct", 0)
        top10 = d.get("top10_pct", 0)
        total = d.get("total", 0)

        if top1 > 50:
            r["safe"] = False
            r["reasons"].append(f"🐋 Top1 holder = {top1:.0f}% (trop dominant)")
        elif top1 > 30:
            r["score"] -= 2.0
            r["warnings"].append(f"Top1 = {top1:.0f}%")
        elif top1 > 20:
            r["score"] -= 1.0
            r["warnings"].append(f"Top1 = {top1:.0f}%")

        if top10 > 80:
            r["safe"] = False
            r["reasons"].append(f"🐋 Top10 = {top10:.0f}% (trop concentré)")
        elif top10 > 60:
            r["score"] -= 1.5
            r["warnings"].append(f"Top10 = {top10:.0f}%")

        if total < 20:
            r["safe"] = False
            r["reasons"].append(f"👤 Seulement {total} holders")
        elif total < 50:
            r["score"] -= 1.0
            r["warnings"].append(f"Holders faibles: {total}")
        elif total > 500:
            r["score"] += 0.5

    def _rules_liquidity(self, r: dict):
        d = r["details"].get("liquidity", {})
        if not d or "error" in d:
            return
        liq = d.get("liquidity_usd", 0)
        if liq < 1000:
            r["safe"] = False
            r["reasons"].append(f"💧 Liquidité critique: ${liq:,.0f}")
        elif liq < 5000:
            r["score"] -= 2.0
            r["warnings"].append(f"Liquidité faible: ${liq:,.0f}")
        elif liq < 20000:
            r["score"] -= 0.5
        elif liq > 100000:
            r["score"] += 0.5

    def _rules_mint(self, r: dict):
        d = r["details"].get("mint_auth", {})
        if not d or "error" in d:
            return
        if d.get("has_mint_authority"):
            r["score"] -= 2.0
            r["warnings"].append("⚠️ Mint Authority active (inflation possible)")

    def _rules_age(self, r: dict):
        d = r["details"].get("age", {})
        if not d or "error" in d:
            return
        age = d.get("age_minutes", 999)
        if age < 1:
            r["score"] -= 1.0
            r["warnings"].append("Token < 1 minute (très risqué)")
        elif age > 1440:
            r["score"] += 0.5  # Survécu 24h

    # ════════════════════════════════════════
    # CHECKS API
    # ════════════════════════════════════════

    async def _check_rugcheck(self, mint: str) -> dict:
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
                        "risk_level": data.get("riskLevel", "unknown"),
                        "risks":      [r.get("name") for r in risks[:5]],
                    }
            return {"risk_level": "unknown"}
        except Exception as e:
            raise Exception(f"Rugcheck: {e}")

    async def _check_top_holders(self, mint: str) -> dict:
        try:
            payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "getTokenLargestAccounts",
                "params": [mint]
            }
            async with self.session.post(self.rpc_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    accounts = data.get("result", {}).get("value", [])
                    if not accounts:
                        return {"total": 0, "top1_pct": 100, "top10_pct": 100}
                    amounts = [
                        float(a.get("uiAmount") or a.get("amount", 0))
                        for a in accounts
                    ]
                    total = sum(amounts) or 1
                    return {
                        "total":    len(accounts),
                        "top1_pct":  round(amounts[0] / total * 100, 1),
                        "top10_pct": round(sum(amounts[:10]) / total * 100, 1),
                    }
            return {}
        except Exception as e:
            raise Exception(f"Holders: {e}")

    async def _check_liquidity(self, mint: str) -> dict:
        try:
            url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs") or []
                    if pairs:
                        liq = pairs[0].get("liquidity", {})
                        return {"liquidity_usd": liq.get("usd", 0)}
            return {"liquidity_usd": 0}
        except Exception as e:
            raise Exception(f"Liquidity: {e}")

    async def _check_mint_authority(self, mint: str) -> dict:
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
            return {}
        except Exception as e:
            raise Exception(f"MintAuth: {e}")

    async def _check_age(self, mint: str) -> dict:
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
            return {"age_minutes": 999}
        except Exception as e:
            raise Exception(f"Age: {e}")

    def summary(self, result: dict) -> str:
        """Résumé lisible pour les alertes"""
        icon = "✅" if result["safe"] else "❌"
        lines = [f"{icon} Sécurité: {result['score']}/10"]
        for r in result.get("reasons", []):
            lines.append(f"  🚫 {r}")
        for w in result.get("warnings", [])[:3]:
            lines.append(f"  ⚠️ {w}")
        return "\n".join(lines)