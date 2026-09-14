"""OutcomeObserver (§9) + router cost accounting (§9.1)."""

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.app.api.admin import router as admin_router
from src.gateway.app.api.chat_completions import router as chat_router
from src.gateway.app.api.feedback import router as feedback_router
from src.gateway.app.api.sessions import router as sessions_router
from src.gateway.app.config.loader import GatewaySettings, load_routing_config
from src.gateway.app.core.interfaces import CompletionResult, Usage
from src.gateway.app.core.outcome_observer import OutcomeObserver
from src.gateway.app.core.session_router import SessionRouter
from src.gateway.app.core.session_router.state import SessionState
from src.gateway.app.db.crud import (
    create_session,
    get_request_log,
    get_routing_state,
    update_routing_state,
)
from src.gateway.app.db.session import SessionLocal, get_db
from src.gateway.tests.test_request_logging import _make_test_orchestrator


@pytest.fixture(scope="module")
def client():
    """Same mock-tier app as the issue-28 tests, plus session router + observer."""
    app = FastAPI()
    app.include_router(chat_router, prefix="/v1")
    app.include_router(sessions_router, prefix="/v1")
    app.include_router(feedback_router, prefix="/v1")
    app.include_router(admin_router, prefix="/admin")

    def override_db():
        with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    app.state.orchestrator = _make_test_orchestrator()
    app.state.settings = GatewaySettings()
    app.state.session_router = SessionRouter(t1_max=30, t2_max=60)
    app.state.routing_config = load_routing_config()
    app.state.outcome_observer = OutcomeObserver(db_factory=SessionLocal)
    return TestClient(app)


@pytest.fixture
def observer():
    return OutcomeObserver(db_factory=SessionLocal)


@pytest.fixture
def session_at_t2():
    """Session whose routing_state already sits at turn 1, tier T2."""
    with SessionLocal() as db:
        stored = create_session(db, {})
        state = SessionState(turn_count=1, current_tier="T2", ema_score=45.0)
        assert update_routing_state(db, stored.id, state.to_dict())
        return stored.id


# --- detection (pure) ------------------------------------------------------


@pytest.mark.parametrize(
    "content,finish,score,expected",
    [
        ("I cannot help with that request.", "stop", 70, "refusal"),
        ("Tôi không thể hỗ trợ yêu cầu này.", "stop", 70, "refusal"),
        ("def f():\n    return 1", "length", 70, "truncated_output"),
        ("Ok.", "stop", 70, "abnormally_short"),
        ("Ok.", "stop", 10, None),  # short but the task was easy — not evidence
        ("A" * 200, "stop", 70, None),
        ("", "stop", 70, None),
    ],
)
def test_detect(observer, content, finish, score, expected):
    evidence = observer.detect(content, finish, score)
    assert (evidence.name if evidence else None) == expected


def test_refusal_inside_code_block_is_not_evidence(observer):
    content = 'Ví dụ:\n```python\nprint("I cannot help with that")\n```\nBạn chạy thử nhé.'
    assert observer.detect(content, "stop", 70) is None


# --- persistence: evidence → request row + session state -------------------


def test_refusal_from_provider_flags_the_session_automatically(client, monkeypatch, session_at_t2):
    """Phase-2 wiring: no manual call — the observer runs off the real response."""

    class RefusingAdapter:
        provider = "mock"

        async def complete(self, model_id, messages, params):
            return CompletionResult(
                content="I cannot help with that request.",
                finish_reason="stop",
                usage=Usage(prompt_tokens=10, completion_tokens=8),
                provider_latency_ms=1,
            )

    monkeypatch.setattr(client.app.state, "orchestrator", _make_test_orchestrator(RefusingAdapter()))
    resp = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Explain how a thread pool schedules work"}],
            "smartroute": {"session_id": str(session_at_t2)},
        },
    )
    assert resp.status_code == 200
    request_id = resp.json()["smartroute"]["request_id"]

    with SessionLocal() as db:
        log = get_request_log(db, request_id)
        assert log.outcome_evidence["name"] == "refusal"
        assert log.outcome_evidence["tier"] == log.tier
        state = SessionState.from_dict(get_routing_state(db, session_at_t2)[0])
        assert state.unresolved_failure is True
        assert state.failed_tier == log.tier
        # regression: the observer writes at the current turn — the monotonic
        # guard in update_routing_state must not drop it (§4.1)
        assert state.failure_streak == 1


def test_clean_response_leaves_no_evidence(client, session_at_t2):
    resp = client.post(
        "/v1/chat/completions",
        json={
            "messages": [{"role": "user", "content": "Explain how a thread pool schedules work"}],
            "smartroute": {"session_id": str(session_at_t2)},
        },
    )
    assert resp.status_code == 200
    with SessionLocal() as db:
        assert get_request_log(db, resp.json()["smartroute"]["request_id"]).outcome_evidence is None
        assert SessionState.from_dict(get_routing_state(db, session_at_t2)[0]).unresolved_failure is False


def test_observe_is_cas_guarded_against_a_newer_turn(observer, session_at_t2):
    with SessionLocal() as db:
        assert update_routing_state(db, session_at_t2, SessionState(turn_count=9).to_dict())
    # expected_turn_count is stale → the router's newer write wins, evidence dropped
    assert observer.record(session_at_t2, "feedback_negative", "stale", None) is True
    from src.gateway.app.core.outcome_observer import apply_evidence_to_state

    with SessionLocal() as db:
        assert apply_evidence_to_state(db, session_at_t2, "feedback_negative", None, 1) is False


def test_record_positive_clears_failure(observer, session_at_t2):
    assert observer.record(session_at_t2, "feedback_negative", "test") is True
    assert observer.record(session_at_t2, "feedback_positive", "test") is True

    with SessionLocal() as db:
        state = SessionState.from_dict(get_routing_state(db, session_at_t2)[0])
        assert state.unresolved_failure is False
        assert state.failed_tier is None
        assert state.failure_streak == 0


def test_record_rejects_unknown_evidence(observer, session_at_t2):
    assert observer.record(session_at_t2, "vibes_bad", "test") is False


def test_session_feedback_endpoint_feeds_observer(client, session_at_t2):
    resp = client.post(
        "/v1/session-feedback",
        json={"session_id": str(session_at_t2), "tags": ["Nên dùng model mạnh hơn"]},
    )
    assert resp.status_code == 201

    with SessionLocal() as db:
        assert SessionState.from_dict(get_routing_state(db, session_at_t2)[0]).unresolved_failure is True


def test_inconsistent_routing_tag_is_not_failure_evidence(client):
    with SessionLocal() as db:
        sid = create_session(db, {}).id
        assert update_routing_state(db, sid, SessionState(turn_count=1, current_tier="T2").to_dict())

    resp = client.post(
        "/v1/session-feedback",
        json={"session_id": str(sid), "tags": ["Routing không nhất quán"]},
    )
    assert resp.status_code == 201

    with SessionLocal() as db:
        assert SessionState.from_dict(get_routing_state(db, sid)[0]).unresolved_failure is False


# --- router cost accounting (§9.1) -----------------------------------------


def test_heuristic_router_costs_zero(client):
    resp = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "What is 2+2?"}]})
    assert resp.status_code == 200
    meta = resp.json()["smartroute"]
    assert meta["router_cost_usd"] == 0.0

    with SessionLocal() as db:
        assert Decimal(get_request_log(db, meta["request_id"]).router_cost_usd) == 0


def test_classifier_cost_lands_on_the_request_row(client, monkeypatch):
    """A paying classifier (v2) must show up as router_cost_usd, not vanish."""
    import dataclasses

    orchestrator = client.app.state.orchestrator
    original = orchestrator.classifier.classify

    async def paying_classify(messages):
        return dataclasses.replace(await original(messages), cost_usd=Decimal("0.00002"))

    monkeypatch.setattr(orchestrator.classifier, "classify", paying_classify)
    resp = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 200
    meta = resp.json()["smartroute"]
    assert meta["router_cost_usd"] == pytest.approx(0.00002)

    with SessionLocal() as db:
        assert Decimal(get_request_log(db, meta["request_id"]).router_cost_usd) == Decimal("0.000020")


def test_stats_savings_is_net_of_router_cost(client):
    totals = client.get("/admin/stats").json()["totals"]
    assert totals["net_cost_usd"] == pytest.approx(totals["cost_usd"] + totals["router_cost_usd"])
