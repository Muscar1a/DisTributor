"""RequestOrchestrator — AC-1 (flow) và AC-2 (fallback chain).

Content-filter không fallback (ADR-010) đã được kiểm tra ở tầng FallbackExecutor
trong test_circuit.py::test_fallback_executor_content_filter_stops_immediately.
"""

from __future__ import annotations

import pytest

from src.gateway.app.adapters.mock_adapter import MockAdapter
from src.gateway.app.core.circuit import CircuitBreaker
from src.gateway.app.core.fallback import AllProvidersFailedError, FallbackExecutor
from src.gateway.app.core.interfaces import (
    BaseAdapter,
    BaseClassifier,
    BasePolicyEngine,
    ClassificationResult,
    CompletionParams,
    CompletionResult,
    Message,
    ModelRef,
    RateLimitError,
    RoutingPlan,
    Tier,
    Usage,
)
from src.gateway.app.core.orchestrator import RequestOrchestrator


class _Classifier(BaseClassifier):
    def __init__(self, score: int = 0):
        self._score = score

    async def classify(self, messages: list[Message]) -> ClassificationResult:
        tier = Tier.T1 if self._score < 30 else (Tier.T2 if self._score < 60 else Tier.T3)
        return ClassificationResult(score=self._score, tier=tier, signals=[], classifier_version="stub", latency_ms=0)


class _Policy(BasePolicyEngine):
    def __init__(self, chain: list[ModelRef]):
        self._chain = chain

    def select(self, classification: ClassificationResult, **kwargs) -> RoutingPlan:
        return RoutingPlan(chain=self._chain, tier_effective=classification.tier, policy_applied="balanced")


def _orc(chain: list[ModelRef], score: int = 0) -> RequestOrchestrator:
    adapters = {"mock": MockAdapter()}
    fallback = FallbackExecutor(adapters=adapters, circuit=CircuitBreaker())
    return RequestOrchestrator(
        classifier=_Classifier(score),
        policy_engine=_Policy(chain),
        fallback_executor=fallback,
    )


_CHEAP = ModelRef(model_id="mock-cheap", provider="mock")
_MID = ModelRef(model_id="mock-mid", provider="mock")
_MSG = [Message(role="user", content="hello")]

# Stub adapter cho AC-2: fail retryable trên model_id đầu tiên, thành công trên model_id còn lại


class _FailFirstAdapter(BaseAdapter):
    """Raise RateLimitError với model_id trong `fail_ids`, thành công với các model còn lại."""

    provider = "mock"
    models = ["mock-cheap", "mock-mid"]
    model_capabilities = {
        "mock-cheap": frozenset({"text"}),
        "mock-mid": frozenset({"text"}),
    }

    def __init__(self, fail_ids: set[str]):
        self._fail = fail_ids

    async def complete(self, model_id: str, messages, params) -> CompletionResult:
        if model_id in self._fail:
            raise RateLimitError(f"stub 429 on {model_id}")
        return CompletionResult(
            content=f"ok from {model_id}",
            finish_reason="stop",
            usage=Usage(prompt_tokens=1, completion_tokens=1),
            provider_latency_ms=0,
        )

    def stream(self, model_id, messages, params):
        raise NotImplementedError

    async def health(self) -> bool:
        return True


def _orc_stub(chain: list[ModelRef], fail_ids: set[str], score: int = 0) -> RequestOrchestrator:
    adapter = _FailFirstAdapter(fail_ids)
    fallback = FallbackExecutor(adapters={"mock": adapter}, circuit=CircuitBreaker())
    return RequestOrchestrator(
        classifier=_Classifier(score),
        policy_engine=_Policy(chain),
        fallback_executor=fallback,
    )


# --- AC-1: classify → policy → adapter → RoutingResult -------------------------


@pytest.mark.asyncio
async def test_ac1_full_flow_returns_routing_result():
    result = await _orc([_CHEAP]).handle(_MSG, CompletionParams())

    assert result.completion.content
    assert result.completion.finish_reason == "stop"
    assert result.classification.tier == Tier.T1
    assert result.model_used.model_id == "mock-cheap"
    assert result.latency_total_ms is not None
    assert result.latency_router_ms is not None


@pytest.mark.asyncio
async def test_ac1_classifier_score_maps_to_correct_tier():
    r_t1 = await _orc([_CHEAP], score=10).handle(_MSG, CompletionParams())
    r_t2 = await _orc([_CHEAP], score=45).handle(_MSG, CompletionParams())
    r_t3 = await _orc([_CHEAP], score=80).handle(_MSG, CompletionParams())

    assert r_t1.classification.tier == Tier.T1
    assert r_t2.classification.tier == Tier.T2
    assert r_t3.classification.tier == Tier.T3


# --- AC-2: retryable → fallback; chain exhausted → AllProvidersFailedError ----


@pytest.mark.asyncio
async def test_ac2_retryable_error_triggers_fallback_to_next_model():
    result = await _orc_stub([_CHEAP, _MID], fail_ids={"mock-cheap"}).handle(_MSG, CompletionParams())

    assert result.model_used.model_id == "mock-mid"
    assert result.fallback_count == 1
    assert result.chain_attempted == ["mock-cheap", "mock-mid"]


@pytest.mark.asyncio
async def test_ac2_chain_exhausted_raises_all_providers_failed():
    with pytest.raises(AllProvidersFailedError) as exc_info:
        await _orc_stub([_CHEAP], fail_ids={"mock-cheap"}).handle(_MSG, CompletionParams())
    assert "mock-cheap" in exc_info.value.chain_attempted
