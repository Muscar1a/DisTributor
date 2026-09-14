# Regression tests for issue #91 — feedback endpoint persistence and production auth.

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.gateway.app.api import middleware
from src.gateway.app.db.models import Feedback, RequestLog
from src.gateway.app.db.session import SessionLocal, build_sync_database_url, get_db
from src.gateway.app.main import app


@pytest.fixture
def db_client(monkeypatch):
    with SessionLocal() as s:
        s.query(Feedback).delete()
        s.query(RequestLog).delete()
        s.commit()

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


def test_supabase_url_requires_tls_in_production():
    result = build_sync_database_url(
        "postgresql+asyncpg://user:secret@db.example.com:6543/postgres",
        require_ssl=True,
    )
    assert result.startswith("postgresql+psycopg2://")
    assert "sslmode=require" in result


def test_existing_ssl_query_is_preserved_and_required():
    result = build_sync_database_url(
        "postgresql://user:secret@db.example.com/postgres?application_name=smartroute",
        require_ssl=True,
    )
    assert "application_name=smartroute" in result
    assert "sslmode=require" in result

    stronger = build_sync_database_url(
        "postgresql://user:secret@db.example.com/postgres?sslmode=verify-full",
        require_ssl=True,
    )
    assert "sslmode=verify-full" in stronger


def test_feedback_is_persisted_for_request(db_client):
    client, session_factory = db_client
    request_id = uuid.uuid4()
    with session_factory() as db:
        db.add(RequestLog(id=request_id, status="ok"))
        db.commit()

    response = client.post(
        "/v1/feedback",
        json={"request_id": str(request_id), "tags": ["Chậm"], "note": "useful"},
    )

    assert response.status_code == 201
    assert response.json()["ok"] is True
    with session_factory() as db:
        stored = db.get(Feedback, request_id)
        assert stored.tags == ["Chậm"]
        assert stored.note == "useful"


def test_feedback_rejects_unknown_and_duplicate_request(db_client):
    client, session_factory = db_client
    missing = client.post(
        "/v1/feedback",
        json={"request_id": str(uuid.uuid4()), "tags": ["Chậm"]},
    )
    assert missing.status_code == 404

    request_id = uuid.uuid4()
    with session_factory() as db:
        db.add(RequestLog(id=request_id, status="ok"))
        db.commit()
    payload = {"request_id": str(request_id), "tags": ["Chậm"]}
    assert client.post("/v1/feedback", json=payload).status_code == 201
    assert client.post("/v1/feedback", json=payload).status_code == 409


def test_production_requires_bearer_auth(monkeypatch):
    monkeypatch.delenv("GATEWAY_DEV_KEY", raising=False)
    monkeypatch.delenv("API_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with TestClient(app) as client:
        response = client.get("/v1/models")
    assert response.status_code == 401


def test_database_api_key_is_accepted_and_attached(monkeypatch):
    monkeypatch.delenv("GATEWAY_DEV_KEY", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setattr(
        middleware,
        "verify_db_api_key",
        lambda raw_key: SimpleNamespace(id=42, rate_limit=17) if raw_key == "sr-valid" else None,
    )
    with TestClient(app) as client:
        response = client.get("/v1/models", headers={"Authorization": "Bearer sr-valid"})
    assert response.status_code == 200
