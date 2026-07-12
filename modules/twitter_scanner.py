import tweepy
import os
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
from config.alpha_accounts import ALL_ACCOUNTS
from config.keywords import BULLISH_KEYWORDS, DANGER_KEYWORDS
from utils.logger import logger

load_dotenv()


class TwitterScanner:
    def __init__(self):
        self.client = tweepy.Client(
            bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
            wait_on_rate_limit=True
        )
        self.recent_mentions = {}

    def search_alpha_tweets(self):
        results = []

        for account in ALL_ACCOUNTS:
            try:
                tweets = self.client.search_recent_tweets(
                    query=f"from:{account} -is:retweet",
                    max_results=10,
                    tweet_fields=["created_at", "text"]
                )

                if not tweets.data:
                    continue

                for tweet in tweets.data:
                    text = tweet.text.lower()
                    has_bullish = any(
                        k in text for k in BULLISH_KEYWORDS
                    )
                    has_danger = any(
                        k in text for k in DANGER_KEYWORDS
                    )
                    tickers = re.findall(
                        r'\$([A-Za-z]{2,10})', tweet.text
                    )
                    contracts = re.findall(
                        r'[1-9A-HJ-NP-Za-km-z]{32,44}',
                        tweet.text
                    )

                    if has_bullish and not has_danger and tickers:
                        for ticker in tickers:
                            self._record_mention(ticker.upper())
                            results.append({
                                "ticker": ticker.upper(),
                                "account": account,
                                "contracts_found": contracts,
                            })

            except Exception as e:
                logger.error(
                    f"Twitter erreur ({account}) : {e}"
                )

        return results

    def _record_mention(self, ticker):
        now = datetime.utcnow()
        if ticker not in self.recent_mentions:
            self.recent_mentions[ticker] = []
        self.recent_mentions[ticker].append(now)
        cutoff = now - timedelta(minutes=5)
        self.recent_mentions[ticker] = [
            t for t in self.recent_mentions[ticker]
            if t > cutoff
        ]

    def get_mention_count(self, ticker):
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=5)
        if ticker not in self.recent_mentions:
            return 0
        return len([
            t for t in self.recent_mentions[ticker]
            if t > cutoff
        ])

    def is_trending(self, ticker, min_mentions=2):
        return self.get_mention_count(ticker) >= min_mentions