import uuid
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.gateway.app.db.models import Feedback, RequestLog, Session, SessionFeedback
from src.gateway.app.db.session import SessionLocal, get_db
from src.gateway.app.main import app


@pytest.fixture
def session_client(monkeypatch):
    def override_get_db():
        with SessionLocal() as db:
            yield db

    monkeypatch.delenv("GATEWAY_DEV_KEY", raising=False)
    monkeypatch.delenv("API_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client, SessionLocal
    finally:
        app.dependency_overrides.clear()


def test_list_sessions_format(session_client):
    client, _ = session_client
    response = client.get("/v1/sessions")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert isinstance(data["items"], list)
    assert isinstance(data["total"], int)



def test_create_and_list_sessions(session_client):
    client, session_factory = session_client
    create_resp = client.post("/v1/sessions")
    assert create_resp.status_code == 201
    sid = create_resp.json()["session_id"]
    req_id = uuid.uuid4()

    try:
        # 1. Empty conversation does NOT appear in GET /v1/sessions
        list_resp = client.get("/v1/sessions")
        assert list_resp.status_code == 200
        data = list_resp.json()
        assert not any(item["session_id"] == sid for item in data["items"])

        # 2. Once a request occurs in this conversation, it appears
        with session_factory() as db:
            s_obj = Session(id=uuid.UUID(sid))
            db.add(s_obj)
            r_obj = RequestLog(
                id=req_id,
                session_id=uuid.UUID(sid),
                messages=[{"role": "user", "content": "Hello"}],
                response_content="Hi there!",
                model="gpt-4o-mini",
                provider="openai",
                tier="T1",
                status="ok",
            )
            db.add(r_obj)
            db.commit()

        list_resp2 = client.get("/v1/sessions")
        assert list_resp2.status_code == 200
        data2 = list_resp2.json()
        assert any(item["session_id"] == sid for item in data2["items"])
    finally:
        with session_factory() as db:
            db.query(RequestLog).filter(RequestLog.id == req_id).delete(synchronize_session=False)
            db.query(Session).filter(Session.id == uuid.UUID(sid)).delete(synchronize_session=False)
            db.commit()




def test_get_session_detail_not_found(session_client):
    client, _ = session_client
    random_id = uuid.uuid4()
    response = client.get(f"/v1/sessions/{random_id}")
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "session_id not found"


def test_get_session_detail_with_turns_and_feedback(session_client):
    client, session_factory = session_client
    session_id = uuid.uuid4()
    req1_id = uuid.uuid4()
    req2_id = uuid.uuid4()
    t1 = datetime.utcnow() - timedelta(minutes=5)
    t2 = datetime.utcnow() - timedelta(minutes=2)

    try:
        with session_factory() as db:
            sess = Session(id=session_id, started_at=t1, last_activity_at=t2, routing_state={"turn_count": 2})
            db.add(sess)

            r1 = RequestLog(
                id=req1_id,
                session_id=session_id,
                ts=t1,
                messages=[{"role": "user", "content": "Chào bạn"}],
                response_content="Xin chào! Tôi có thể giúp gì cho bạn?",
                model="gpt-4o-mini",
                provider="openai",
                tier="T1",
                difficulty_score=10,
                prompt_tokens=10,
                completion_tokens=20,
                cost_usd=0.000015,
                latency_total_ms=300,
                status="ok",
            )
            r2 = RequestLog(
                id=req2_id,
                session_id=session_id,
                ts=t2,
                messages=[{"role": "user", "content": "Viết hàm quicksort"}],
                response_content="Dưới đây là hàm quicksort...",
                model="claude-3-5-sonnet",
                provider="anthropic",
                tier="T3",
                difficulty_score=75,
                prompt_tokens=50,
                completion_tokens=120,
                cost_usd=0.002,
                latency_total_ms=850,
                status="ok",
            )
            db.add(r1)
            db.add(r2)

            fb1 = Feedback(request_id=req1_id, tags=["Nhanh"], note="Tốt", ts=t1)
            db.add(fb1)

            s_fb = SessionFeedback(session_id=session_id, tags=["Routing tốt, tiết kiệm chi phí"], note="Hài lòng", ts=t2)
            db.add(s_fb)

            db.commit()

        # Test GET /v1/sessions/{session_id}
        detail_resp = client.get(f"/v1/sessions/{session_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["session_id"] == str(session_id)
        assert detail["routing_state"] == {"turn_count": 2}
        assert detail["feedback"]["tags"] == ["Routing tốt, tiết kiệm chi phí"]
        assert detail["feedback"]["note"] == "Hài lòng"

        assert len(detail["turns"]) == 2
        # Turn 1
        assert detail["turns"][0]["request_id"] == str(req1_id)
        assert detail["turns"][0]["messages"] == [{"role": "user", "content": "Chào bạn"}]
        assert detail["turns"][0]["response_content"] == "Xin chào! Tôi có thể giúp gì cho bạn?"
        assert detail["turns"][0]["model"] == "gpt-4o-mini"
        assert detail["turns"][0]["tier"] == "T1"
        assert detail["turns"][0]["feedback"]["tags"] == ["Nhanh"]
        assert detail["turns"][0]["feedback"]["note"] == "Tốt"

        # Turn 2
        assert detail["turns"][1]["request_id"] == str(req2_id)
        assert detail["turns"][1]["messages"] == [{"role": "user", "content": "Viết hàm quicksort"}]
        assert detail["turns"][1]["response_content"] == "Dưới đây là hàm quicksort..."
        assert detail["turns"][1]["model"] == "claude-3-5-sonnet"
        assert detail["turns"][1]["tier"] == "T3"
        assert detail["turns"][1]["feedback"] is None
    finally:
        with session_factory() as db:
            db.query(Feedback).filter(Feedback.request_id.in_([req1_id, req2_id])).delete(synchronize_session=False)
            db.query(SessionFeedback).filter(SessionFeedback.session_id == session_id).delete(synchronize_session=False)
            db.query(RequestLog).filter(RequestLog.session_id == session_id).delete(synchronize_session=False)
            db.query(Session).filter(Session.id == session_id).delete(synchronize_session=False)
            db.commit()

