"""ClientRateLimiter — per-client sliding-window RPM gate.

Sliding-window counter độc lập với TierRateLimiter: gate đặt ở middleware,
key là client identifier (api_key_id, dev-key hash, hoặc IP). Khi vượt limit
trả False; middleware chuyển thành 429.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque


class ClientRateLimiter:
    """Per-client sliding-window rate limiter.

    is_allowed(client_id, limit) returns True nếu request được phép, False
    nếu đã đạt `limit` request trong `window_s` giây. `limit == 0` nghĩa là
    unlimited (pass-through).
    """

    def __init__(self, window_s: float = 60.0):
        self._window = window_s
        self._queues: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()
        self._last_sweep = 0.0

    async def is_allowed(self, client_id: str | int | None, limit: int) -> bool:
        if not client_id or limit <= 0:
            return True

        key = str(client_id)
        now = time.monotonic()
        cutoff = now - self._window

        async with self._lock:
            self._sweep_idle(now, cutoff)
            q = self._queues.setdefault(key, deque())
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def _sweep_idle(self, now: float, cutoff: float) -> None:
        """Drop keys whose newest hit already expired — else idle/rotating clients (IP mode)
        leave empty deques that never get evicted (memory leak). Runs at most once per window.
        ponytail: per-process only; >1 worker cần Redis, không thêm lock ở đây."""
        if now - self._last_sweep < self._window:
            return
        self._last_sweep = now
        stale = [k for k, dq in self._queues.items() if not dq or dq[-1] <= cutoff]
        for k in stale:
            del self._queues[k]

    def reset(self) -> None:
        """Xoá toàn bộ counter (dùng trong test / admin operations)."""
        self._queues.clear()
