# modules/early_detector.py — v9.1 FIXED
# FIX : cleanup_old() et cleanup_old_data() les deux présents
# FIX : MAX_AGE utilisé en secondes partout
# FIX : protection si token_data est None

import time
import aiohttp
from utils.logger import logger


BAD_KEYWORDS = [
    "test", "scam", "rug", "fake",
    "elon", "trump", "biden",
    "presale", "airdrop",
]

MAX_AGE_SECONDS = 300   # 5 minutes


class EarlyDetector:

    def __init__(self):
        self.session       = None
        self.recent_tokens = {}   # {address: first_seen_timestamp}

    async def _get_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    # ═══════════════════════════════════════════════════
    # ANALYSE EARLY
    # ═══════════════════════════════════════════════════

    async def analyze_early_token(
        self,
        token_address: str,
        token_data:    dict | None = None,
    ) -> dict:
        """
        Analyse rapide pour tokens < 5 min.
        FIX : token_data peut être None sans planter.
        """
        now        = time.time()
        token_data = token_data or {}

        # Enregistre la première détection
        if token_address not in self.recent_tokens:
            self.recent_tokens[token_address] = now

        age = now - self.recent_tokens[token_address]

        # Résultat par défaut
        result = {
            "is_early": age < MAX_AGE_SECONDS,
            "score":    0.0,
            "signals":  [],
            "bonus":    0.0,
            "age_sec":  int(age),
            "message":  "",
        }

        if age > MAX_AGE_SECONDS:
            return result

        score   = 5.0
        signals = []

        # ── 1. Nom / Symbol ───────────────────────────
        name   = str(token_data.get("name")   or "").lower()
        symbol = str(token_data.get("symbol") or "").lower()

        if any(k in name or k in symbol for k in BAD_KEYWORDS):
            score -= 3.0
            signals.append("🚨 Nom suspect")

        # ── 2. Longueur du symbol ─────────────────────
        sym_clean = symbol.replace("_", "").replace("-", "")
        if len(sym_clean) < 2 or len(symbol) > 10:
            score -= 1.0
            signals.append("⚠️ Symbol étrange")
        elif 3 <= len(symbol) <= 6 and sym_clean.isalpha():
            score += 1.0
            signals.append("✅ Symbol propre")

        # ── 3. Check rapide DexScreener ───────────────
        try:
            metadata = await self._quick_check(token_address)
            if metadata:
                # Socials
                if metadata.get("has_socials"):
                    score += 2.0
                    signals.append("✅ Socials présents")

                # Liquidité
                liq = float(metadata.get("liquidity", 0) or 0)
                if liq > 20_000:
                    score += 2.0
                    signals.append(f"🔥 Liq solide : ${liq:,.0f}")
                elif liq > 10_000:
                    score += 1.5
                    signals.append(f"✅ Liq OK : ${liq:,.0f}")
                elif liq > 5_000:
                    score += 1.0
                    signals.append(f"🟡 Liq basique : ${liq:,.0f}")
                elif 0 < liq < 1_000:
                    score -= 2.0
                    signals.append(f"🔴 Liq DANGER : ${liq:,.0f}")

                # Volume 5m
                vol_5m = float(metadata.get("volume_5m", 0) or 0)
                if vol_5m > 50_000:
                    score += 2.5
                    signals.append("🚀 Vol EXPLOSION")
                elif vol_5m > 20_000:
                    score += 2.0
                    signals.append("📈 Bon volume")
                elif vol_5m > 5_000:
                    score += 1.0
                    signals.append("📊 Vol OK")

                # Buy pressure
                txns_5m = metadata.get("txns_5m", {}) or {}
                buys    = int(txns_5m.get("buys",  0))
                sells   = int(txns_5m.get("sells", 0))
                if buys >= 20 and sells == 0:
                    score += 2.5
                    signals.append(f"🟢 {buys} buys / 0 sells")
                elif buys > 0 and buys > sells * 3:
                    score += 1.5
                    signals.append(f"🟢 Pression : {buys}b/{sells}s")

        except Exception as e:
            logger.debug(f"[EARLY] Erreur check DexScreener: {e}")

        # Cap score
        score = max(0.0, min(10.0, score))

        # ── Bonus ──────────────────────────────────────
        bonus   = 0.0
        message = ""

        if score >= 8.5:
            bonus   = 3.0
            message = f"⚡ EARLY GEM détectée ({int(age)}s)"
        elif score >= 7.5:
            bonus   = 2.0
            message = f"⚡ Early prometteur ({int(age)}s)"
        elif score >= 6.5:
            bonus   = 1.0
            message = f"⚡ Early OK ({int(age)}s)"

        result.update({
            "score":   round(score, 1),
            "signals": signals,
            "bonus":   bonus,
            "message": message,
        })

        return result

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

            pairs     = data.get("pairs") or []
            sol_pairs = [
                p for p in pairs
                if p.get("chainId") == "solana"
            ]
            if not sol_pairs:
                return {}

            pair   = max(
                sol_pairs,
                key=lambda p: p.get("liquidity", {}).get("usd", 0),
            )
            info   = pair.get("info", {}) or {}
            volume = pair.get("volume", {}) or {}
            txns   = pair.get("txns",   {}) or {}

            return {
                "has_socials": bool(
                    info.get("socials") or info.get("websites")
                ),
                "liquidity":   pair.get("liquidity", {}).get("usd", 0),
                "volume_5m":   volume.get("m5", 0),
                "volume_1h":   volume.get("h1", 0),
                "txns_5m":     txns.get("m5", {}),
            }

        except Exception as e:
            logger.debug(f"[EARLY] _quick_check erreur: {e}")
            return {}

    # ═══════════════════════════════════════════════════
    # CLEANUP
    # FIX : les deux méthodes présentes
    # ═══════════════════════════════════════════════════

    def cleanup_old(self):
        """
        Nettoie les tokens trop vieux.
        Appelé par main.py _run_memory_cleanup().
        """
        now = time.time()
        old = [
            addr for addr, ts in self.recent_tokens.items()
            if now - ts > MAX_AGE_SECONDS
        ]
        for addr in old:
            del self.recent_tokens[addr]

        if old:
            logger.debug(
                f"[EARLY] 🧹 {len(old)} tokens expirés supprimés"
            )

    def cleanup_old_data(self):
        """
        Alias pour compatibilité.
        FIX : les deux noms fonctionnent.
        """
        self.cleanup_old()

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()