"""AC-1/AC-3/AC-4: Auth middleware + ErrorEnvelope regression."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.gateway.app.api import middleware
from src.gateway.app.main import app


@pytest.fixture
def keyed_client(monkeypatch):
    """TestClient with GATEWAY_DEV_KEY set — enforces Bearer auth."""
    monkeypatch.setenv("GATEWAY_DEV_KEY", "test-secret")
    with TestClient(app) as client:
        yield client


def test_v1_missing_auth_returns_401_envelope(keyed_client):
    """AC-1/AC-4: no Bearer header → 401 in ErrorEnvelope format."""
    response = keyed_client.get("/v1/models")
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["type"] == "authentication_error"
    assert error["code"] == "invalid_api_key"
    assert "request_id" in error
    assert response.headers["x-request-id"] == error["request_id"]
    assert response.headers["x-sr-request-id"] == error["request_id"]


def test_v1_wrong_key_returns_401(keyed_client):
    response = keyed_client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
    assert response.status_code == 401


def test_v1_correct_key_passes(keyed_client):
    """AC-1: valid static key → 200."""
    response = keyed_client.get("/v1/models", headers={"Authorization": "Bearer test-secret"})
    assert response.status_code == 200


def test_health_no_auth_required(keyed_client):
    """Health endpoints bypass auth even when key is configured."""
    assert keyed_client.get("/healthz").status_code == 200
    assert keyed_client.get("/readyz").status_code == 200


def test_request_id_in_header(keyed_client):
    """AC-3: standard and legacy request IDs match on successful responses."""
    response = keyed_client.get("/v1/models", headers={"Authorization": "Bearer test-secret"})
    assert response.headers["x-request-id"] == response.headers["x-sr-request-id"]


def test_open_mode_no_key_required(monkeypatch):
    """When GATEWAY_DEV_KEY is unset, /v1/* is open (CI/dev mode)."""
    monkeypatch.delenv("GATEWAY_DEV_KEY", raising=False)
    with TestClient(app) as client:
        response = client.get("/v1/models")
    assert response.status_code == 200


def test_database_key_rate_limit_returns_429_with_retry_after(monkeypatch):
    monkeypatch.delenv("GATEWAY_DEV_KEY", raising=False)
    monkeypatch.setenv("API_AUTH_REQUIRED", "true")
    monkeypatch.setattr(
        middleware,
        "verify_db_api_key",
        lambda raw_key: SimpleNamespace(id=42, rate_limit=1) if raw_key == "sr-valid" else None,
    )
    middleware._rate_limiter.reset()
    try:
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer sr-valid"}
            assert client.get("/v1/models", headers=headers).status_code == 200
            response = client.get("/v1/models", headers=headers)

        assert response.status_code == 429
        assert response.headers["Retry-After"] == "60"
        assert response.json()["error"]["type"] == "rate_limit_error"
        assert response.json()["error"]["code"] == "rate_limit_exceeded"
    finally:
        middleware._rate_limiter.reset()
