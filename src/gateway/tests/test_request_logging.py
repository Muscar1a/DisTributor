# Regression tests for issue #28 — two-phase request log commit ordering.

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.app.api.admin import router as admin_router
from src.gateway.app.api.chat_completions import _database_api_key_id
from src.gateway.app.api.chat_completions import router as chat_router
from src.gateway.app.api.health import router as health_router
from src.gateway.app.config.loader import GatewaySettings
from src.gateway.app.core.interfaces import CompletionResult, ModelRef, Tier, Usage
from src.gateway.app.core.provider_status import ProviderStatusRegistry
from src.gateway.app.db.crud import create_request_log
from src.gateway.app.db.models import Feedback, RequestLog
from src.gateway.app.db.session import SessionLocal, get_db


def _make_test_orchestrator(adapter=None):
    """Build a minimal orchestrator routing all tiers to the mock provider."""
    from src.gateway.app.adapters.mock_adapter import MockAdapter
    from src.gateway.app.config.loader import Config, ModelPricing, PolicyRule, TierRoute
    from src.gateway.app.core.circuit import CircuitBreaker
    from src.gateway.app.core.classifier_v1 import ClassifierV1Heuristic
    from src.gateway.app.core.fallback import FallbackExecutor
    from src.gateway.app.core.orchestrator import RequestOrchestrator
    from src.gateway.app.core.policy import PolicyEngineV1

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
    mock_caps = {m: frozenset({"text"}) for m in ["mock-cheap", "mock-mid", "mock-premium"]}
    actual_adapter = adapter or MockAdapter()
    circuit = CircuitBreaker()
    fallback = FallbackExecutor(adapters={"mock": actual_adapter}, circuit=circuit)
    return RequestOrchestrator(
        classifier=ClassifierV1Heuristic(),
        policy_engine=PolicyEngineV1(config=config, model_capabilities=mock_caps),
        fallback_executor=fallback,
    )


def test_database_api_key_id_excludes_dev_limiter_identity():
    assert _database_api_key_id(SimpleNamespace(state=SimpleNamespace(api_key_id=42))) == 42
    assert _database_api_key_id(SimpleNamespace(state=SimpleNamespace(api_key_id="dev:hash"))) is None


@pytest.fixture
def db_setup():
    with SessionLocal() as s:
        s.query(Feedback).delete()
        s.query(RequestLog).delete()
        s.commit()

    app = FastAPI()
    app.include_router(chat_router, prefix="/v1")
    app.include_router(admin_router, prefix="/admin")
    app.include_router(health_router)

    def override_db():
        with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    orchestrator = _make_test_orchestrator()
    app.state.orchestrator = orchestrator
    app.state.settings = GatewaySettings()
    app.state.config = orchestrator.policy_engine.config
    app.state.provider_registry = ProviderStatusRegistry(
        orchestrator.policy_engine.config,
        orchestrator.fallback_executor.adapters,
        orchestrator.fallback_executor.circuit,
    )
    return SessionLocal, app, TestClient(app)


def test_phase_one_is_committed_before_provider_and_phase_two_completes(db_setup):
    session_factory, app, client = db_setup

    class InspectingAdapter:
        provider = "mock"

        async def complete(self, model_id, messages, params):
            with session_factory() as db:
                pending = db.query(RequestLog).one()
                assert pending.status == "pending"
                assert pending.prompt_tokens is None
            return CompletionResult(
                content="done",
                finish_reason="stop",
                usage=Usage(prompt_tokens=11, completion_tokens=7),
                provider_latency_ms=1,
            )

    app.state.orchestrator = _make_test_orchestrator(InspectingAdapter())
    response = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hello"}]})

    assert response.status_code == 200
    request_id = response.headers["x-sr-request-id"]
    usage = client.get(f"/v1/usage/{request_id}").json()
    assert usage["status"] == "complete"
    assert usage["smartroute"]["cost_usd"] == 0.0
    with session_factory() as db:
        log = db.get(RequestLog, uuid.UUID(request_id))
        assert log.status == "ok"
        assert log.prompt_tokens == 11
        assert log.completion_tokens == 7


def test_usage_returns_pending_instead_of_404(db_setup):
    session_factory, _, client = db_setup
    with session_factory() as db:
        log = create_request_log(
            db,
            {
                "difficulty_score": 0,
                "tier": "T1",
                "signals": [],
                "policy": "balanced",
                "model": "mock-cheap",
                "provider": "mock",
                "classifier_version": "heuristic-v1",
                "status": "pending",
            },
        )
        request_id = log.id

    response = client.get(f"/v1/usage/{request_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["smartroute"]["cost_usd"] is None


def test_admin_stats_matches_contract_and_calculates_savings(db_setup):
    session_factory, _, client = db_setup
    with session_factory() as db:
        create_request_log(
            db,
            {
                "tier": "T1",
                "provider": "mock",
                "model": "mock-cheap",
                "prompt_tokens": 1000,
                "completion_tokens": 1000,
                "cost_usd": Decimal("0.001000"),
                "latency_total_ms": 200,
                "latency_router_ms": 20,
                "status": "ok",
            },
        )

    response = client.get("/admin/stats")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "from",
        "to",
        "baseline_model",
        "totals",
        "by_tier",
        "by_provider",
        "tokens_by_model",
        "series",
    }
    assert body["totals"]["requests"] == 1
    assert body["totals"]["baseline_premium_cost_usd"] == 0.0175
    assert body["totals"]["savings_pct"] == 94.29
    assert body["totals"]["success_rate"] == 1.0
    assert body["totals"]["total_tokens"] == 2000
    assert body["tokens_by_model"] == [
        {"model": "mock-cheap", "prompt_tokens": 1000, "completion_tokens": 1000, "total_tokens": 2000}
    ]


def test_admin_logs_returns_recent_logs_newest_first(db_setup):
    session_factory, _, client = db_setup
    with session_factory() as db:
        create_request_log(
            db,
            {
                "tier": "T1",
                "model": "mock-cheap",
                "provider": "mock",
                "cost_usd": Decimal("0.001000"),
                "latency_total_ms": 100,
                "status": "ok",
            },
        )
        create_request_log(
            db,
            {
                "tier": "T3",
                "model": "mock-premium",
                "provider": "mock",
                "cost_usd": None,
                "latency_total_ms": None,
                "status": "error",
            },
        )

    response = client.get("/admin/logs")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    # Newest first: log thứ hai vừa tạo sau log thứ nhất.
    newest = items[0]
    assert set(newest) == {
        "request_id",
        "ts",
        "tier",
        "model",
        "provider",
        "cost_usd",
        "latency_total_ms",
        "status",
    }
    assert newest["tier"] == "T3"
    assert newest["status"] == "error"
    assert newest["cost_usd"] is None
    assert newest["latency_total_ms"] is None


def test_admin_logs_respects_limit_and_date_range(db_setup):
    session_factory, _, client = db_setup
    with session_factory() as db:
        for i in range(5):
            create_request_log(db, {"tier": "T1", "status": "ok"})

    resp = client.get("/admin/logs?limit=3")
    assert len(resp.json()["items"]) == 3

    far_past = datetime(2000, 1, 1, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    resp = client.get(f"/admin/logs?from={far_past}&to={far_past}")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_health_and_readiness_match_openapi_schema(db_setup, monkeypatch):
    _, _, client = db_setup
    monkeypatch.setenv("APP_VERSION", "1.0.0")
    monkeypatch.setenv("GIT_COMMIT_SHA", "18bfbaa1234567890abcdef1234567890abcdef1")
    monkeypatch.setenv("BUILD_TIMESTAMP", "2026-08-29T00:00:00Z")
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "version": "1.0.0",
        "commit_sha": "18bfbaa",
        "build_timestamp": "2026-08-29T00:00:00Z",
        "db": "ok",
        "classifier_error_rate": 0.0,
        "providers": [
            {
                "provider": "mock",
                "status": "available",
                "configured": True,
                "available": True,
                "circuit": "closed",
                "consecutive_errors": 0,
                "open_until": None,
            }
        ],
    }
    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "checks": {"database": "ok", "config": "ok", "providers": "ok"},
    }
