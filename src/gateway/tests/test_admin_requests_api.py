import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src.gateway.app.db.models import Feedback, RequestLog
from src.gateway.app.db.session import SessionLocal, get_db
from src.gateway.app.main import app


@pytest.fixture
def admin_client(monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "test-admin-key")
    monkeypatch.setenv("APP_ENV", "test")

    with SessionLocal() as s:
        s.query(Feedback).delete()
        s.query(RequestLog).delete()
        s.commit()

    def override_get_db():
        with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, SessionLocal
    finally:
        app.dependency_overrides.clear()


def test_admin_requests_empty_list(admin_client):
    client, _ = admin_client
    response = client.get("/admin/requests", headers={"X-Admin-Key": "test-admin-key"})
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["page"] == 1
    assert data["page_size"] == 50


def test_admin_requests_filtering_and_pagination(admin_client):
    client, session_factory = admin_client

    req1_id = uuid.uuid4()
    req2_id = uuid.uuid4()
    req3_id = uuid.uuid4()

    now = datetime.utcnow()
    with session_factory() as db:
        r1 = RequestLog(
            id=req1_id,
            ts=now - timedelta(minutes=10),
            tier="T1",
            provider="google",
            model="gemini-flash-lite",
            status="ok",
            fallback_count=0,
            cost_usd=Decimal("0.000100"),
            difficulty_score=15,
        )
        r2 = RequestLog(
            id=req2_id,
            ts=now - timedelta(minutes=5),
            tier="T3",
            provider="anthropic",
            model="claude-3-5-sonnet",
            status="ok",
            fallback_count=2,
            cost_usd=Decimal("0.005000"),
            difficulty_score=85,
        )
        r3 = RequestLog(
            id=req3_id,
            ts=now,
            tier="T2",
            provider="groq",
            model="llama-3.3-70b-versatile",
            status="error",
            fallback_count=1,
            cost_usd=Decimal("0.000800"),
            difficulty_score=50,
        )
        db.add_all([r1, r2, r3])
        db.commit()

    # Total list
    res = client.get("/admin/requests", headers={"X-Admin-Key": "test-admin-key"})
    assert res.status_code == 200
    assert res.json()["total"] == 3
    assert len(res.json()["items"]) == 3

    # Filter by tier
    res_t3 = client.get("/admin/requests?tier=T3", headers={"X-Admin-Key": "test-admin-key"})
    assert res_t3.json()["total"] == 1
    assert res_t3.json()["items"][0]["id"] == str(req2_id)

    # Filter by provider
    res_prov = client.get("/admin/requests?provider=groq", headers={"X-Admin-Key": "test-admin-key"})
    assert res_prov.json()["total"] == 1
    assert res_prov.json()["items"][0]["id"] == str(req3_id)

    # Filter by status
    res_err = client.get("/admin/requests?status=error", headers={"X-Admin-Key": "test-admin-key"})
    assert res_err.json()["total"] == 1
    assert res_err.json()["items"][0]["id"] == str(req3_id)

    # Filter by min_fallback
    res_fb = client.get("/admin/requests?min_fallback=1", headers={"X-Admin-Key": "test-admin-key"})
    assert res_fb.json()["total"] == 2

    # Filter by search q (prefix of req1_id)
    res_q = client.get(f"/admin/requests?q={str(req1_id)[:8]}", headers={"X-Admin-Key": "test-admin-key"})
    assert res_q.json()["total"] == 1
    assert res_q.json()["items"][0]["id"] == str(req1_id)

    # Pagination
    res_p1 = client.get("/admin/requests?page=1&page_size=2", headers={"X-Admin-Key": "test-admin-key"})
    assert len(res_p1.json()["items"]) == 2
    assert res_p1.json()["total"] == 3

    res_p2 = client.get("/admin/requests?page=2&page_size=2", headers={"X-Admin-Key": "test-admin-key"})
    assert len(res_p2.json()["items"]) == 1


def test_admin_request_detail_and_feedback(admin_client):
    client, session_factory = admin_client
    req_id = uuid.uuid4()
    with session_factory() as db:
        r = RequestLog(
            id=req_id,
            tier="T2",
            provider="google",
            model="gemini-2.5-flash",
            difficulty_score=45,
            policy="balanced",
            signals=[{"name": "code", "score": 25}],
            chain_attempted=[{"model": "gemini-2.5-flash", "provider": "google", "status": "ok"}],
            classifier_version="heuristic-v1",
            messages=[{"role": "user", "content": "Explain quantum mechanics"}],
            response_content="Quantum mechanics is a fundamental theory in physics...",
            status="ok",
            latency_total_ms=1200,
            latency_router_ms=35,
        )
        fb = Feedback(
            request_id=req_id,
            tags=["Chính xác", "Nhanh"],
            note="Great answer!",
        )
        db.add(r)
        db.add(fb)
        db.commit()

    res = client.get(f"/admin/requests/{req_id}", headers={"X-Admin-Key": "test-admin-key"})
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == str(req_id)
    assert data["difficulty_score"] == 45
    assert data["tier"] == "T2"
    assert data["signals"] == [{"name": "code", "score": 25}]
    assert data["prompt_preview"] == "Explain quantum mechanics"
    assert "fundamental theory" in data["response_preview"]
    assert data["feedback"]["tags"] == ["Chính xác", "Nhanh"]
    assert data["feedback"]["note"] == "Great answer!"


def test_admin_request_detail_not_found(admin_client):
    client, _ = admin_client
    res = client.get(f"/admin/requests/{uuid.uuid4()}", headers={"X-Admin-Key": "test-admin-key"})
    assert res.status_code == 404
    assert "not found" in str(res.json()["error"]["message"]).lower()


@pytest.mark.parametrize("path", ["/admin/stats", "/admin/requests", "/admin/logs"])
def test_admin_time_ranges_reject_reversed_bounds_with_stable_error(admin_client, path):
    client, _ = admin_client
    response = client.get(
        path,
        params={"from": "2026-08-02T00:00:00Z", "to": "2026-08-01T00:00:00Z"},
        headers={"X-Admin-Key": "test-admin-key"},
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_time_range"
    assert error["details"] == {
        "fields": ["from", "to"],
        "from_inclusive": True,
        "to_exclusive": True,
    }


@pytest.mark.parametrize(
    ("path", "empty_field"),
    [("/admin/stats", "totals"), ("/admin/requests", "total"), ("/admin/logs", "items")],
)
def test_admin_time_ranges_accept_equal_bounds_as_empty(admin_client, path, empty_field):
    client, _ = admin_client
    response = client.get(
        path,
        params={"from": "2026-08-01T00:00:00Z", "to": "2026-08-01T00:00:00Z"},
        headers={"X-Admin-Key": "test-admin-key"},
    )

    assert response.status_code == 200
    value = response.json()[empty_field]
    if empty_field == "totals":
        assert value["requests"] == 0
    else:
        expected = 0 if empty_field == "total" else []
        assert value == expected


def test_admin_surfaces_reconcile_offset_range_and_utc_day_boundaries(admin_client):
    client, session_factory = admin_client
    lower_id, next_day_id, upper_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    lower = datetime(2026, 8, 1, 23, 0, tzinfo=UTC).replace(tzinfo=None)
    next_day = datetime(2026, 8, 2, 0, 30, tzinfo=UTC).replace(tzinfo=None)
    upper = datetime(2026, 8, 2, 1, 0, tzinfo=UTC).replace(tzinfo=None)

    with session_factory() as db:
        db.add_all(
            [
                RequestLog(
                    id=lower_id,
                    ts=lower,
                    tier="T1",
                    provider="google",
                    model="gemini-flash-lite",
                    status="ok",
                    prompt_tokens=10,
                    completion_tokens=20,
                    cost_usd=Decimal("0.001000"),
                ),
                RequestLog(
                    id=next_day_id,
                    ts=next_day,
                    tier="T2",
                    provider="groq",
                    model="llama-3.3-70b",
                    status="error",
                    cost_usd=Decimal("9.000000"),
                ),
                RequestLog(
                    id=upper_id,
                    ts=upper,
                    tier="T3",
                    provider="openai",
                    model="gpt-4o",
                    status="ok",
                    cost_usd=Decimal("8.000000"),
                ),
            ]
        )
        db.commit()

    params = {"from": "2026-08-02T01:00:00+02:00", "to": "2026-08-02T03:00:00+02:00"}
    headers = {"X-Admin-Key": "test-admin-key"}
    stats = client.get("/admin/stats", params=params, headers=headers)
    requests = client.get("/admin/requests", params=params, headers=headers)
    logs = client.get("/admin/logs", params=params, headers=headers)

    assert stats.status_code == requests.status_code == logs.status_code == 200
    stats_body = stats.json()
    assert stats_body["from"] == "2026-08-01T23:00:00Z"
    assert stats_body["to"] == "2026-08-02T01:00:00Z"
    assert stats_body["totals"]["requests"] == 2
    assert stats_body["totals"]["success_rate"] == 0.5
    assert stats_body["totals"]["cost_usd"] == 0.001
    assert stats_body["totals"]["total_tokens"] == 30
    assert sum(item["requests"] for item in stats_body["by_tier"]) == 2
    assert sum(item["requests"] for item in stats_body["by_provider"]) == 2
    assert [(item["date"], item["requests"], item["cost_usd"]) for item in stats_body["series"]] == [
        ("2026-08-01", 1, 0.001),
        ("2026-08-02", 1, 0.0),
    ]

    expected_ids = {str(lower_id), str(next_day_id)}
    assert requests.json()["total"] == 2
    assert {item["id"] for item in requests.json()["items"]} == expected_ids
    assert {item["request_id"] for item in logs.json()["items"]} == expected_ids
    assert client.get(f"/admin/requests/{lower_id}", headers=headers).status_code == 200
    assert str(upper_id) not in requests.text
