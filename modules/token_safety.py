# modules/token_safety.py — v1.5 RISK-GUARD
# ═══════════════════════════════════════════════
# Plus strict pour réduire les pertes -80/-100 :
# + seuil sécurité configurable et relevé par défaut à 6.5
# + filtre liquidité plus strict
# + filtre concentration top holder plus strict
# + pénalité no-social + faible liquidité
# + cache court, logs compatibles dashboard

from __future__ import annotations

import asyncio
import aiohttp
import os
import re
import time
from typing import Any

from utils.logger import get_logger


logger = get_logger("token_safety")


def _env_float(
    name: str,
    default: float,
) -> float:
    try:
        return float(
            str(
                os.getenv(name, str(default))
            ).replace(",", ".")
        )
    except Exception:
        return float(default)


def _env_int(
    name: str,
    default: int,
) -> int:
    try:
        return int(
            float(
                str(
                    os.getenv(name, str(default))
                ).replace(",", ".")
            )
        )
    except Exception:
        return int(default)


SUSPICIOUS_NAME_PATTERNS = [
    r"(inu|elon|trump|biden|pepe2|shib2|doge2)",
    r"(assfarted|memehouse|fartcoon|psyopcoon)",
    r"(safe|fair|based|legit|rewards)",
    r"(official|cto|community takeover)",
    r"\d{4,}",
]


GENERIC_NAME_WORDS = {
    "coin",
    "token",
    "inu",
    "doge",
    "cat",
    "fish",
    "ai",
    "gpt",
    "meme",
    "moon",
    "safe",
    "pump",
}


class TokenSafety:
    MIN_SAFE_SCORE = _env_float(
        "SAFETY_MIN_SCORE",
        6.5,
    )

    MIN_AGE_MINUTES = _env_float(
        "SAFETY_MIN_AGE_MINUTES",
        3.0,
    )

    BLOCK_LIQ_ZERO_AFTER_MIN = _env_float(
        "SAFETY_BLOCK_LIQ_ZERO_AFTER_MIN",
        8.0,
    )

    VERY_LOW_LIQ = _env_float(
        "SAFETY_VERY_LOW_LIQUIDITY",
        8000.0,
    )

    LOW_LIQ = _env_float(
        "SAFETY_LOW_LIQUIDITY",
        15000.0,
    )

    HEALTHY_LIQ = _env_float(
        "SAFETY_HEALTHY_LIQUIDITY",
        50000.0,
    )

    BLOCK_TOP_HOLDER_PCT = _env_float(
        "SAFETY_BLOCK_TOP_HOLDER_PCT",
        30.0,
    )

    WARN_TOP_HOLDER_PCT = _env_float(
        "SAFETY_WARN_TOP_HOLDER_PCT",
        22.0,
    )

    BLOCK_TOP10_PCT = _env_float(
        "SAFETY_BLOCK_TOP10_PCT",
        85.0,
    )

    def __init__(
        self,
        rpc_url: str,
    ):
        self.rpc_url = rpc_url
        self.session: aiohttp.ClientSession | None = None

        self.cache: dict[str, tuple[float, dict]] = {}
        self.CACHE_TTL = _env_int("SAFETY_CACHE_TTL", 60)

        self.total_checked = 0
        self.total_blocked = 0

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=8)
        )

        logger.info(
            f"✅ TokenSafety v1.5 démarré "
            f"(min_score={self.MIN_SAFE_SCORE})"
        )

    async def stop(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def full_safety_check(
        self,
        token_mint: str,
    ) -> dict:
        cached = self.cache.get(token_mint)

        if cached and time.time() - cached[0] < self.CACHE_TTL:
            return cached[1]

        self.total_checked += 1

        result = {
            "safe": True,
            "score": 10.0,
            "reasons": [],
            "warnings": [],
            "details": {},
        }

        checks = await asyncio.gather(
            self._check_dexscreener(token_mint),
            self._check_rugcheck(token_mint),
            self._check_mint_authority(token_mint),
            return_exceptions=True,
        )

        for key, check in zip(
            ["dex", "rugcheck", "mint_auth"],
            checks,
        ):
            if isinstance(check, Exception):
                result["details"][key] = {
                    "error": str(check)
                }
            else:
                result["details"][key] = check or {}

        self._rules_dex(result)
        self._rules_rugcheck(result)
        self._rules_mint(result)
        self._rules_name(result)
        self._rules_socials(result)
        self._rules_concentration(result)
        self._rules_combo(result)

        result["score"] = round(
            max(0.0, min(10.0, result["score"])),
            1,
        )

        if result["score"] < self.MIN_SAFE_SCORE:
            result["safe"] = False

            if not result["reasons"]:
                result["reasons"].append(
                    f"Score sécurité insuffisant: "
                    f"{result['score']}/10"
                )

        if not result["safe"]:
            self.total_blocked += 1

        icon = "✅" if result["safe"] else "❌"

        logger.info(
            f"{icon} Safety v1.5 | {token_mint[:8]}... | "
            f"Score: {result['score']}/10 | "
            f"❌{len(result['reasons'])} "
            f"⚠️{len(result['warnings'])}"
        )

        self.cache[token_mint] = (time.time(), result)

        return result

    def _dex(
        self,
        result: dict,
    ) -> dict:
        return result["details"].get("dex", {}) or {}

    def _rug(
        self,
        result: dict,
    ) -> dict:
        return result["details"].get("rugcheck", {}) or {}

    def _rules_dex(
        self,
        result: dict,
    ):
        dex = self._dex(result)

        liq = float(dex.get("liquidity_usd", 0) or 0)
        age = float(dex.get("age_minutes", 999) or 999)
        market_cap = float(dex.get("market_cap", 0) or 0)

        # Age
        if age < self.MIN_AGE_MINUTES:
            result["safe"] = False
            result["score"] -= 3.5
            result["reasons"].append(
                f"🔴 Token trop jeune: {age:.1f}min"
            )

        elif age < 5:
            result["score"] -= 1.2
            result["warnings"].append(
                f"⚠️ Très jeune: {age:.1f}min"
            )

        # Liquidité
        if liq == 0:
            if age < 5:
                result["score"] -= 1.5
                result["warnings"].append(
                    "Liquidité non visible (bonding curve)"
                )

            elif age < self.BLOCK_LIQ_ZERO_AFTER_MIN:
                result["score"] -= 3.0
                result["warnings"].append(
                    f"⚠️ Liq $0 après {age:.1f}min"
                )

            else:
                result["safe"] = False
                result["score"] -= 6.0
                result["reasons"].append(
                    f"🔴 Liquidité $0 après {age:.0f}min"
                )

        elif liq < self.VERY_LOW_LIQ:
            if age > 8:
                result["safe"] = False
                result["reasons"].append(
                    f"🔴 Liquidité trop faible: ${liq:,.0f}"
                )

            result["score"] -= 3.5

        elif liq < self.LOW_LIQ:
            result["score"] -= 1.8
            result["warnings"].append(
                f"⚠️ Liquidité faible: ${liq:,.0f}"
            )

        elif liq < 20_000:
            result["score"] -= 0.6

        elif liq >= self.HEALTHY_LIQ:
            result["score"] += 0.4

        # MarketCap/liquidity ratio
        if market_cap and liq and market_cap / max(liq, 1) > 25:
            result["score"] -= 1.0
            result["warnings"].append("⚠️ MC/Liq élevé")

    def _rules_rugcheck(
        self,
        result: dict,
    ):
        rug = self._rug(result)

        if not rug or "error" in rug:
            result["score"] -= 0.5
            return

        if rug.get("is_honeypot"):
            result["safe"] = False
            result["score"] -= 10.0
            result["reasons"].append("🍯 HONEYPOT détecté")

        if rug.get("has_freeze"):
            result["safe"] = False
            result["score"] -= 10.0
            result["reasons"].append("🥶 Freeze Authority active")

        risk_count = int(rug.get("risk_count", 0) or 0)

        if risk_count >= 4:
            result["safe"] = False
            result["score"] -= 3.0
            result["reasons"].append(
                f"🔴 {risk_count} risques RugCheck"
            )

        elif risk_count >= 2:
            result["score"] -= 2.0
            result["warnings"].append(
                f"⚠️ {risk_count} risques RugCheck"
            )

        elif risk_count >= 1:
            result["score"] -= 0.8

    def _rules_mint(
        self,
        result: dict,
    ):
        mint_auth = result["details"].get("mint_auth", {}) or {}

        if mint_auth.get("has_mint_authority"):
            result["score"] -= 2.0
            result["warnings"].append(
                "⚠️ Mint Authority active"
            )

    def _rules_name(
        self,
        result: dict,
    ):
        dex = self._dex(result)

        name = str(dex.get("name", "") or "").lower()
        symbol = str(dex.get("symbol", "") or "").lower()

        if not name and not symbol:
            return

        text = f"{name} {symbol}"

        suspicious_count = sum(
            1
            for pattern in SUSPICIOUS_NAME_PATTERNS
            if re.search(pattern, text, re.IGNORECASE)
        )

        if suspicious_count >= 2:
            result["score"] -= 3.0
            result["warnings"].append(
                f"⚠️ Nom très suspect: {dex.get('symbol', '?')}"
            )

        elif suspicious_count == 1:
            result["score"] -= 1.0
            result["warnings"].append(
                f"⚠️ Nom suspect: {dex.get('symbol', '?')}"
            )

        words = re.split(r"[^a-zA-Z0-9]+", text)

        generic_count = sum(
            1
            for word in words
            if word in GENERIC_NAME_WORDS
        )

        if generic_count >= 2:
            result["score"] -= 1.0
            result["warnings"].append("⚠️ Nom générique")

    def _rules_socials(
        self,
        result: dict,
    ):
        dex = self._dex(result)

        if not dex.get("has_socials", False):
            result["score"] -= 1.2
            result["warnings"].append(
                "⚠️ Aucun social détecté"
            )

        else:
            result["score"] += 0.3

    def _rules_concentration(
        self,
        result: dict,
    ):
        rug = self._rug(result)

        top_pct = float(rug.get("top_holder_pct", 0) or 0)
        top10 = float(rug.get("top_10_holders_pct", 0) or 0)

        if top_pct > self.BLOCK_TOP_HOLDER_PCT:
            result["safe"] = False
            result["score"] -= 6.0
            result["reasons"].append(
                f"🔴 Top holder: {top_pct:.0f}% "
                f"(rug facile)"
            )

        elif top_pct > self.WARN_TOP_HOLDER_PCT:
            result["score"] -= 2.0
            result["warnings"].append(
                f"⚠️ Top holder concentré: {top_pct:.0f}%"
            )

        if top10 > self.BLOCK_TOP10_PCT:
            result["safe"] = False
            result["score"] -= 3.0
            result["reasons"].append(
                f"🔴 Top 10 trop concentré: {top10:.0f}%"
            )

        elif top10 > 70:
            result["score"] -= 1.2
            result["warnings"].append(
                f"⚠️ Top 10: {top10:.0f}%"
            )

        elif top10 > 60:
            result["score"] -= 0.5

    def _rules_combo(
        self,
        result: dict,
    ):
        dex = self._dex(result)
        rug = self._rug(result)

        liq = float(dex.get("liquidity_usd", 0) or 0)
        age = float(dex.get("age_minutes", 999) or 999)
        socials = bool(dex.get("has_socials", False))
        top_pct = float(rug.get("top_holder_pct", 0) or 0)

        if not socials and liq < 15_000 and age > 8:
            result["safe"] = False
            result["score"] -= 2.0
            result["reasons"].append(
                "🔴 Faible liquidité + aucun social"
            )

        if liq < 12_000 and top_pct > 20:
            result["score"] -= 1.5
            result["warnings"].append(
                "⚠️ Combo liq faible + concentration"
            )

    async def _check_dexscreener(
        self,
        mint: str,
    ) -> dict:
        try:
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=8)
                )

            url = (
                "https://api.dexscreener.com/latest/dex/tokens/"
                f"{mint}"
            )

            async with self.session.get(url) as resp:
                if resp.status != 200:
                    return {
                        "liquidity_usd": 0,
                    }

                data = await resp.json()
                pairs = data.get("pairs") or []

                if not pairs:
                    return {
                        "liquidity_usd": 0,
                    }

                # On prend la paire la plus liquide.
                pair = max(
                    pairs,
                    key=lambda p: float(
                        (p.get("liquidity") or {}).get(
                            "usd",
                            0,
                        )
                        or 0
                    ),
                )

                created = pair.get("pairCreatedAt", 0)

                age_minutes = 999

                if created:
                    age_minutes = round(
                        (
                            time.time() * 1000
                            - created
                        )
                        / 60000,
                        1,
                    )

                base = pair.get("baseToken", {}) or {}
                info = pair.get("info", {}) or {}

                return {
                    "liquidity_usd": float(
                        (pair.get("liquidity") or {}).get(
                            "usd",
                            0,
                        )
                        or 0
                    ),
                    "market_cap": float(
                        pair.get("marketCap", 0)
                        or pair.get("fdv", 0)
                        or 0
                    ),
                    "age_minutes": age_minutes,
                    "name": base.get("name", ""),
                    "symbol": base.get("symbol", ""),
                    "has_socials": bool(
                        info.get("socials", [])
                        or info.get("websites", [])
                    ),
                }

        except Exception:
            pass

        return {
            "liquidity_usd": 0,
        }

    async def _check_rugcheck(
        self,
        mint: str,
    ) -> dict:
        try:
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=8)
                )

            url = (
                "https://api.rugcheck.xyz/v1/tokens/"
                f"{mint}/report"
            )

            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    risks = data.get("risks", []) or []

                    names = [
                        str(risk.get("name", "")).lower()
                        for risk in risks
                        if isinstance(risk, dict)
                    ]

                    top_holders = data.get("topHolders", []) or []

                    pcts = [
                        float(holder.get("pct", 0) or 0)
                        for holder in top_holders
                        if isinstance(holder, dict)
                    ]

                    return {
                        "is_honeypot": any(
                            item in names
                            for item in [
                                "honeypot",
                                "trading disabled",
                            ]
                        ),
                        "has_freeze": any(
                            "freeze" in item
                            for item in names
                        ),
                        "risk_count": len(risks),
                        "top_holder_pct": (
                            pcts[0] if pcts else 0
                        ),
                        "top_10_holders_pct": (
                            sum(pcts[:10]) if pcts else 0
                        ),
                    }

        except Exception:
            pass

        return {}

    async def _check_mint_authority(
        self,
        mint: str,
    ) -> dict:
        try:
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=8)
                )

            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAccountInfo",
                "params": [
                    mint,
                    {
                        "encoding": "jsonParsed",
                    },
                ],
            }

            async with self.session.post(
                self.rpc_url,
                json=payload,
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
                            info.get("mintAuthority")
                            is not None
                        )
                    }

        except Exception:
            pass

        return {}

    def summary(
        self,
        result: dict,
    ) -> str:
        icon = "✅" if result.get("safe") else "❌"

        lines = [
            f"{icon} Sécurité: {result.get('score', 0)}/10"
        ]

        for reason in result.get("reasons", []):
            lines.append(f"🚫 {reason}")

        for warning in result.get("warnings", []):
            lines.append(f"⚠️ {warning}")

        lines.append(
            f"\n📊 Checkés: {self.total_checked} | "
            f"Bloqués: {self.total_blocked} "
            f"({self.total_blocked / max(self.total_checked, 1) * 100:.0f}%)"
        )

        return "\n".join(lines)