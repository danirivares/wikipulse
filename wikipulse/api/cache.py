"""Single-flight async TTL cache for SSE snapshot coalescing.

Ensures that N concurrent browser tabs subscribed to `/api/stream` or `/api/malice`
trigger at most one Redis round-trip per TTL window per key.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


class SnapshotCache:
    """Coalesces concurrent async fetches under a per-key lock with a short TTL."""

    def __init__(
        self,
        ttl_s: float = 0.8,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_s = ttl_s
        self._clock = clock
        self._entries: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[T]],
    ) -> T:
        now = self._clock()
        entry = self._entries.get(key)
        if entry is not None and (now - entry[0]) < self._ttl_s:
            return entry[1]

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = self._clock()
            entry = self._entries.get(key)
            if entry is not None and (now - entry[0]) < self._ttl_s:
                return entry[1]
            value = await fetcher()
            self._entries[key] = (self._clock(), value)
            return value

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)
