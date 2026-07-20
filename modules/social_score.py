# modules/social_score.py v1.0
"""
Social Score Twitter/X
Analyse le buzz autour d'un token via Nitter (Twitter mirror).

Métriques calculées :
  - Nombre de mentions (1h, 24h)
  - Utilisateurs uniques
  - Sentiment positif/négatif/neutre
  - Détection d'influenceurs
  - Vélocité (croissance des mentions)
  - Anti-spam (filtre bots)

Score final : 0-100
  - 0-30   : pas de buzz
  - 30-60  : buzz modéré
  - 60-80  : buzz fort
  - 80+    : viral 🚀
"""

import asyncio
import aiohttp
import re
import time
from datetime import datetime, timezone, timedelta
from collections import defaultdict, Counter
from utils.logger import get_logger

logger = get_logger("social_score")


class SocialScore:

    # ════════════════════════════════════════
    # CONFIGURATION
    # ════════════════════════════════════════

    # Instances Nitter (fallback multiple)
    NITTER_INSTANCES = [
        "https://nitter.net",
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.projectsegfau.lt",
    ]

    # Cache pour éviter les requêtes multiples
    CACHE_TTL = 300  # 5 minutes

    # Mots-clés positifs
    POSITIVE_KEYWORDS = {
        "moon", "gem", "100x", "1000x", "pump", "buy", "bullish",
        "🚀", "💎", "🌙", "🔥", "ape", "aping", "based",
        "insane", "explode", "moonshot", "next big", "early",
        "load", "loaded", "accumulate", "conviction",
    }

    # Mots-clés négatifs
    NEGATIVE_KEYWORDS = {
        "rug", "scam", "honeypot", "dump", "dead", "rekt",
        "avoid", "trash", "shit", "dumped", "exit", "sell",
        "warning", "sus", "fake", "farm", "cabal",
    }

    # Mots-clés spam
    SPAM_KEYWORDS = {
        "follow me", "check bio", "airdrop", "free money",
        "guaranteed", "join telegram", "dm me", "🎁",
    }

    # Influenceurs connus (usernames)
    KNOWN_INFLUENCERS = {
        # Tier 1
        "ansem":          {"tier": 1, "weight": 5.0},
        "notthreadguy":   {"tier": 1, "weight": 5.0},
        "murad_mahmudov": {"tier": 1, "weight": 4.5},
        "blknoiz06":      {"tier": 1, "weight": 4.0},
        # Tier 2
        "tree_of_alpha":  {"tier": 2, "weight": 3.5},
        "inversebrah":    {"tier": 3, "weight": 2.5},
        "lookonchain":    {"tier": 3, "weight": 2.5},
        # Ajouter d'autres...
    }

    def __init__(self):
        self.session = None
        self.cache = {}  # {token_query: (timestamp, result)}

        # Stats
        self.total_analyses = 0
        self.total_high_scores = 0
        self.total_influencer_hits = 0

    async def start(self):
        """Démarre le module"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        )
        logger.info(
            f"🐦 SocialScore démarré "
            f"({len(self.NITTER_INSTANCES)} instances Nitter)"
        )

    async def stop(self):
        """Arrêt propre"""
        if self.session and not self.session.closed:
            await self.session.close()
        logger.info("🐦 SocialScore arrêté")

    # ════════════════════════════════════════
    # ANALYSE PRINCIPALE
    # ════════════════════════════════════════

    async def analyze_token(
        self,
        symbol: str,
        mint: str = None,
    ) -> dict:
        """
        Analyse le buzz Twitter/X d'un token.

        Args:
          symbol : symbole du token (ex: "PEPE")
          mint   : adresse du contrat (optionnel, pour recherche $ADDRESS)

        Returns:
          {
            "score":              0-100,
            "level":              "NONE" | "LOW" | "MEDIUM" | "HIGH" | "VIRAL",
            "mentions_1h":        int,
            "mentions_24h":       int,
            "unique_users":       int,
            "sentiment_pos":      %,
            "sentiment_neg":      %,
            "sentiment_neutral":  %,
            "influencers":        [{"username", "tier"}],
            "velocity":           float,
            "spam_ratio":         %,
            "trending":           bool,
          }
        """
        try:
            # Cache
            cache_key = symbol.lower()
            if cache_key in self.cache:
                ts, result = self.cache[cache_key]
                if time.time() - ts < self.CACHE_TTL:
                    return result

            # Recherche les tweets
            tweets = await self._fetch_tweets(symbol, mint)

            if not tweets:
                result = self._empty_result()
                self.cache[cache_key] = (time.time(), result)
                return result

            # Analyse
            result = self._analyze_tweets(tweets, symbol)

            # Cache
            self.cache[cache_key] = (time.time(), result)

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

    # ════════════════════════════════════════
    # RÉCUPÉRATION DES TWEETS
    # ════════════════════════════════════════

    async def _fetch_tweets(
        self,
        symbol: str,
        mint: str = None,
    ) -> list:
        """
        Fetch les tweets via Nitter avec fallback multiple.

        Cherche : $SYMBOL OR mint_address
        """
        # Query : combiner $symbol et mint si dispo
        if mint:
            query = f"%24{symbol}%20OR%20{mint}"
        else:
            query = f"%24{symbol}"

        # Essaie chaque instance Nitter
        for instance in self.NITTER_INSTANCES:
            try:
                url = f"{instance}/search/rss?f=tweets&q={query}"

                async with self.session.get(url) as resp:
                    if resp.status != 200:
                        continue

                    text = await resp.text()

                # Parse RSS
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
        """Parse le RSS Nitter pour extraire les tweets"""
        tweets = []

        try:
            # Regex simple pour extraire les items
            items = re.findall(
                r"<item>(.*?)</item>",
                xml_text,
                re.DOTALL
            )

            for item in items[:100]:  # Max 100 tweets
                # Extraire les données
                title_match = re.search(
                    r"<title>(.*?)</title>",
                    item
                )
                desc_match = re.search(
                    r"<description>(.*?)</description>",
                    item,
                    re.DOTALL
                )
                pub_match = re.search(
                    r"<pubDate>(.*?)</pubDate>",
                    item
                )
                link_match = re.search(
                    r"<link>(.*?)</link>",
                    item
                )

                if not title_match or not desc_match:
                    continue

                title = title_match.group(1)
                desc = desc_match.group(1)
                pub = pub_match.group(1) if pub_match else ""
                link = link_match.group(1) if link_match else ""

                # Extraire username depuis le titre (format: @user)
                user_match = re.search(r"R to @(\w+)|(\w+):", title)
                username = "unknown"
                if user_match:
                    username = user_match.group(1) or user_match.group(2)
                elif link:
                    # Extract from link : https://nitter.net/USERNAME/status/...
                    url_match = re.search(
                        r"nitter\.[^/]+/([^/]+)/status",
                        link
                    )
                    if url_match:
                        username = url_match.group(1)

                # Timestamp
                try:
                    dt = datetime.strptime(
                        pub, "%a, %d %b %Y %H:%M:%S %Z"
                    )
                    timestamp = dt.replace(tzinfo=timezone.utc).timestamp()
                except Exception:
                    timestamp = time.time()

                # Clean text (retirer HTML)
                clean_text = re.sub(r"<[^>]+>", "", desc)
                clean_text = clean_text.replace("&amp;", "&")
                clean_text = clean_text.replace("&lt;", "<")
                clean_text = clean_text.replace("&gt;", ">")

                tweets.append({
                    "username":   username.lower(),
                    "text":       clean_text[:500],
                    "timestamp":  timestamp,
                    "link":       link,
                })

        except Exception as e:
            logger.debug(f"Parse RSS error : {e}")

        return tweets

    # ════════════════════════════════════════
    # ANALYSE DES TWEETS
    # ════════════════════════════════════════

    def _analyze_tweets(
        self, tweets: list, symbol: str
    ) -> dict:
        """Analyse une liste de tweets et calcule le score"""
        now = time.time()
        one_hour_ago = now - 3600
        one_day_ago  = now - 86400

        # Compteurs
        mentions_1h = 0
        mentions_24h = 0
        users_all = set()
        users_1h = set()

        sentiments = {"pos": 0, "neg": 0, "neutral": 0}
        spam_count = 0
        influencers_found = {}

        for tweet in tweets:
            timestamp = tweet["timestamp"]
            username = tweet["username"]
            text = tweet["text"].lower()

            # Périodes
            in_24h = timestamp >= one_day_ago
            in_1h = timestamp >= one_hour_ago

            if in_24h:
                mentions_24h += 1
                users_all.add(username)

            if in_1h:
                mentions_1h += 1
                users_1h.add(username)

            # Détection spam
            is_spam = self._is_spam(text)
            if is_spam:
                spam_count += 1
                continue  # Ignore les spams pour le sentiment

            # Sentiment
            sentiment = self._analyze_sentiment(text)
            sentiments[sentiment] += 1

            # Détection influenceur
            if username in self.KNOWN_INFLUENCERS:
                if username not in influencers_found:
                    influencers_found[username] = self.KNOWN_INFLUENCERS[username]

        # Calcul des ratios
        total_analyzed = sum(sentiments.values())
        if total_analyzed > 0:
            sent_pos = round(sentiments["pos"] / total_analyzed * 100)
            sent_neg = round(sentiments["neg"] / total_analyzed * 100)
            sent_neu = round(sentiments["neutral"] / total_analyzed * 100)
        else:
            sent_pos = sent_neg = sent_neu = 0

        spam_ratio = round(spam_count / len(tweets) * 100) if tweets else 0

        # Vélocité : mentions 1h / (mentions 24h / 24)
        # >1 = accélération
        avg_hourly_24h = mentions_24h / 24 if mentions_24h > 0 else 0
        velocity = mentions_1h / avg_hourly_24h if avg_hourly_24h > 0 else 0

        # Trending : mentions_1h > 20 + vélocité > 2
        trending = mentions_1h > 20 and velocity > 2

        # ════════════════════════════════════════
        # CALCUL DU SCORE 0-100
        # ════════════════════════════════════════
        score = 0

        # 1. Volume mentions (30 points max)
        if mentions_1h >= 100:
            score += 30
        elif mentions_1h >= 50:
            score += 20
        elif mentions_1h >= 20:
            score += 15
        elif mentions_1h >= 10:
            score += 10
        elif mentions_1h >= 5:
            score += 5

        # 2. Utilisateurs uniques (20 points max)
        unique_users = len(users_1h)
        if unique_users >= 50:
            score += 20
        elif unique_users >= 25:
            score += 15
        elif unique_users >= 10:
            score += 10
        elif unique_users >= 5:
            score += 5

        # 3. Sentiment positif (20 points max)
        if sent_pos >= 80:
            score += 20
        elif sent_pos >= 60:
            score += 15
        elif sent_pos >= 40:
            score += 10
        elif sent_pos >= 30:
            score += 5

        # 4. Influenceurs (20 points max)
        influencer_weight = sum(
            i["weight"] for i in influencers_found.values()
        )
        if influencer_weight >= 15:
            score += 20
        elif influencer_weight >= 10:
            score += 15
        elif influencer_weight >= 5:
            score += 10
        elif influencer_weight >= 2:
            score += 5

        # 5. Vélocité (10 points max)
        if velocity >= 5:
            score += 10
        elif velocity >= 3:
            score += 7
        elif velocity >= 2:
            score += 5
        elif velocity >= 1.5:
            score += 3

        # Pénalité spam
        if spam_ratio > 40:
            score = int(score * 0.5)
        elif spam_ratio > 25:
            score = int(score * 0.8)

        # Pénalité sentiment négatif
        if sent_neg > 40:
            score = int(score * 0.6)

        # Cap à 100
        score = min(100, max(0, score))

        # Level
        if score >= 80:
            level = "VIRAL"
        elif score >= 60:
            level = "HIGH"
        elif score >= 40:
            level = "MEDIUM"
        elif score >= 20:
            level = "LOW"
        else:
            level = "NONE"

        # Liste des influenceurs
        influencers_list = [
            {"username": u, "tier": info["tier"], "weight": info["weight"]}
            for u, info in influencers_found.items()
        ]
        influencers_list.sort(key=lambda x: x["weight"], reverse=True)

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

    # ════════════════════════════════════════
    # DÉTECTION SENTIMENT
    # ════════════════════════════════════════

    def _analyze_sentiment(self, text: str) -> str:
        """Analyse le sentiment (positif/négatif/neutre)"""
        text_lower = text.lower()

        pos_count = sum(
            1 for kw in self.POSITIVE_KEYWORDS
            if kw in text_lower
        )
        neg_count = sum(
            1 for kw in self.NEGATIVE_KEYWORDS
            if kw in text_lower
        )

        if pos_count > neg_count and pos_count >= 1:
            return "pos"
        elif neg_count > pos_count and neg_count >= 1:
            return "neg"
        else:
            return "neutral"

    def _is_spam(self, text: str) -> bool:
        """Détecte si un tweet est du spam"""
        text_lower = text.lower()

        # Trop de emojis
        emoji_count = len([c for c in text if ord(c) > 127])
        if emoji_count > 20:
            return True

        # Mots-clés spam
        spam_hits = sum(
            1 for kw in self.SPAM_KEYWORDS
            if kw in text_lower
        )
        if spam_hits >= 2:
            return True

        # Trop de @mentions
        mentions = text.count("@")
        if mentions > 10:
            return True

        # Trop de liens
        links = text.count("http")
        if links > 3:
            return True

        return False

    # ════════════════════════════════════════
    # HELPERS
    # ════════════════════════════════════════

    def get_stats(self) -> dict:
        return {
            "total_analyses":      self.total_analyses,
            "high_scores":         self.total_high_scores,
            "influencer_hits":     self.total_influencer_hits,
            "cache_size":          len(self.cache),
        }

    def clear_cache(self):
        """Vide le cache"""
        self.cache.clear()

    def get_score_emoji(self, score: int) -> str:
        """Retourne l'emoji correspondant au score"""
        if score >= 80:
            return "🔥"
        elif score >= 60:
            return "🚀"
        elif score >= 40:
            return "📈"
        elif score >= 20:
            return "📊"
        else:
            return "😐"