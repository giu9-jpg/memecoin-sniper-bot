# utils/rate_limiter.py — v1.0
# Rate limiter async réutilisable pour les appels API

import asyncio
import time
from collections import deque
from utils.logger import get_logger

logger = get_logger("rate_limiter")


class RateLimiter:
    """
    Rate limiter basé sur une fenêtre glissante.

    Usage :
        limiter = RateLimiter(max_calls=10, period=60)
        async with limiter:
            await api_call()
    """

    def __init__(self, max_calls: int, period: float, name: str = "API"):
        self.max_calls = max_calls
        self.period    = period
        self.name      = name
        self._calls: deque = deque()
        self._lock:  asyncio.Lock = asyncio.Lock()

    async def acquire(self):
        """Attend si nécessaire pour respecter le rate limit."""
        async with self._lock:
            now = time.time()

            # Supprime les appels hors de la fenêtre
            while self._calls and self._calls[0] <= now - self.period:
                self._calls.popleft()

            # Si au maximum, attend
            if len(self._calls) >= self.max_calls:
                oldest = self._calls[0]
                wait   = self.period - (now - oldest) + 0.01
                if wait > 0:
                    logger.debug(
                        f"[RATE] {self.name} : attente {wait:.2f}s "
                        f"({len(self._calls)}/{self.max_calls})"
                    )
                    await asyncio.sleep(wait)

            self._calls.append(time.time())

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        pass

    @property
    def current_usage(self) -> int:
        now = time.time()
        return sum(1 for t in self._calls if t > now - self.period)

    @property
    def is_limited(self) -> bool:
        return self.current_usage >= self.max_calls


# ── Instances partagées ───────────────────────────────

# Helius API
helius_limiter = RateLimiter(max_calls=8, period=1.0, name="Helius")

# DexScreener
dexscreener_limiter = RateLimiter(max_calls=20, period=60.0, name="DexScreener")

# Telegram
telegram_limiter = RateLimiter(max_calls=20, period=60.0, name="Telegram")

# CoinGecko
coingecko_limiter = RateLimiter(max_calls=10, period=60.0, name="CoinGecko")

# Nitter
nitter_limiter = RateLimiter(max_calls=1, period=2.0, name="Nitter")