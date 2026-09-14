from fastapi.testclient import TestClient

from src.gateway.app.main import app


def test_admin_routes_fail_closed_when_admin_key_is_unset(monkeypatch):
    monkeypatch.delenv("ADMIN_KEY", raising=False)

    with TestClient(app) as client:
        response = client.get("/admin/keys")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "admin_auth_not_configured"


def test_admin_routes_reject_missing_or_invalid_header(monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "expected-admin-key")

    with TestClient(app) as client:
        missing = client.get("/admin/keys")
        invalid = client.get("/admin/keys", headers={"X-Admin-Key": "wrong"})

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_admin_auth_errors_include_cors_headers(monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "expected-admin-key")

    with TestClient(app) as client:
        response = client.get(
            "/admin/keys",
            headers={"Origin": "http://localhost:5173"},
        )

    assert response.status_code == 401
    assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:5173"
