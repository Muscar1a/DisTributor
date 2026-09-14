from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from src.gateway.app.core.interfaces import ModelRef

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """Máy trạng thái CLOSED -> OPEN -> HALF_OPEN (FR-10, AC-3.4).

    - Đếm **chỉ trên lỗi retryable** (429/5xx/timeout), per (model_id, provider).
    - `failure_threshold` lỗi liên tiếp -> OPEN.
    - OPEN trong `recovery_timeout_s` -> HALF_OPEN, thử **đúng 1 request**:
        - thành công -> CLOSED (reset bộ đếm);
        - thất bại -> OPEN lại (reset bộ đếm, không cần đủ threshold).
    - Model đang OPEN nằm trong `open_set()` -> PolicyEngine đưa vào `exclude`
      nên tự rời mọi chain (05_interfaces.md §B.3).
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_s: int = 300,
        now: Callable[[], float] | None = None,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self._now = now or time.monotonic
        self._failures: dict[tuple[str, str], int] = {}
        self._state: dict[tuple[str, str], str] = {}
        self._open_since: dict[tuple[str, str], float] = {}
        self._half_open_inflight: dict[tuple[str, str], bool] = {}

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _key(ref: ModelRef) -> tuple[str, str]:
        return (ref.model_id, ref.provider)

    def state_of(self, ref: ModelRef) -> str:
        return self._state.get(self._key(ref), CLOSED)

    # ------------------------------------------------------------------ #
    # Ghi nhận kết quả (chỉ gọi từ Orchestrator/FallbackExecutor)
    # ------------------------------------------------------------------ #
    def record_success(self, ref: ModelRef) -> None:
        key = self._key(ref)
        self._failures[key] = 0
        self._state[key] = CLOSED
        self._open_since.pop(key, None)
        self._half_open_inflight[key] = False

    def record_error(self, ref: ModelRef, retryable: bool = True) -> None:
        """Ghi nhận lỗi. Chỉ đếm khi `retryable=True` (ADR-010: content-filter không đếm)."""
        key = self._key(ref)
        if not retryable:
            return

        if self._state.get(key) == HALF_OPEN:
            # 1 lỗi trong HALF_OPEN -> OPEN lại ngay (reset bộ đếm)
            self._state[key] = OPEN
            self._open_since[key] = self._now()
            self._failures[key] = 0
            self._half_open_inflight[key] = False
            return

        self._failures[key] = self._failures.get(key, 0) + 1
        if self._failures[key] >= self.failure_threshold:
            self._state[key] = OPEN
            self._open_since[key] = self._now()
            self._half_open_inflight[key] = False

    # ------------------------------------------------------------------ #
    # Kiểm soát luồng request
    # ------------------------------------------------------------------ #
    def allow_request(self, ref: ModelRef) -> bool:
        """Kiểm tra provider này có được gọi không.

        - CLOSED -> True.
        - OPEN chưa hết `recovery_timeout_s` -> False (chặn).
        - OPEN đã quá hạn -> chuyển HALF_OPEN và cho thử đúng 1 request.
        - HALF_OPEN -> chỉ 1 request đồng thời (`half_open_inflight`).
        """
        key = self._key(ref)
        state = self._state.get(key, CLOSED)
        if state == CLOSED:
            return True

        if state == OPEN:
            if self._now() - self._open_since.get(key, 0) >= self.recovery_timeout_s:
                self._state[key] = HALF_OPEN
                self._half_open_inflight[key] = True
                return True
            return False

        # HALF_OPEN
        if self._half_open_inflight.get(key, False):
            return False
        self._half_open_inflight[key] = True
        return True

    def open_set(self) -> frozenset[tuple[str, str]]:
        """Tập (model_id, provider) đang OPEN — nguồn cho `exclude` của PolicyEngine."""
        return frozenset(k for k, v in self._state.items() if v == OPEN)

    def retry_after_s(self, ref: ModelRef) -> float:
        key = self._key(ref)
        if self._state.get(key) != OPEN:
            return 0.0
        return max(0.0, self._open_since.get(key, 0) + self.recovery_timeout_s - self._now())

    def snapshot(self) -> dict[tuple[str, str], dict[str, Any]]:
        """Trạng thái đầy đủ cho /healthz & /v1/models (AC-3.4)."""
        return {
            k: {
                "state": self._state.get(k, CLOSED),
                "consecutive_failures": self._failures.get(k, 0),
                "open_until": (self._open_since.get(k, 0) + self.recovery_timeout_s)
                if self._state.get(k) == OPEN
                else None,
            }
            for k in self._state.keys() | self._failures.keys()
        }
