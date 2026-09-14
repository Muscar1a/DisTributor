"""Integration test: policy switching in Playground and SessionRouter interaction."""

import os

import pytest
from fastapi.testclient import TestClient

from src.gateway.app.core.classifier_v1_5 import ClassifierV1_5Heuristic
from src.gateway.app.core.interfaces import ClassificationResult, Message, Tier
from src.gateway.app.core.policy import PolicyEngineV1
from src.gateway.app.core.session_router import SessionRouter
from src.gateway.app.core.session_router.state import SessionState


@pytest.fixture(scope="module")
def client():
    os.environ["USE_MOCK_PROVIDERS"] = "true"
    from src.gateway.app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture
def classifier():
    return ClassifierV1_5Heuristic()


@pytest.fixture
def policy_engine():
    return PolicyEngineV1()


@pytest.fixture
def session_router():
    return SessionRouter(t1_max=30, t2_max=60)


@pytest.mark.asyncio
async def test_policy_tier_shift_unit(classifier, policy_engine):
    # Prompt C2 standard (score = 32) — must be > 15 words to avoid brevity → C1
    messages = [Message(role="user", content="Viết hàm tính toán dữ liệu đầu vào bằng Python rồi xử lý từng phần tử và trả về kết quả dưới dạng list dict")]
    cls = await classifier.classify(messages)
    assert cls.score == 32
    assert cls.tier == Tier.T2

    # 1. balanced (shift 0) -> T2
    plan_balanced = policy_engine.select(cls, policy="balanced")
    assert plan_balanced.tier_effective == Tier.T2

    # 2. cost_first (shift -10) -> score becomes 22 -> drops to T1
    plan_cost = policy_engine.select(cls, policy="cost_first")
    assert plan_cost.tier_effective == Tier.T1

    # 3. quality_first (shift +10) -> score becomes 42 -> stays T2
    plan_quality = policy_engine.select(cls, policy="quality_first")
    assert plan_quality.tier_effective == Tier.T2


@pytest.mark.asyncio
async def test_policy_quality_first_promotes_to_t3(classifier, policy_engine):
    # Prompt C2 with modifiers (base 32 + artifact_large 6 + multi_file 6 + output_constraint 6 = 50)
    prompt_c2_mod = (
        "Tối ưu các hàm trong services.py và models.py, yêu cầu trả về json schema chính xác:\n"
        "```python\n"
        + "x = 1\n" * 160  # artifact > 150 tokens
        + "```"
    )
    messages = [Message(role="user", content=prompt_c2_mod)]
    cls = await classifier.classify(messages)
    assert cls.score == 50
    assert cls.tier == Tier.T2

    # 1. balanced -> T2
    plan_balanced = policy_engine.select(cls, policy="balanced")
    assert plan_balanced.tier_effective == Tier.T2

    # 2. quality_first -> 50 + 10 = 60 -> promotes to T3
    plan_quality = policy_engine.select(cls, policy="quality_first")
    assert plan_quality.tier_effective == Tier.T3


@pytest.mark.asyncio
async def test_session_router_floor_tier_preserves_failure_safety(session_router, policy_engine):
    # Turn 1: user ran on T1 and it failed
    state = SessionState(
        turn_count=1,
        current_tier="T1",
        failed_tier="T1",
        unresolved_failure=True,
    )
    # Turn 2: user reports failure with low-scoring text
    cls = ClassificationResult(
        score=10,
        tier=Tier.T1,
        signals=[],
        classifier_version="heuristic-v1.5",
        latency_ms=1,
    )
    messages = [
        {"role": "user", "content": "Viết code"},
        {"role": "assistant", "content": "def foo(): pass"},
        {"role": "user", "content": "Code bạn viết bị lỗi rồi, vẫn không chạy được"},
    ]

    tier, signals, new_state, floor_tier, effective_score = session_router.route(messages, state, cls)
    assert floor_tier == Tier.T2

    # Even with cost_first (shift -10), floor_tier prevents dropping below T2
    effective_cls = ClassificationResult(
        score=effective_score,
        tier=Tier.T1,
        signals=cls.signals,
        classifier_version=cls.classifier_version,
        latency_ms=1,
    )
    plan = policy_engine.select(effective_cls, policy="cost_first", floor_tier=floor_tier)
    assert plan.tier_effective == Tier.T2


def test_chat_completions_playground_policy_switch(client):
    from unittest.mock import AsyncMock

    from src.gateway.app.core.fallback import FallbackResult
    from src.gateway.app.core.interfaces import CompletionResult, Usage

    mock_exec = AsyncMock(
        return_value=FallbackResult(
            result=CompletionResult(
                content="mock response",
                finish_reason="stop",
                usage=Usage(prompt_tokens=5, completion_tokens=5),
                provider_latency_ms=10,
            ),
            chain_attempted=["mock-model"],
            fallback_count=0,
        )
    )
    client.app.state.orchestrator.fallback_executor.execute = mock_exec

    # Prompt C2 standard (score = 32) — must be > 15 words to avoid brevity → C1
    prompt = "Viết hàm tính toán dữ liệu đầu vào bằng Python rồi xử lý từng phần tử và trả về kết quả dưới dạng list dict"

    # 1. Request with policy: balanced -> T2
    r_balanced = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": prompt}],
            "smartroute": {
                "policy": "balanced",
                "classifier_version": "v1.5",
            },
        },
    )
    assert r_balanced.status_code == 200
    assert r_balanced.headers.get("X-SR-Tier-Effective") == "T2"

    # 2. Request with policy: cost_first -> T1
    r_cost = client.post(
        "/v1/chat/completions",
        json={
            "model": "auto",
            "messages": [{"role": "user", "content": prompt}],
            "smartroute": {
                "policy": "cost_first",
                "classifier_version": "v1.5",
            },
        },
    )
    assert r_cost.status_code == 200
    assert r_cost.headers.get("X-SR-Tier-Effective") == "T1"
