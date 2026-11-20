"""Async token bucket rate limiter for Wikimedia API politeness."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class AsyncTokenBucket:
    """Smooths a per-minute request budget across concurrent async workers."""

    def __init__(
        self,
        rate_per_min: float,
        capacity: float | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate = max(rate_per_min, 1.0) / 60.0
        self._capacity = capacity if capacity is not None else max(1.0, rate_per_min / 6.0)
        self._tokens = self._capacity
        self._clock = clock
        self._updated = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
        self._updated = now

    def try_acquire(self) -> bool:
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                if self.try_acquire():
                    return
                wait_s = max((1.0 - self._tokens) / self._rate, 0.001)
            await asyncio.sleep(wait_s)
