"""Tests for cross-tier fallback (#130).

Bidirectional: T3→T2→T1 (downgrade) and T1→T2→T3 (upgrade).
"""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.app.api.chat_completions import router as chat_router
from src.gateway.app.config.loader import GatewaySettings
from src.gateway.app.core.interfaces import (
    CompletionResult,
    ModelRef,
    RateLimitError,
    Tier,
    Usage,
)
from src.gateway.app.db.session import get_db


def _make_downgrade_orchestrator(fail_models: set[str], circuit_open: set[str] = frozenset()):
    from src.gateway.app.config.loader import Config, ModelPricing, PolicyRule, TierRoute
    from src.gateway.app.core.circuit import CircuitBreaker
    from src.gateway.app.core.classifier_v1 import ClassifierV1Heuristic
    from src.gateway.app.core.fallback import FallbackExecutor
    from src.gateway.app.core.orchestrator import RequestOrchestrator
    from src.gateway.app.core.policy import PolicyEngineV1

    class _FailSelectAdapter:
        provider = "mock"
        models = ["mock-cheap", "mock-mid", "mock-premium"]
        model_capabilities = {m: frozenset({"text"}) for m in models}

        async def complete(self, model_id, messages, params):
            if model_id in fail_models:
                raise RateLimitError(f"stub 429 on {model_id}")
            return CompletionResult(
                content=f"ok from {model_id}",
                finish_reason="stop",
                usage=Usage(prompt_tokens=5, completion_tokens=5),
                provider_latency_ms=1,
            )

        def stream(self, *a, **kw):
            raise NotImplementedError

        async def health(self):
            return True

    config = Config(
        tiers={
            Tier.T1: TierRoute(primary=ModelRef("mock-cheap", "mock"), fallbacks=()),
            Tier.T2: TierRoute(primary=ModelRef("mock-mid", "mock"), fallbacks=()),
            Tier.T3: TierRoute(primary=ModelRef("mock-premium", "mock"), fallbacks=()),
        },
        t1_max=30,
        t2_max=60,
        default_policy="balanced",
        policies={"balanced": PolicyRule(tier_shift=0, order_by="quality_then_cost")},
        pricing={
            "mock-cheap": ModelPricing(provider="mock", input_per_1m_usd=0.0, output_per_1m_usd=0.0, quality_rank=1),
            "mock-mid": ModelPricing(provider="mock", input_per_1m_usd=0.0, output_per_1m_usd=0.0, quality_rank=5),
            "mock-premium": ModelPricing(provider="mock", input_per_1m_usd=0.0, output_per_1m_usd=0.0, quality_rank=9),
        },
        premium_baseline_model="mock-premium",
    )
    adapter = _FailSelectAdapter()
    circuit = CircuitBreaker(failure_threshold=1)
    for model_id in circuit_open:
        ref = ModelRef(model_id=model_id, provider="mock")
        circuit.record_error(ref)  # threshold=1 -> trips immediately
    fallback = FallbackExecutor(adapters={"mock": adapter}, circuit=circuit)
    mock_caps = {m: frozenset({"text"}) for m in adapter.models}
    return RequestOrchestrator(
        classifier=ClassifierV1Heuristic(),
        policy_engine=PolicyEngineV1(config=config, model_capabilities=mock_caps),
        fallback_executor=fallback,
    )


def _mock_db():
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock(side_effect=lambda obj: setattr(obj, "id", obj.id))
    return db


@pytest.fixture
def app_factory():
    def _make(fail_models: set[str] = frozenset(), circuit_open: set[str] = frozenset()):
        app = FastAPI()
        app.include_router(chat_router, prefix="/v1")
        app.dependency_overrides[get_db] = lambda: _mock_db()
        app.state.orchestrator = _make_downgrade_orchestrator(fail_models, circuit_open)
        app.state.settings = GatewaySettings()
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _t3_payload(allow_downgrade: bool):
    return {
        "messages": [
            {
                "role": "user",
                "content": (
                    "Analyze and compare two distributed systems, "
                    "prove the latency tradeoffs mathematically, "
                    "include code, and return a detailed JSON schema"
                ),
            }
        ],
        "smartroute": {
            "force_tier": "T3",
            "allow_tier_downgrade": allow_downgrade,
        },
    }


def test_tier_downgrade_t3_to_t2_success(app_factory):
    client = app_factory(fail_models={"mock-premium"})
    resp = client.post("/v1/chat/completions", json=_t3_payload(allow_downgrade=True))

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "mock-mid"
    assert body["smartroute"]["tier_effective"] == "T2"
    assert body["smartroute"]["tier_changed"] is True
    assert resp.headers["x-sr-tier-effective"] == "T2"


def test_tier_downgrade_disabled_returns_502(app_factory):
    client = app_factory(fail_models={"mock-premium"})
    resp = client.post("/v1/chat/completions", json=_t3_payload(allow_downgrade=False))

    assert resp.status_code == 502
    assert "mock-premium" in resp.json()["error"]["details"]["chain_attempted"]


def test_tier_downgrade_all_tiers_fail_returns_502(app_factory):
    client = app_factory(fail_models={"mock-premium", "mock-mid", "mock-cheap"})
    resp = client.post("/v1/chat/completions", json=_t3_payload(allow_downgrade=True))

    assert resp.status_code == 502
    attempted = resp.json()["error"]["details"]["chain_attempted"]
    assert "mock-premium" in attempted
    assert "mock-mid" in attempted
    assert "mock-cheap" in attempted


def test_tier_downgrade_t3_skips_t2_falls_to_t1(app_factory):
    client = app_factory(fail_models={"mock-premium", "mock-mid"})
    resp = client.post("/v1/chat/completions", json=_t3_payload(allow_downgrade=True))

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "mock-cheap"
    assert body["smartroute"]["tier_effective"] == "T1"
    assert body["smartroute"]["tier_changed"] is True


def _t1_payload(allow_downgrade: bool):
    return {
        "messages": [{"role": "user", "content": "hi"}],
        "smartroute": {
            "force_tier": "T1",
            "allow_tier_downgrade": allow_downgrade,
        },
    }


def test_tier_upgrade_t1_to_t2_success(app_factory):
    """T1 fails → upward fallback → T2 succeeds."""
    client = app_factory(fail_models={"mock-cheap"})
    resp = client.post("/v1/chat/completions", json=_t1_payload(allow_downgrade=True))

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "mock-mid"
    assert body["smartroute"]["tier_effective"] == "T2"
    assert body["smartroute"]["tier_changed"] is True
    assert resp.headers["x-sr-tier-effective"] == "T2"


def test_tier_upgrade_t1_skips_t2_falls_to_t3(app_factory):
    """T1+T2 fail → upward fallback → T3 succeeds."""
    client = app_factory(fail_models={"mock-cheap", "mock-mid"})
    resp = client.post("/v1/chat/completions", json=_t1_payload(allow_downgrade=True))

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "mock-premium"
    assert body["smartroute"]["tier_effective"] == "T3"
    assert body["smartroute"]["tier_changed"] is True


def test_policy_select_fallback_circuit_open(app_factory):
    """T3 circuit-open at policy-select time (not runtime) → falls back to T2 via allow_tier_downgrade."""
    # mock-premium is pre-tripped in circuit breaker → policy select excludes it → NoCapableModelError
    client = app_factory(circuit_open={"mock-premium"})
    resp = client.post("/v1/chat/completions", json=_t3_payload(allow_downgrade=True))

    assert resp.status_code == 200
    body = resp.json()
    assert body["model"] == "mock-mid"
    assert body["smartroute"]["tier_effective"] == "T2"
    assert body["smartroute"]["tier_changed"] is True


def test_no_downgrade_without_opt_in(app_factory):
    client = app_factory(fail_models={"mock-premium"})
    resp = client.post(
        "/v1/chat/completions",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Analyze distributed systems, prove latency tradeoffs, include code, return JSON schema"
                    ),
                }
            ],
            "smartroute": {"force_tier": "T3"},
        },
    )
    assert resp.status_code == 502
