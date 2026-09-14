"""TierRateLimiter — sliding-window RPM gate per tier."""

from __future__ import annotations

import asyncio
import time
from collections import deque


class TierRateLimiter:
    """Per-tier sliding-window rate limiter.

    consume(tier) returns True if the request is allowed, False if the limit
    for that tier is exceeded. A limit of 0 means unlimited.
    """

    def __init__(self, limits: dict[str, int], window_s: float = 60.0):
        self._limits = limits
        self._window = window_s
        self._queues: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def consume(self, tier: str) -> bool:
        rpm = self._limits.get(tier, 0)
        if rpm == 0:
            return True

        now = time.monotonic()
        cutoff = now - self._window

        async with self._lock:
            q = self._queues.setdefault(tier, deque())
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= rpm:
                return False
            q.append(now)
            return True
