"""Tests cho QuotaGuard — tự động exclude model khi nhóm hết quota."""

from unittest.mock import MagicMock, patch

from src.gateway.app.core.quota import QuotaGuard

_CONFIG = [
    {"group": "premium", "limit_tokens": 100, "models": ["gpt-5.4", "gpt-4o"]},
    {"group": "standard", "limit_tokens": 500, "models": ["gpt-5-nano", "gpt-4o-mini"]},
]


def _guard(usage: dict) -> QuotaGuard:
    db = MagicMock()
    guard = QuotaGuard(db_factory=lambda: db, quota_config=_CONFIG, ttl_s=0)
    with patch("src.gateway.app.core.quota.sum_tokens_by_model", return_value=usage):
        _ = guard.exhausted_models()
    return guard


def test_no_usage_returns_empty():
    guard = _guard({})
    with patch("src.gateway.app.core.quota.sum_tokens_by_model", return_value={}):
        assert guard.exhausted_models() == frozenset()


def test_group_exhausted_excludes_all_models():
    usage = {"gpt-5.4": 60, "gpt-4o": 40}  # tổng = 100 == limit
    guard = _guard(usage)
    with patch("src.gateway.app.core.quota.sum_tokens_by_model", return_value=usage):
        result = guard.exhausted_models()
    assert ("gpt-5.4", "openai") in result
    assert ("gpt-4o", "openai") in result


def test_partial_usage_not_excluded():
    usage = {"gpt-5.4": 50}  # tổng = 50 < 100
    guard = _guard(usage)
    with patch("src.gateway.app.core.quota.sum_tokens_by_model", return_value=usage):
        result = guard.exhausted_models()
    assert ("gpt-5.4", "openai") not in result


def test_only_exhausted_group_excluded():
    usage = {"gpt-5.4": 100, "gpt-5-nano": 100}  # premium = 100 hết, standard = 100 < 500
    guard = _guard(usage)
    with patch("src.gateway.app.core.quota.sum_tokens_by_model", return_value=usage):
        result = guard.exhausted_models()
    assert ("gpt-5.4", "openai") in result
    assert ("gpt-5-nano", "openai") not in result


def test_cache_hit_skips_db():
    """TTL > 0 → lần 2 không gọi DB."""
    db = MagicMock()
    guard = QuotaGuard(db_factory=lambda: db, quota_config=_CONFIG, ttl_s=9999)
    call_count = 0

    def counting_sum(*_a, **_kw):
        nonlocal call_count
        call_count += 1
        return {}

    with patch("src.gateway.app.core.quota.sum_tokens_by_model", side_effect=counting_sum):
        guard.exhausted_models()
        guard.exhausted_models()

    assert call_count == 1
