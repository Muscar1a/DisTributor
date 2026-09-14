import uuid

import pytest
from fastapi.testclient import TestClient

from src.gateway.app.core.auth import SESSION_COOKIE_NAME
from src.gateway.app.db.models import APIKey, User
from src.gateway.app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_db():
    from src.gateway.app.core.auth import login_limiter, register_limiter
    login_limiter.reset_all()
    register_limiter.reset_all()
    yield
    from src.gateway.app.db.models import APIKey, Feedback, RequestLog, SessionFeedback, User
    from src.gateway.app.db.models import Session as SessionModel
    from src.gateway.app.db.session import SessionLocal
    with SessionLocal() as s:
        s.query(Feedback).delete()
        s.query(RequestLog).delete()
        s.query(SessionFeedback).delete()
        s.query(SessionModel).delete()
        s.query(APIKey).delete()
        s.query(User).delete()
        s.commit()
    login_limiter.reset_all()
    register_limiter.reset_all()


def test_register_login_and_logout(client):
    # 1. Register a new user with unique email
    email = f"testdev_{uuid.uuid4().hex[:8]}@example.com"
    reg_resp = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "password123", "full_name": "Test Developer"},
    )
    assert reg_resp.status_code == 201
    data = reg_resp.json()
    assert data["status"] == "ok"
    assert data["user"]["email"] == email
    assert data["user"]["full_name"] == "Test Developer"
    assert "sr_session" in reg_resp.cookies

    # 2. Duplicate registration should fail with 409
    dup_resp = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "password456"},
    )
    assert dup_resp.status_code == 409

    # 3. Access /v1/auth/me with the session cookie
    me_resp = client.get("/v1/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["email"] == email

    # 4. Logout
    logout_resp = client.post("/v1/auth/logout")
    assert logout_resp.status_code == 200

    # 5. Access /v1/auth/me after logout should fail with 401
    client.cookies.clear()
    unauth_resp = client.get("/v1/auth/me")
    assert unauth_resp.status_code == 401

    # 6. Login with invalid password
    bad_login = client.post(
        "/v1/auth/login",
        json={"email": email, "password": "wrongpassword"},
    )
    assert bad_login.status_code == 401

    # 7. Login with correct credentials
    good_login = client.post(
        "/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert good_login.status_code == 200
    assert "sr_session" in good_login.cookies


def test_update_preferences(client):
    email = f"prefsdev_{uuid.uuid4().hex[:8]}@example.com"
    reg_resp = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert reg_resp.status_code == 201

    # Initial preferences
    me_resp = client.get("/v1/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json()["user"]["preferences"]["default_policy"] == "balanced"

    # Update preferences to cost-first
    put_resp = client.put(
        "/v1/auth/preferences",
        json={"default_policy": "cost-first", "default_classifier_version": "v2"},
    )
    assert put_resp.status_code == 200
    assert put_resp.json()["preferences"]["default_policy"] == "cost-first"
    assert put_resp.json()["preferences"]["default_classifier_version"] == "v2"

    # Verify /me reflects the update
    me_resp2 = client.get("/v1/auth/me")
    assert me_resp2.json()["user"]["preferences"]["default_policy"] == "cost-first"
    assert me_resp2.json()["user"]["preferences"]["default_classifier_version"] == "v2"


def test_user_personal_api_keys(client):
    email = f"keydev_{uuid.uuid4().hex[:8]}@example.com"
    reg_resp = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert reg_resp.status_code == 201

    # List keys should be empty initially
    keys_resp = client.get("/v1/user/keys")
    assert keys_resp.status_code == 200
    assert keys_resp.json()["items"] == []

    # Create a personal key
    key_name = f"key_{uuid.uuid4().hex[:6]}"
    create_resp = client.post(
        "/v1/user/keys",
        json={"name": key_name, "rate_limit_per_min": 100},
    )
    assert create_resp.status_code == 201
    created_data = create_resp.json()
    assert created_data["name"] == key_name
    assert created_data["key"].startswith("sr-")
    key_id = created_data["id"]

    # List keys now has 1 key
    keys_resp2 = client.get("/v1/user/keys")
    assert len(keys_resp2.json()["items"]) == 1
    assert keys_resp2.json()["items"][0]["id"] == key_id

    # Revoke key
    del_resp = client.delete(f"/v1/user/keys/{key_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["revoked_key_id"] == key_id

    # Verify it is no longer active
    keys_resp3 = client.get("/v1/user/keys")
    assert keys_resp3.json()["items"][0]["active"] is False


def test_personalization_in_gateway_routing(client):
    # 1. Register a user and set default_policy to quality-first
    email = f"routerdev_{uuid.uuid4().hex[:8]}@example.com"
    reg_resp = client.post(
        "/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert reg_resp.status_code == 201

    put_resp = client.put(
        "/v1/auth/preferences",
        json={"default_policy": "quality-first"},
    )
    assert put_resp.status_code == 200

    # 2. Create personal API key
    key_name = f"rkey_{uuid.uuid4().hex[:6]}"
    key_resp = client.post(
        "/v1/user/keys",
        json={"name": key_name},
    )
    assert key_resp.status_code == 201
    api_key = key_resp.json()["key"]

    # 3. Call /v1/chat/completions WITHOUT specifying smartroute.policy
    client.cookies.clear()  # Ensure call is made as external SDK client with Bearer key
    chat_resp = None
    try:
        chat_resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "auto",
                "messages": [{"role": "user", "content": "hello world"}],
            },
        )
        assert chat_resp.status_code == 200
        chat_data = chat_resp.json()
        # Check that the personalized policy was automatically applied
        assert chat_data["smartroute"]["policy"] == "quality_first"
    finally:
        # Clean up request logs so other tests that wipe api_keys won't violate FK constraints
        from src.gateway.app.db.models import RequestLog
        from src.gateway.app.db.session import SessionLocal
        with SessionLocal() as s:
            if chat_resp and chat_resp.headers.get("X-Request-Id"):
                s.query(RequestLog).filter(RequestLog.id == uuid.UUID(chat_resp.headers["X-Request-Id"])).delete()
            else:
                s.query(RequestLog).delete()
            s.commit()


def test_auth_input_validation_and_anti_injection(client):
    # 1. SQL injection attempt in email
    sqli_resp = client.post(
        "/v1/auth/register",
        json={"email": "admin' OR '1'='1'--@example.com", "password": "securepassword123"},
    )
    assert sqli_resp.status_code == 422

    # 2. Control characters in email
    ctrl_resp = client.post(
        "/v1/auth/register",
        json={"email": "admin\x00@example.com", "password": "securepassword123"},
    )
    assert ctrl_resp.status_code == 422

    # 3. Password too short (< 8 chars)
    short_pw_resp = client.post(
        "/v1/auth/register",
        json={"email": f"valid_{uuid.uuid4().hex[:6]}@example.com", "password": "short"},
    )
    assert short_pw_resp.status_code == 422

    # 4. Password too long (> 72 chars, bcrypt limit & DoS prevention)
    long_pw_resp = client.post(
        "/v1/auth/register",
        json={"email": f"valid_{uuid.uuid4().hex[:6]}@example.com", "password": "A" * 73},
    )
    assert long_pw_resp.status_code == 422

    # 5. XSS HTML tags in full_name are sanitized
    email = f"xss_{uuid.uuid4().hex[:6]}@example.com"
    xss_resp = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "securepassword123",
            "full_name": "<script>alert('xss')</script>Alice",
        },
    )
    assert xss_resp.status_code == 201
    assert xss_resp.json()["user"]["full_name"] == "Alice"


def test_auth_brute_force_rate_limiting(client):
    email = f"target_{uuid.uuid4().hex[:6]}@example.com"
    # Register target user
    client.post(
        "/v1/auth/register",
        json={"email": email, "password": "correct_password123"},
    )
    client.cookies.clear()

    # Attempt 5 consecutive invalid logins
    for _ in range(5):
        fail_resp = client.post(
            "/v1/auth/login",
            json={"email": email, "password": "wrong_password"},
        )
        assert fail_resp.status_code == 401

    # The 6th attempt should be blocked by rate limiter with 429 Too Many Requests
    blocked_resp = client.post(
        "/v1/auth/login",
        json={"email": email, "password": "wrong_password"},
    )
    assert blocked_resp.status_code == 429
    assert "Retry-After" in blocked_resp.headers
    assert blocked_resp.json()["error"]["code"] == "auth_rate_limited"

