# modules/social_score.py — v1.0 CORRIGÉ
# FIX AUDIT :
# - Import Counter inutilisé retiré
# - session vérifiée avant close()
# - Cache nettoyé périodiquement

import asyncio
import aiohttp
import re
import time
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger("social_score")


class SocialScore:

    NITTER_INSTANCES = [
        "https://nitter.net",
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.projectsegfau.lt",
    ]

    CACHE_TTL = 300

    POSITIVE_KEYWORDS = {
        "moon", "gem", "100x", "1000x", "pump", "buy", "bullish",
        "🚀", "💎", "🌙", "🔥", "ape", "aping", "based",
        "insane", "explode", "moonshot", "next big", "early",
        "load", "loaded", "accumulate", "conviction",
    }

    NEGATIVE_KEYWORDS = {
        "rug", "scam", "honeypot", "dump", "dead", "rekt",
        "avoid", "trash", "shit", "dumped", "exit", "sell",
        "warning", "sus", "fake", "farm", "cabal",
    }

    SPAM_KEYWORDS = {
        "follow me", "check bio", "airdrop", "free money",
        "guaranteed", "join telegram", "dm me", "🎁",
    }

    KNOWN_INFLUENCERS = {
        "ansem":          {"tier": 1, "weight": 5.0},
        "notthreadguy":   {"tier": 1, "weight": 5.0},
        "murad_mahmudov": {"tier": 1, "weight": 4.5},
        "blknoiz06":      {"tier": 1, "weight": 4.0},
        "tree_of_alpha":  {"tier": 2, "weight": 3.5},
        "inversebrah":    {"tier": 3, "weight": 2.5},
        "lookonchain":    {"tier": 3, "weight": 2.5},
    }

    def __init__(self):
        self.session              = None
        self.cache                = {}
        self.total_analyses       = 0
        self.total_high_scores    = 0
        self.total_influencer_hits = 0

    async def start(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )
        logger.info(
            f"🐦 SocialScore démarré "
            f"({len(self.NITTER_INSTANCES)} instances Nitter)"
        )

    async def stop(self):
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("🐦 SocialScore arrêté")

    async def analyze_token(
        self,
        symbol: str,
        mint:   str = None,
    ) -> dict:
        try:
            cache_key = symbol.lower()

            # FIX : nettoyage cache périodique
            now = time.time()
            expired = [
                k for k, (ts, _) in self.cache.items()
                if now - ts > self.CACHE_TTL * 2
            ]
            for k in expired:
                del self.cache[k]

            if cache_key in self.cache:
                ts, result = self.cache[cache_key]
                if now - ts < self.CACHE_TTL:
                    return result

            tweets = await self._fetch_tweets(symbol, mint)

            if not tweets:
                result = self._empty_result()
                self.cache[cache_key] = (now, result)
                return result

            result = self._analyze_tweets(tweets, symbol)
            self.cache[cache_key] = (now, result)

            self.total_analyses += 1
            if result["score"] >= 60:
                self.total_high_scores += 1
            if result["influencers"]:
                self.total_influencer_hits += 1

            logger.info(
                f"🐦 Social analysé : ${symbol} → "
                f"Score {result['score']}/100 ({result['level']}) | "
                f"Mentions: {result['mentions_1h']}/h"
            )

            return result

        except Exception as e:
            logger.error(f"Social analyze error : {e}")
            return self._empty_result()

    def _empty_result(self) -> dict:
        return {
            "score":             0,
            "level":             "NONE",
            "mentions_1h":       0,
            "mentions_24h":      0,
            "unique_users":      0,
            "sentiment_pos":     0,
            "sentiment_neg":     0,
            "sentiment_neutral": 0,
            "influencers":       [],
            "velocity":          0,
            "spam_ratio":        0,
            "trending":          False,
        }

    async def _fetch_tweets(
        self,
        symbol: str,
        mint:   str = None,
    ) -> list:
        if mint:
            query = f"%24{symbol}%20OR%20{mint}"
        else:
            query = f"%24{symbol}"

        for instance in self.NITTER_INSTANCES:
            try:
                url = f"{instance}/search/rss?f=tweets&q={query}"
                async with self.session.get(url) as resp:
                    if resp.status != 200:
                        continue
                    text   = await resp.text()
                    tweets = self._parse_rss(text)
                    if tweets:
                        return tweets
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.debug(f"Nitter {instance} error : {e}")
                continue

        return []

    def _parse_rss(self, xml_text: str) -> list:
        tweets = []
        try:
            items = re.findall(r"<item>(.*?)</item>", xml_text, re.DOTALL)

            for item in items[:100]:
                title_match = re.search(r"<title>(.*?)</title>",           item)
                desc_match  = re.search(r"<description>(.*?)</description>", item, re.DOTALL)
                pub_match   = re.search(r"<pubDate>(.*?)</pubDate>",        item)
                link_match  = re.search(r"<link>([^<\s]+)</link>",          item)

                if not title_match or not desc_match:
                    continue

                title = title_match.group(1)
                desc  = desc_match.group(1)
                pub   = pub_match.group(1)  if pub_match  else ""
                link  = link_match.group(1) if link_match else ""

                user_match = re.search(r"R to @(\w+)|(\w+):", title)
                username   = "unknown"
                if user_match:
                    username = user_match.group(1) or user_match.group(2)
                elif link:
                    url_match = re.search(
                        r"nitter\.[^/]+/([^/]+)/status", link
                    )
                    if url_match:
                        username = url_match.group(1)

                try:
                    dt        = datetime.strptime(pub, "%a, %d %b %Y %H:%M:%S %Z")
                    timestamp = dt.replace(tzinfo=timezone.utc).timestamp()
                except Exception:
                    timestamp = time.time()

                clean_text = re.sub(r"<[^>]+>", "", desc)
                clean_text = clean_text.replace("&amp;", "&")
                clean_text = clean_text.replace("&lt;", "<")
                clean_text = clean_text.replace("&gt;", ">")
                clean_text = re.sub(r"\s+", " ", clean_text).strip()

                tweets.append({
                    "username":  username.lower(),
                    "text":      clean_text[:500],
                    "timestamp": timestamp,
                    "link":      link,
                })

        except Exception as e:
            logger.debug(f"Parse RSS error : {e}")

        return tweets

    def _analyze_tweets(self, tweets: list, symbol: str) -> dict:
        now          = time.time()
        one_hour_ago = now - 3600
        one_day_ago  = now - 86400

        mentions_1h = mentions_24h = 0
        users_all   = set()
        users_1h    = set()
        sentiments  = {"pos": 0, "neg": 0, "neutral": 0}
        spam_count  = 0
        influencers_found = {}

        for tweet in tweets:
            timestamp = tweet["timestamp"]
            username  = tweet["username"]
            text      = tweet["text"].lower()

            in_24h = timestamp >= one_day_ago
            in_1h  = timestamp >= one_hour_ago

            if in_24h:
                mentions_24h += 1
                users_all.add(username)

            if in_1h:
                mentions_1h += 1
                users_1h.add(username)

            if self._is_spam(text):
                spam_count += 1
                continue

            sentiment = self._analyze_sentiment(text)
            sentiments[sentiment] += 1

            if username in self.KNOWN_INFLUENCERS and username not in influencers_found:
                influencers_found[username] = self.KNOWN_INFLUENCERS[username]

        total_analyzed = sum(sentiments.values())
        if total_analyzed > 0:
            sent_pos = round(sentiments["pos"]     / total_analyzed * 100)
            sent_neg = round(sentiments["neg"]     / total_analyzed * 100)
            sent_neu = round(sentiments["neutral"] / total_analyzed * 100)
        else:
            sent_pos = sent_neg = sent_neu = 0

        spam_ratio    = round(spam_count / len(tweets) * 100) if tweets else 0
        avg_hourly_24h = mentions_24h / 24 if mentions_24h > 0 else 0
        velocity       = mentions_1h / avg_hourly_24h if avg_hourly_24h > 0 else 0
        trending       = mentions_1h > 20 and velocity > 2

        # Score 0-100
        score = 0

        if mentions_1h >= 100: score += 30
        elif mentions_1h >= 50: score += 20
        elif mentions_1h >= 20: score += 15
        elif mentions_1h >= 10: score += 10
        elif mentions_1h >= 5:  score += 5

        unique_users = len(users_1h)
        if unique_users >= 50: score += 20
        elif unique_users >= 25: score += 15
        elif unique_users >= 10: score += 10
        elif unique_users >= 5:  score += 5

        if sent_pos >= 80: score += 20
        elif sent_pos >= 60: score += 15
        elif sent_pos >= 40: score += 10
        elif sent_pos >= 30: score += 5

        influencer_weight = sum(i["weight"] for i in influencers_found.values())
        if influencer_weight >= 15: score += 20
        elif influencer_weight >= 10: score += 15
        elif influencer_weight >= 5:  score += 10
        elif influencer_weight >= 2:  score += 5

        if velocity >= 5: score += 10
        elif velocity >= 3: score += 7
        elif velocity >= 2: score += 5
        elif velocity >= 1.5: score += 3

        if spam_ratio > 40: score = int(score * 0.5)
        elif spam_ratio > 25: score = int(score * 0.8)
        if sent_neg > 40: score = int(score * 0.6)

        score = min(100, max(0, score))

        if score >= 80:   level = "VIRAL"
        elif score >= 60: level = "HIGH"
        elif score >= 40: level = "MEDIUM"
        elif score >= 20: level = "LOW"
        else:             level = "NONE"

        influencers_list = sorted(
            [
                {"username": u, "tier": info["tier"], "weight": info["weight"]}
                for u, info in influencers_found.items()
            ],
            key=lambda x: x["weight"],
            reverse=True,
        )

        return {
            "score":             score,
            "level":             level,
            "mentions_1h":       mentions_1h,
            "mentions_24h":      mentions_24h,
            "unique_users":      unique_users,
            "sentiment_pos":     sent_pos,
            "sentiment_neg":     sent_neg,
            "sentiment_neutral": sent_neu,
            "influencers":       influencers_list[:5],
            "velocity":          round(velocity, 2),
            "spam_ratio":        spam_ratio,
            "trending":          trending,
        }

    def _analyze_sentiment(self, text: str) -> str:
        text_lower = text.lower()
        pos_count  = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in text_lower)
        neg_count  = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in text_lower)
        if pos_count > neg_count and pos_count >= 1:
            return "pos"
        elif neg_count > pos_count and neg_count >= 1:
            return "neg"
        return "neutral"

    def _is_spam(self, text: str) -> bool:
        text_lower  = text.lower()
        emoji_count = len([c for c in text if ord(c) > 127])
        if emoji_count > 20:
            return True
        spam_hits = sum(1 for kw in self.SPAM_KEYWORDS if kw in text_lower)
        if spam_hits >= 2:
            return True
        if text.count("@") > 10:
            return True
        if text.count("http") > 3:
            return True
        return False

    def get_stats(self) -> dict:
        return {
            "total_analyses":   self.total_analyses,
            "high_scores":      self.total_high_scores,
            "influencer_hits":  self.total_influencer_hits,
            "cache_size":       len(self.cache),
        }

    def clear_cache(self):
        self.cache.clear()

    def get_score_emoji(self, score: int) -> str:
        if score >= 80:   return "🔥"
        elif score >= 60: return "🚀"
        elif score >= 40: return "📈"
        elif score >= 20: return "📊"
        else:             return "😐"