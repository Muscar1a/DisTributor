"""Tests for TierRateLimiter và orchestrator downgrade logic (issue #104)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gateway.app.core.interfaces import Tier
from src.gateway.app.core.tier_limiter import TierRateLimiter

# ---------------------------------------------------------------------------
# TierRateLimiter unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consume_returns_false_when_limit_exceeded():
    limiter = TierRateLimiter({"T3": 2})
    assert await limiter.consume("T3") is True
    assert await limiter.consume("T3") is True
    assert await limiter.consume("T3") is False


@pytest.mark.asyncio
async def test_consume_returns_true_when_within_limit():
    limiter = TierRateLimiter({"T3": 5})
    for _ in range(5):
        assert await limiter.consume("T3") is True


@pytest.mark.asyncio
async def test_consume_unlimited_when_rpm_is_zero():
    limiter = TierRateLimiter({"T3": 0})
    for _ in range(100):
        assert await limiter.consume("T3") is True


@pytest.mark.asyncio
async def test_consume_allows_after_window_expires():
    with patch("src.gateway.app.core.tier_limiter.time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        limiter = TierRateLimiter({"T3": 1}, window_s=60.0)
        assert await limiter.consume("T3") is True
        assert await limiter.consume("T3") is False

        mock_time.return_value = 61.0
        assert await limiter.consume("T3") is True


@pytest.mark.asyncio
async def test_unlimited_tier_passes_through():
    """Tier không có trong limits dict được coi là unlimited."""
    limiter = TierRateLimiter({"T3": 1})
    for _ in range(10):
        assert await limiter.consume("T1") is True
        assert await limiter.consume("T2") is True


# ---------------------------------------------------------------------------
# Orchestrator downgrade logic
# ---------------------------------------------------------------------------


def _make_orchestrator(consume_return: bool, tier: Tier):
    from src.gateway.app.core.orchestrator import RequestOrchestrator

    tier_limiter = AsyncMock(spec=TierRateLimiter)
    tier_limiter.consume.return_value = consume_return

    classification = MagicMock()
    classification.tier = tier

    classifier = AsyncMock()
    classifier.classify.return_value = classification

    plan = MagicMock()
    plan.chain = [MagicMock(model_id="m1")]

    policy = MagicMock()
    policy.select.return_value = plan

    fb_result = MagicMock()
    fb_result.chain_attempted = ["m1"]
    fb_result.fallback_count = 0
    fb_result.result = MagicMock(usage=MagicMock())

    fallback = MagicMock()
    fallback.circuit.open_set.return_value = frozenset()
    fallback.execute = AsyncMock(return_value=fb_result)

    orch = RequestOrchestrator(
        classifier=classifier,
        policy_engine=policy,
        fallback_executor=fallback,
        tier_limiter=tier_limiter,
    )
    return orch, policy


@pytest.mark.asyncio
async def test_orchestrator_downgrades_t3_to_t2_when_limited():
    orch, policy = _make_orchestrator(consume_return=False, tier=Tier.T3)
    await orch.handle(messages=[], params=MagicMock())
    assert policy.select.call_args[1]["force_tier"] == Tier.T2


@pytest.mark.asyncio
async def test_orchestrator_downgrades_t2_to_t1_when_limited():
    orch, policy = _make_orchestrator(consume_return=False, tier=Tier.T2)
    await orch.handle(messages=[], params=MagicMock())
    assert policy.select.call_args[1]["force_tier"] == Tier.T1


@pytest.mark.asyncio
async def test_orchestrator_does_not_downgrade_when_allowed():
    orch, policy = _make_orchestrator(consume_return=True, tier=Tier.T3)
    await orch.handle(messages=[], params=MagicMock())
    assert policy.select.call_args[1]["force_tier"] is None
