"""#240 — unit tests for fault-injection primitives.

Covers every trigger independently (AC-5), per-model targeting (@model_id),
and the non-bypass invariant for #force_filter (AC-3).
"""

from __future__ import annotations

import pytest

from src.gateway.app.adapters.mock_adapter import MockAdapter
from src.gateway.app.core.interfaces import (
    BadRequestToProvider,
    CompletionParams,
    ContentFilteredError,
    Message,
    ModelRef,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimitError,
)

_PARAMS = CompletionParams()


def _msg(text: str) -> list[Message]:
    return [Message(role="user", content=text)]


# ───────── existing triggers still work ──────────────────────────────────────


@pytest.mark.asyncio
async def test_force_429():
    adapter = MockAdapter()
    with pytest.raises(RateLimitError):
        await adapter.complete("mock-cheap", _msg("hi #force_429"), _PARAMS)


@pytest.mark.asyncio
async def test_force_500():
    adapter = MockAdapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.complete("mock-cheap", _msg("hi #force_500"), _PARAMS)


# ───────── new triggers (#240 §1) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_force_timeout():
    adapter = MockAdapter()
    with pytest.raises(ProviderTimeout):
        await adapter.complete("mock-cheap", _msg("hi #force_timeout"), _PARAMS)


@pytest.mark.asyncio
async def test_force_filter():
    adapter = MockAdapter()
    with pytest.raises(ContentFilteredError):
        await adapter.complete("mock-cheap", _msg("hi #force_filter"), _PARAMS)


@pytest.mark.asyncio
async def test_force_400():
    adapter = MockAdapter()
    with pytest.raises(BadRequestToProvider):
        await adapter.complete("mock-cheap", _msg("hi #force_400"), _PARAMS)


# ───────── retryable semantics ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_force_timeout_is_retryable():
    adapter = MockAdapter()
    with pytest.raises(ProviderTimeout) as exc_info:
        await adapter.complete("mock-cheap", _msg("#force_timeout"), _PARAMS)
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_force_filter_is_not_retryable():
    adapter = MockAdapter()
    with pytest.raises(ContentFilteredError) as exc_info:
        await adapter.complete("mock-cheap", _msg("#force_filter"), _PARAMS)
    assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_force_400_is_not_retryable():
    adapter = MockAdapter()
    with pytest.raises(BadRequestToProvider) as exc_info:
        await adapter.complete("mock-cheap", _msg("#force_400"), _PARAMS)
    assert exc_info.value.retryable is False


# ───────── @model_id targeting (#240 §1) ────────────────────────────────────


@pytest.mark.asyncio
async def test_targeted_trigger_fires_for_matching_model():
    adapter = MockAdapter()
    with pytest.raises(RateLimitError):
        await adapter.complete("mock-cheap", _msg("#force_429@mock-cheap"), _PARAMS)


@pytest.mark.asyncio
async def test_targeted_trigger_skips_non_matching_model():
    adapter = MockAdapter()
    result = await adapter.complete("mock-mid", _msg("#force_429@mock-cheap"), _PARAMS)
    assert result.content  # mock-mid is unaffected


@pytest.mark.asyncio
async def test_bare_trigger_fires_for_any_model():
    adapter = MockAdapter()
    for model in ("mock-cheap", "mock-mid", "mock-premium"):
        with pytest.raises(ProviderUnavailable):
            await adapter.complete(model, _msg("#force_500"), _PARAMS)


@pytest.mark.asyncio
async def test_targeted_filter_fires_only_for_target():
    adapter = MockAdapter()
    with pytest.raises(ContentFilteredError):
        await adapter.complete("mock-premium", _msg("#force_filter@mock-premium"), _PARAMS)
    result = await adapter.complete("mock-cheap", _msg("#force_filter@mock-premium"), _PARAMS)
    assert result.content


# ───────── stream path ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stream_force_timeout():
    adapter = MockAdapter()
    with pytest.raises(ProviderTimeout):
        async for _ in adapter.stream("mock-cheap", _msg("#force_timeout"), _PARAMS):
            pass


@pytest.mark.asyncio
async def test_stream_targeted_skips_non_matching():
    adapter = MockAdapter()
    chunks = []
    async for chunk in adapter.stream("mock-mid", _msg("#force_500@mock-cheap"), _PARAMS):
        chunks.append(chunk.delta)
    assert len(chunks) > 0


# ───────── #force_filter cannot be bypassed through fallback (AC-3) ─────────


@pytest.mark.asyncio
async def test_filter_not_bypassed_by_fallback():
    """ContentFilteredError is non-retryable, so FallbackExecutor must raise
    it immediately without trying the next model in the chain."""
    from src.gateway.app.core.circuit import CircuitBreaker
    from src.gateway.app.core.fallback import FallbackExecutor

    adapter = MockAdapter()
    executor = FallbackExecutor(adapters={"mock": adapter}, circuit=CircuitBreaker())
    chain = [
        ModelRef(model_id="mock-cheap", provider="mock"),
        ModelRef(model_id="mock-mid", provider="mock"),
    ]
    with pytest.raises(ContentFilteredError):
        await executor.execute(chain, _msg("#force_filter"), _PARAMS)


# ───────── quota now parameter (#240 §3) ────────────────────────────────────


def test_check_daily_token_budget_accepts_now():
    from datetime import UTC, datetime
    from unittest.mock import patch

    from src.gateway.app.core.quota import check_daily_token_budget

    fake_now = datetime(2026, 6, 15, 23, 59, 0, tzinfo=UTC)
    with patch("src.gateway.app.core.quota.sum_tokens_by_api_key", return_value=60000):
        result = check_daily_token_budget(object(), 7, 50000, now=fake_now)
    assert result == 60000


def test_check_daily_token_budget_defaults_to_utc_now():
    from unittest.mock import patch

    from src.gateway.app.core.quota import check_daily_token_budget

    with patch("src.gateway.app.core.quota.sum_tokens_by_api_key", return_value=100):
        result = check_daily_token_budget(object(), 7, 50000)
    assert result is None


def test_exhausted_models_accepts_now():
    from datetime import UTC, datetime
    from unittest.mock import MagicMock, patch

    from src.gateway.app.core.quota import QuotaGuard

    config = [{"group": "test", "models": ["m1"], "limit_tokens": 1000, "provider": "p"}]
    guard = QuotaGuard(db_factory=MagicMock, quota_config=config)

    fake_now = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
    with patch("src.gateway.app.core.quota.sum_tokens_by_model", return_value={"m1": 2000}):
        result = guard.exhausted_models(now=fake_now)
    assert ("m1", "p") in result
