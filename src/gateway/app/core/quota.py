"""QuotaGuard — tự động disable model khi nhóm hết quota token trong ngày."""

from __future__ import annotations

import math
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from src.gateway.app.db.crud import sum_tokens_by_api_key, sum_tokens_by_model

_QUOTA_FILE = Path(__file__).resolve().parent.parent / "config" / "quota.yaml"


def get_daily_quota_reset(now: datetime | None = None) -> tuple[datetime, int]:
    """Return the next UTC daily-budget reset and seconds until it occurs."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)

    reset_at = current.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    retry_after_seconds = max(1, math.ceil((reset_at - current).total_seconds()))
    return reset_at, retry_after_seconds


def check_daily_token_budget(db, api_key_id, limit: int, *, now: datetime | None = None) -> int | None:
    """Per-client daily token budget (AC-2). Trả tokens đã dùng hôm nay nếu client ĐÃ chạm/vượt
    budget (block); None nếu còn dưới, hoặc không áp dụng (open/dev mode, limit<=0).

    ponytail: chặn khi usage-đã-ghi >= limit, không reserve trước — một request có thể vượt nhẹ
    (tối đa 1 request), đủ cho cost cap. Cần hard-cap chính xác thì thêm reservation.
    """
    if not isinstance(api_key_id, int) or limit <= 0:
        return None
    d = (now or datetime.now(UTC)).date()
    day_start = datetime(d.year, d.month, d.day)
    day_end = day_start + timedelta(days=1)
    used = sum_tokens_by_api_key(db, api_key_id, day_start, day_end)
    return used if used >= limit else None


def _load_quota_config() -> list[dict]:
    return yaml.safe_load(_QUOTA_FILE.read_text(encoding="utf-8"))["openai_quotas"]


class QuotaGuard:
    """Cache 60s, refresh khi hết hạn hoặc sang ngày mới.

    exhausted_models() trả frozenset[(model_id, provider)] để merge vào exclude
    của PolicyEngine — cùng cơ chế với CircuitBreaker.open_set().
    """

    def __init__(self, db_factory, quota_config: list[dict] | None = None, ttl_s: int = 60):
        self._db_factory = db_factory
        self._config = quota_config or _load_quota_config()
        self._ttl = ttl_s
        self._cached_date: str | None = None
        self._cached_at: float = 0.0
        self._cached_result: frozenset[tuple[str, str]] = frozenset()

        # map model_id -> provider từ config (tất cả quota models hiện tại là openai)
        self._model_provider: dict[str, str] = {}
        for group in self._config:
            provider = group.get("provider", "openai")
            for m in group["models"]:
                self._model_provider[m] = provider

    def exhausted_models(self, *, now: datetime | None = None) -> frozenset[tuple[str, str]]:
        """Trả (model_id, provider) của các model thuộc nhóm đã hết quota hôm nay."""
        today = (now or datetime.now(UTC)).date().isoformat()
        mono = time.monotonic()

        if today == self._cached_date and mono - self._cached_at < self._ttl:
            return self._cached_result

        self._cached_result = self._compute(today)
        self._cached_date = today
        self._cached_at = mono
        return self._cached_result

    def _compute(self, today_str: str) -> frozenset[tuple[str, str]]:
        from datetime import date

        d = date.fromisoformat(today_str)
        day_start = datetime(d.year, d.month, d.day)
        day_end = day_start + timedelta(days=1)

        all_models = list(self._model_provider)
        db = self._db_factory()
        try:
            usage = sum_tokens_by_model(db, day_start, day_end, all_models)
        finally:
            db.close()

        exhausted: set[tuple[str, str]] = set()
        for group in self._config:
            used = sum(usage.get(m, 0) for m in group["models"])
            if used >= group["limit_tokens"]:
                for m in group["models"]:
                    exhausted.add((m, self._model_provider[m]))
        return frozenset(exhausted)
