from types import SimpleNamespace

import pytest

from src.gateway.app.config.loader import load_config
from src.gateway.app.core.fallback import FallbackExecutor
from src.gateway.app.core.interfaces import (
    ClassificationResult,
    CompletionParams,
    Message,
    Tier,
)
from src.gateway.app.core.policy import PolicyEngineV1
from src.gateway.app.main import _build_adapters, _with_mock_routes

EXPECTED_MODEL_BY_TIER = {
    Tier.T1: "mock-cheap",
    Tier.T2: "mock-mid",
    Tier.T3: "mock-premium",
}


def _mock_runtime():
    config = _with_mock_routes(load_config())
    adapters = _build_adapters(SimpleNamespace(use_mock_providers=True))
    capabilities = {
        model_id: capabilities
        for adapter in adapters.values()
        for model_id, capabilities in adapter.model_capabilities.items()
    }
    return config, adapters, capabilities


def test_mock_routes_match_the_mock_adapter_registry() -> None:
    config, adapters, capabilities = _mock_runtime()

    assert set(adapters) == {"mock"}
    for tier, expected_model in EXPECTED_MODEL_BY_TIER.items():
        route = config.tiers[tier]
        assert route.primary.model_id == expected_model
        assert route.primary.provider in adapters
        assert route.primary.model_id in capabilities
        assert route.fallbacks == ()
        assert config.pricing[expected_model].provider == "mock"


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", list(Tier))
async def test_each_tier_completes_in_mock_mode(tier: Tier) -> None:
    config, adapters, capabilities = _mock_runtime()
    policy = PolicyEngineV1(config=config, model_capabilities=capabilities)
    plan = policy.select(
        ClassificationResult(
            score=0,
            tier=tier,
            signals=[],
            classifier_version="test",
            latency_ms=0,
        ),
        force_tier=tier,
    )

    result = await FallbackExecutor(adapters=adapters).execute(
        plan.chain,
        [Message(role="user", content="load-test smoke")],
        CompletionParams(max_tokens=16),
    )

    assert result.chain_attempted == [EXPECTED_MODEL_BY_TIER[tier]]
    assert result.result.content
