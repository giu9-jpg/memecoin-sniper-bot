# modules/early_detector.py — v8.0
# Détecte les tokens ultra-early (< 5 min) avec fort potentiel

import time
import aiohttp
from utils.logger import logger


class EarlyDetector:

    def __init__(self):
        self.session       = None
        self.recent_tokens = {}   # token → première detection
        self.MAX_AGE       = 300   # 5 min max

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # ANALYSE EARLY
    # ═══════════════════════════════════════════════════

    async def analyze_early_token(
        self, token_address: str, token_data: dict
    ) -> dict | None:
        """
        Analyse rapide pour tokens < 5 min.
        Critères stricts car peu de données disponibles.
        """
        now = time.time()

        # Enregistre première detection
        if token_address not in self.recent_tokens:
            self.recent_tokens[token_address] = now

        age = now - self.recent_tokens[token_address]

        # Skip si trop vieux pour l'early
        if age > self.MAX_AGE:
            return None

        # ── Score early (0-10) ────────────────────────
        score   = 5.0
        signals = []

        # 1. Nom/Symbol suspect (rugs classiques)
        name   = token_data.get("name", "").lower()
        symbol = token_data.get("symbol", "").lower()

        # Blacklist de noms
        BAD_KEYWORDS = [
            "test", "scam", "rug", "fake",
            "elon", "trump", "biden",   # trop cliché
        ]
        if any(k in name or k in symbol for k in BAD_KEYWORDS):
            score -= 3.0
            signals.append("🚨 Nom suspect")

        # 2. Longueur du symbol
        if len(symbol) < 2 or len(symbol) > 10:
            score -= 1.0
            signals.append(f"⚠️ Symbol étrange : {symbol}")

        # 3. Bonus si nom court et clean
        if 3 <= len(symbol) <= 6 and symbol.isalpha():
            score += 1.0
            signals.append(f"✅ Symbol propre : {symbol}")

        # 4. Vérifie les métadonnées (via DexScreener)
        try:
            metadata = await self._quick_check(token_address)
            if metadata:
                # Bonus si socials présents
                if metadata.get("has_socials"):
                    score += 2.0
                    signals.append("✅ Socials présents")

                # Bonus si liquidity > $5k
                liq = metadata.get("liquidity", 0)
                if liq > 20_000:
                    score += 2.0
                    signals.append(f"🔥 Liquidité solide : ${liq:,.0f}")
                elif liq > 10_000:
                    score += 1.5
                    signals.append(f"✅ Liquidité OK : ${liq:,.0f}")
                elif liq > 5_000:
                    score += 1.0
                    signals.append(f"🟡 Liquidité basique : ${liq:,.0f}")
                elif liq < 1_000:
                    score -= 2.0
                    signals.append(f"🔴 Liquidité DANGER : ${liq:,.0f}")

                # Bonus si volume immédiat
                vol_5m = metadata.get("volume_5m", 0)
                if vol_5m > 50_000:
                    score += 2.5
                    signals.append(f"🚀 Volume EXPLOSION : ${vol_5m:,.0f}")
                elif vol_5m > 20_000:
                    score += 2.0
                    signals.append(f"📈 Bon volume : ${vol_5m:,.0f}")
                elif vol_5m > 5_000:
                    score += 1.0
                    signals.append(f"📊 Volume OK : ${vol_5m:,.0f}")

                # Buy pressure
                txns_5m = metadata.get("txns_5m", {})
                buys    = txns_5m.get("buys", 0)
                sells   = txns_5m.get("sells", 1)
                if buys >= 20 and sells == 0:
                    score += 2.5
                    signals.append(f"🟢 {buys} buys / 0 sells !")
                elif buys > sells * 3:
                    score += 1.5
                    signals.append(f"🟢 Pression : {buys}b/{sells}s")

        except Exception as e:
            logger.debug(f"[EARLY] Erreur check : {e}")

        # Cap
        score = max(0.0, min(10.0, score))

        # Retourne seulement si score interessant
        if score >= 7.0:
            return {
                "address":    token_address,
                "score":      round(score, 1),
                "signals":    signals,
                "age_sec":    int(age),
                "is_early":   True,
            }

        return None

    async def _quick_check(self, address: str) -> dict:
        """Vérification rapide via DexScreener."""
        try:
            session = await self._get_session()
            url = (
                f"https://api.dexscreener.com/latest/dex/tokens/{address}"
            )
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json()

            pairs = data.get("pairs") or []
            sol_pairs = [
                p for p in pairs
                if p.get("chainId") == "solana"
            ]
            if not sol_pairs:
                return {}

            pair = max(
                sol_pairs,
                key=lambda p: p.get("liquidity", {}).get("usd", 0)
            )

            info = pair.get("info", {})
            volume = pair.get("volume", {})
            txns   = pair.get("txns", {})

            return {
                "has_socials": bool(
                    info.get("socials") or info.get("websites")
                ),
                "liquidity":   pair.get("liquidity", {}).get("usd", 0),
                "volume_5m":   volume.get("m5", 0),
                "volume_1h":   volume.get("h1", 0),
                "txns_5m":     txns.get("m5", {}),
            }
        except Exception:
            return {}

    def cleanup_old(self):
        """Nettoie les tokens > 5 min."""
        now = time.time()
        old = [
            addr for addr, t in self.recent_tokens.items()
            if now - t > self.MAX_AGE
        ]
        for addr in old:
            del self.recent_tokens[addr]

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()