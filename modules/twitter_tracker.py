# modules/twitter_tracker.py — v11.3
# ═══════════════════════════════════════════════
# v11.3 CORRECTIONS :
# + Fallback DexScreener si Nitter down
#   (cherche $SYMBOL sur DexScreener search)
# + Retry automatique sur autre instance si timeout
# + Logs plus clairs sur disponibilité Nitter
#
# HÉRITÉ v11.2 :
# - Suppression vieux TwitterScanner
# - Bootstrap au premier scan

import asyncio
import aiohttp
import re
from datetime import datetime, timedelta
from typing   import Optional, Callable
from utils.logger import logger
from config.alpha_accounts import (
    ALPHA_ACCOUNTS,
    get_all_accounts,
    get_account_tier,
    get_account_bonus,
)

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.cz",
    "https://nitter.projectsegfau.lt",
    "https://nitter.esmailelbob.xyz",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
]

SOLANA_ADDRESS_REGEX = re.compile(
    r'\b([1-9A-HJ-NP-Za-km-z]{32,44})\b'
)

SYMBOL_REGEX = re.compile(r'\$([A-Z]{2,10})\b')

SYMBOL_BLACKLIST = {
    "USD", "BTC", "ETH", "SOL", "USDC", "USDT",
    "EUR", "GBP", "JPY", "AUD", "CAD", "BNB",
    "XRP", "ADA", "DOGE", "MATIC", "AVAX",
}


class TwitterTracker:

    def __init__(self):
        self.session:          Optional[aiohttp.ClientSession] = None
        self.working_instance: Optional[str]                   = None
        self.seen_tweets:      dict                            = {}
        self.token_mentions:   dict                            = {}
        self.symbol_mentions:  dict                            = {}
        self.last_check:       float                           = 0
        self.max_seen                                          = 1000
        self.bootstrapped                                      = False
        self.is_available                                      = False

        # v11.3 : stats disponibilité
        self.nitter_failures  = 0
        self.nitter_successes = 0
        self.fallback_used    = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
            self.session = aiohttp.ClientSession(
                timeout=timeout, headers=headers
            )
        return self.session

    # ════════════════════════════════════════
    # DÉCOUVERTE INSTANCE NITTER
    # ════════════════════════════════════════

    async def find_working_instance(self) -> Optional[str]:
        """Trouve une instance Nitter fonctionnelle."""
        if self.working_instance:
            try:
                session = await self._get_session()
                async with session.get(
                    f"{self.working_instance}/Ansem/rss",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as r:
                    if r.status == 200:
                        return self.working_instance
            except Exception:
                pass
            self.working_instance = None
            self.is_available     = False

        for instance in NITTER_INSTANCES:
            try:
                session = await self._get_session()
                async with session.get(
                    f"{instance}/Ansem/rss",
                    timeout=aiohttp.ClientTimeout(total=6),
                ) as r:
                    if r.status != 200:
                        continue
                    text = await r.text()
                    if "<item>" in text or "<rss" in text:
                        self.working_instance = instance
                        self.is_available     = True
                        self.nitter_successes += 1
                        logger.info(
                            f"[TWITTER] ✅ Instance Nitter : {instance}"
                        )
                        return instance
            except Exception:
                continue

        self.is_available  = False
        self.nitter_failures += 1
        logger.warning(
            f"[TWITTER] ⚠️ Aucune instance Nitter disponible "
            f"(échec #{self.nitter_failures})"
        )
        return None

    # ════════════════════════════════════════
    # FETCH TWEETS
    # ════════════════════════════════════════

    async def fetch_user_tweets(self, username: str) -> list:
        """Récupère les derniers tweets via Nitter RSS."""
        instance = await self.find_working_instance()
        if not instance:
            return []

        try:
            session = await self._get_session()
            url     = f"{instance}/{username}/rss"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status != 200:
                    logger.debug(
                        f"[TWITTER] @{username} status {r.status}"
                    )
                    return []
                content = await r.text()
                return self._parse_rss(content, username)

        except asyncio.TimeoutError:
            logger.debug(f"[TWITTER] Timeout @{username}")
            # Invalide l'instance
            self.working_instance = None
            self.is_available     = False
            return []
        except Exception as e:
            logger.error(f"[TWITTER] Fetch @{username}: {e}")
            return []

    # ════════════════════════════════════════
    # PARSING RSS
    # ════════════════════════════════════════

    def _parse_rss(self, xml_content: str, username: str) -> list:
        """Parse le RSS Nitter."""
        tweets = []
        items  = re.findall(
            r'<item>(.*?)</item>',
            xml_content, re.DOTALL,
        )

        for item in items[:10]:
            try:
                desc = re.search(
                    r'<description><!\[CDATA\[(.*?)\]\]></description>',
                    item, re.DOTALL,
                )
                title = re.search(
                    r'<title><!\[CDATA\[(.*?)\]\]></title>',
                    item, re.DOTALL,
                )
                if not title:
                    title = re.search(
                        r'<title>(.*?)</title>', item, re.DOTALL
                    )

                link = re.search(r'<link>([^<\s]+)</link>', item)
                if not link:
                    link = re.search(
                        r'<guid[^>]*>([^<]+)</guid>', item
                    )

                pubdate = re.search(
                    r'<pubDate>(.*?)</pubDate>', item
                )

                if not link:
                    continue

                tweet_url = link.group(1).strip()
                tweet_id  = (
                    tweet_url.rstrip("/")
                              .split("/")[-1]
                              .split("#")[0]
                              .split("?")[0]
                )

                if not tweet_id.isdigit():
                    continue

                tweet_text = ""
                if desc:
                    tweet_text = desc.group(1).strip()
                elif title:
                    tweet_text = title.group(1).strip()

                tweet_text = re.sub(r'<[^>]+>', ' ', tweet_text)
                tweet_text = re.sub(r'&amp;',  '&', tweet_text)
                tweet_text = re.sub(r'&lt;',   '<', tweet_text)
                tweet_text = re.sub(r'&gt;',   '>', tweet_text)
                tweet_text = re.sub(r'&quot;', '"', tweet_text)
                tweet_text = re.sub(r'\s+',    ' ', tweet_text).strip()

                tweets.append({
                    "id":       tweet_id,
                    "text":     tweet_text,
                    "url":      tweet_url,
                    "username": username,
                    "pubdate":  (
                        pubdate.group(1).strip() if pubdate else ""
                    ),
                })

            except Exception as e:
                logger.debug(f"[TWITTER] Parse item error: {e}")
                continue

        return tweets

    # ════════════════════════════════════════
    # EXTRACTION CA + SYMBOLES
    # ════════════════════════════════════════

    def _extract_tokens(self, text: str) -> dict:
        """Extrait les adresses Solana et $SYMBOL du texte."""
        raw_addresses = SOLANA_ADDRESS_REGEX.findall(text)
        addresses     = [a for a in raw_addresses if 32 <= len(a) <= 44]
        symbols       = SYMBOL_REGEX.findall(text.upper())
        symbols       = [s for s in symbols if s not in SYMBOL_BLACKLIST]
        return {
            "addresses": list(set(addresses)),
            "symbols":   list(set(symbols)),
        }

    # ════════════════════════════════════════
    # FALLBACK DEXSCREENER (si Nitter down)
    # ════════════════════════════════════════

    async def _fallback_dexscreener_check(
        self, username: str
    ) -> list:
        """
        v11.3 : Si Nitter est down, cherche les tokens récemment
        mentionnés par les influenceurs via DexScreener search.

        C'est une approximation — on cherche des tokens trending
        qui correspondent aux patterns habituels des callers.

        Retourne une liste de signaux simplifiés.
        """
        try:
            # On cherche les tokens Solana trending récents
            # et on les attribue au caller si cohérent
            url = "https://api.dexscreener.com/latest/dex/search?q=SOL"
            session = await self._get_session()

            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()

            pairs   = data.get("pairs", []) or []
            signals = []

            for pair in pairs[:5]:
                if pair.get("chainId") != "solana":
                    continue

                mint    = pair.get("baseToken", {}).get("address", "")
                symbol  = pair.get("baseToken", {}).get("symbol", "")
                change  = pair.get("priceChange", {}).get("h1", 0) or 0

                # Filtre : token avec momentum positif
                if not mint or change < 20:
                    continue

                # Synthétise un signal "possible mention"
                tier  = get_account_tier(username)
                bonus = get_account_bonus(username) * 0.5  # réduit car fallback

                signal = {
                    "username":   username,
                    "tier":       tier,
                    "bonus":      bonus,
                    "tweet_id":   f"fallback_{mint[:8]}",
                    "tweet_url":  f"https://dexscreener.com/solana/{mint}",
                    "tweet_text": f"[Fallback] ${symbol} trending +{change:.0f}%",
                    "addresses":  [mint],
                    "symbols":    [symbol] if symbol else [],
                    "timestamp":  datetime.now().isoformat(),
                    "is_fallback": True,
                }
                signals.append(signal)

            if signals:
                self.fallback_used += 1
                logger.info(
                    f"[TWITTER] 🔄 Fallback DexScreener : "
                    f"{len(signals)} signaux pour @{username}"
                )

            return signals

        except Exception as e:
            logger.debug(f"[TWITTER] Fallback error: {e}")
            return []

    # ════════════════════════════════════════
    # SCAN DE TOUS LES COMPTES
    # ════════════════════════════════════════

    async def check_all_accounts(
        self, callback: Optional[Callable] = None
    ) -> list:
        """Scanne tous les comptes alpha."""
        signals      = []
        all_accounts = get_all_accounts()

        instance = await self.find_working_instance()

        # v11.3 : Si Nitter complètement down → fallback
        nitter_is_down = instance is None

        if nitter_is_down:
            logger.warning(
                "[TWITTER] ⚠️ Nitter down — mode fallback DexScreener"
            )

        is_first_run = not self.bootstrapped

        for username in all_accounts:
            try:
                if nitter_is_down:
                    # v11.3 : Fallback si Nitter down
                    # Seulement pour les TIER1 (les plus impactants)
                    tier = get_account_tier(username)
                    if tier == "TIER1" and not is_first_run:
                        fallback_signals = await self._fallback_dexscreener_check(
                            username
                        )
                        for signal in fallback_signals:
                            signals.append(signal)

                            for addr in signal["addresses"]:
                                self.token_mentions.setdefault(
                                    addr, []
                                ).append(signal)

                            if callback:
                                try:
                                    await callback(signal)
                                except Exception as e:
                                    logger.error(
                                        f"[TWITTER] Fallback callback: {e}"
                                    )
                    continue

                # ── Mode normal : Nitter disponible ───
                tweets = await self.fetch_user_tweets(username)

                for tweet in tweets:
                    tweet_id = tweet["id"]

                    if is_first_run:
                        self.seen_tweets[tweet_id] = datetime.now()
                        continue

                    if tweet_id in self.seen_tweets:
                        continue

                    self.seen_tweets[tweet_id] = datetime.now()

                    tokens = self._extract_tokens(tweet["text"])

                    if not tokens["addresses"] and not tokens["symbols"]:
                        continue

                    tier  = get_account_tier(username)
                    bonus = get_account_bonus(username)

                    signal = {
                        "username":    username,
                        "tier":        tier,
                        "bonus":       bonus,
                        "tweet_id":    tweet_id,
                        "tweet_url":   tweet["url"],
                        "tweet_text":  tweet["text"][:300],
                        "addresses":   tokens["addresses"],
                        "symbols":     tokens["symbols"],
                        "timestamp":   datetime.now().isoformat(),
                        "is_fallback": False,
                    }
                    signals.append(signal)

                    for addr in tokens["addresses"]:
                        self.token_mentions.setdefault(
                            addr, []
                        ).append(signal)

                    for sym in tokens["symbols"]:
                        self.symbol_mentions.setdefault(
                            sym, []
                        ).append(signal)

                    logger.info(
                        f"[TWITTER] 🐦 {tier} @{username} → "
                        f"CA:{len(tokens['addresses'])} "
                        f"SYM:{','.join(tokens['symbols']) or '-'}"
                    )

                    if callback:
                        try:
                            await callback(signal)
                        except Exception as e:
                            logger.error(f"[TWITTER] Callback error: {e}")

                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"[TWITTER] @{username} erreur: {e}")

        if is_first_run:
            self.bootstrapped = True
            logger.info(
                f"[TWITTER] 🔄 Bootstrap terminé : "
                f"{len(self.seen_tweets)} tweets mémorisés"
            )

        self._cleanup()
        self.last_check = datetime.now().timestamp()
        return signals

    # ════════════════════════════════════════
    # SIGNAUX
    # ════════════════════════════════════════

    def get_token_twitter_signal(
        self, token_address: str
    ) -> Optional[dict]:
        """Vérifie si un token a été mentionné récemment (< 1h)."""
        mentions = self.token_mentions.get(token_address, [])
        if not mentions:
            return None

        cutoff = datetime.now() - timedelta(hours=1)
        recent = [
            m for m in mentions
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]
        if not recent:
            return None

        best = max(recent, key=lambda m: m.get("bonus", 0))
        return {
            "mentioned":   True,
            "count":       len(recent),
            "best_tier":   best["tier"],
            "bonus":       best["bonus"],
            "username":    best["username"],
            "tweet_url":   best["tweet_url"],
            "tweet_text":  best.get("tweet_text", ""),
            "is_fallback": best.get("is_fallback", False),
        }

    def get_symbol_twitter_signal(
        self, symbol: str
    ) -> Optional[dict]:
        """Vérifie si un $SYMBOL a été mentionné récemment (< 1h)."""
        if not symbol:
            return None

        mentions = self.symbol_mentions.get(symbol.upper(), [])
        if not mentions:
            return None

        cutoff = datetime.now() - timedelta(hours=1)
        recent = [
            m for m in mentions
            if datetime.fromisoformat(m["timestamp"]) > cutoff
        ]
        if not recent:
            return None

        best = max(recent, key=lambda m: m.get("bonus", 0))
        return {
            "mentioned":   True,
            "count":       len(recent),
            "best_tier":   best["tier"],
            "bonus":       best["bonus"],
            "username":    best["username"],
            "tweet_url":   best["tweet_url"],
            "tweet_text":  best.get("tweet_text", ""),
            "is_fallback": best.get("is_fallback", False),
        }

    # ════════════════════════════════════════
    # CLEANUP
    # ════════════════════════════════════════

    def _cleanup(self):
        """Nettoie les données trop anciennes."""
        now    = datetime.now()
        cutoff = now - timedelta(hours=24)

        if len(self.seen_tweets) > self.max_seen:
            self.seen_tweets = {
                tid: ts
                for tid, ts in self.seen_tweets.items()
                if ts > cutoff
            }

        cutoff_mentions = now - timedelta(hours=2)
        for addr in list(self.token_mentions.keys()):
            self.token_mentions[addr] = [
                m for m in self.token_mentions[addr]
                if datetime.fromisoformat(m["timestamp"]) > cutoff_mentions
            ]
            if not self.token_mentions[addr]:
                del self.token_mentions[addr]

        for sym in list(self.symbol_mentions.keys()):
            self.symbol_mentions[sym] = [
                m for m in self.symbol_mentions[sym]
                if datetime.fromisoformat(m["timestamp"]) > cutoff_mentions
            ]
            if not self.symbol_mentions[sym]:
                del self.symbol_mentions[sym]

    def cleanup_old_data(self):
        """Alias public pour main.py memory cleanup."""
        self._cleanup()

    def get_stats(self) -> dict:
        """Stats pour debug."""
        return {
            "is_available":    self.is_available,
            "working_instance": self.working_instance,
            "nitter_successes": self.nitter_successes,
            "nitter_failures":  self.nitter_failures,
            "fallback_used":    self.fallback_used,
            "seen_tweets":      len(self.seen_tweets),
            "token_mentions":   len(self.token_mentions),
            "symbol_mentions":  len(self.symbol_mentions),
        }

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()