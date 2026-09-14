"""Tests for ClientRateLimiter + RateLimitMiddleware."""

from __future__ import annotations

from collections import deque
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.app.api.middleware import RateLimitMiddleware, _resolve_client_id
from src.gateway.app.core.client_limiter import ClientRateLimiter

# ---------------------------------------------------------------------------
# ClientRateLimiter unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_allowed_returns_false_when_limit_exceeded():
    limiter = ClientRateLimiter()
    assert await limiter.is_allowed("client-1", 2) is True
    assert await limiter.is_allowed("client-1", 2) is True
    assert await limiter.is_allowed("client-1", 2) is False


@pytest.mark.asyncio
async def test_is_allowed_returns_true_when_within_limit():
    limiter = ClientRateLimiter()
    for _ in range(5):
        assert await limiter.is_allowed("client-1", 5) is True


@pytest.mark.asyncio
async def test_is_allowed_unlimited_when_limit_zero():
    limiter = ClientRateLimiter()
    for _ in range(100):
        assert await limiter.is_allowed("client-1", 0) is True


@pytest.mark.asyncio
async def test_is_allowed_skips_when_client_id_none():
    limiter = ClientRateLimiter()
    assert await limiter.is_allowed(None, 5) is True


@pytest.mark.asyncio
async def test_is_allowed_skips_when_client_id_empty():
    limiter = ClientRateLimiter()
    assert await limiter.is_allowed("", 5) is True


@pytest.mark.asyncio
async def test_is_allowed_allows_after_window_expires():
    with patch("src.gateway.app.core.client_limiter.time.monotonic") as mock_time:
        mock_time.return_value = 0.0
        limiter = ClientRateLimiter(window_s=60.0)
        assert await limiter.is_allowed("client-1", 1) is True
        assert await limiter.is_allowed("client-1", 1) is False

        mock_time.return_value = 61.0
        assert await limiter.is_allowed("client-1", 1) is True


@pytest.mark.asyncio
async def test_is_allowed_isolates_clients():
    limiter = ClientRateLimiter()
    assert await limiter.is_allowed("client-A", 1) is True
    assert await limiter.is_allowed("client-A", 1) is False
    # client-B không bị ảnh hưởng
    assert await limiter.is_allowed("client-B", 1) is True


@pytest.mark.asyncio
async def test_is_allowed_counts_across_calls_within_window():
    """Trong cùng window, tổng số call vượt limit thì fail."""
    with patch("src.gateway.app.core.client_limiter.time.monotonic") as mock_time:
        mock_time.return_value = 100.0
        limiter = ClientRateLimiter(window_s=60.0)
        # 3 call liên tiếp với limit=2: call thứ 3 fail
        assert await limiter.is_allowed("client-1", 2) is True
        assert await limiter.is_allowed("client-1", 2) is True
        assert await limiter.is_allowed("client-1", 2) is False


@pytest.mark.asyncio
async def test_is_allowed_accepts_int_client_id():
    """AC-2/AC-7: api_key_id là int từ DB."""
    limiter = ClientRateLimiter()
    assert await limiter.is_allowed(42, 1) is True
    assert await limiter.is_allowed(42, 1) is False
    assert await limiter.is_allowed(43, 1) is True


@pytest.mark.asyncio
async def test_idle_keys_are_evicted_after_window():
    """DOS-2: idle/rotating clients (IP mode) must not leak empty deques forever.
    Once their window passes, the periodic sweep drops their keys."""
    with patch("src.gateway.app.core.client_limiter.time.monotonic") as mock_time:
        mock_time.return_value = 100.0
        limiter = ClientRateLimiter(window_s=60.0)
        for i in range(500):
            assert await limiter.is_allowed(f"ip:{i}", 10) is True
        assert len(limiter._queues) == 500

        # A full window later, one new call triggers the sweep of all stale keys.
        mock_time.return_value = 200.0
        await limiter.is_allowed("ip:fresh", 10)
        assert len(limiter._queues) == 1  # 500 idle keys evicted, only the new one remains


# ---------------------------------------------------------------------------
# _resolve_client_id helper tests
# ---------------------------------------------------------------------------


def _make_request(state_attrs: dict, client_host: str | None = "127.0.0.1"):
    """Build a minimal request-like object for _resolve_client_id."""
    from types import SimpleNamespace

    state = SimpleNamespace(**state_attrs)
    client = SimpleNamespace(host=client_host) if client_host else None
    return SimpleNamespace(state=state, client=client)


def test_resolve_client_id_prefers_db_api_key_id():
    req = _make_request({"api_key_id": 42}, client_host="127.0.0.1")
    assert _resolve_client_id(req) == 42


def test_resolve_client_id_uses_dev_marker():
    req = _make_request({"api_key_id": "dev:abc123"}, client_host="127.0.0.1")
    assert _resolve_client_id(req) == "dev:abc123"


def test_resolve_client_id_falls_back_to_ip_when_no_api_key():
    req = _make_request({}, client_host="10.0.0.5")
    assert _resolve_client_id(req) == "ip:10.0.0.5"


def test_resolve_client_id_returns_none_when_no_identity():
    req = _make_request({}, client_host=None)
    assert _resolve_client_id(req) is None


def test_resolve_client_id_treats_none_api_key_as_open_mode():
    req = _make_request({"api_key_id": None}, client_host="10.0.0.5")
    assert _resolve_client_id(req) == "ip:10.0.0.5"


# ---------------------------------------------------------------------------
# RateLimitMiddleware integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_app():
    """Một FastAPI app mới + limiter riêng cho mỗi test."""

    limiter = ClientRateLimiter()
    app = FastAPI()

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    @app.get("/v1/ping")
    async def ping():
        return {"pong": True}

    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    return app, limiter


def test_rate_limit_middleware_skips_healthz(fresh_app):
    app, _ = fresh_app
    client = TestClient(app)
    # Health không bị throttle kể cả khi gọi nhiều lần
    for _ in range(100):
        assert client.get("/healthz").status_code == 200


def test_rate_limit_middleware_skips_options(fresh_app):
    app, _ = fresh_app
    client = TestClient(app)
    resp = client.options("/v1/ping")
    # OPTIONS preflight đi qua (không phải 429)
    assert resp.status_code != 429


def test_rate_limit_middleware_returns_429_envelope(fresh_app):
    """AC-1: trả 429 với body chuẩn + Retry-After: 60."""
    import time as _time

    from starlette.middleware.base import BaseHTTPMiddleware

    app, limiter = fresh_app

    # Thêm một middleware giả lập "auth đã chạy" set rate_limit=60
    class _FakeAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.request_id = "test-req-id"
            request.state.api_key_id = "client-test"
            request.state.rate_limit = 60
            return await call_next(request)

    app.add_middleware(_FakeAuth)
    # Pre-populate deque với timestamps now — không bị pop bởi cutoff.
    limiter._queues["client-test"] = deque([_time.monotonic()] * 60)

    client = TestClient(app)
    resp = client.get("/v1/ping")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"
    assert resp.headers["x-sr-request-id"] == "test-req-id"
    assert resp.headers["x-request-id"] == "test-req-id"

    err = resp.json()["error"]
    assert err["type"] == "rate_limit_error"
    assert err["code"] == "rate_limit_exceeded"
    assert err["request_id"] == "test-req-id"
    assert err["details"]["limit"] == 60
    assert err["details"]["window_seconds"] == 60


def test_rate_limit_middleware_allows_under_limit(fresh_app):
    from starlette.middleware.base import BaseHTTPMiddleware

    app, _ = fresh_app

    class _FakeAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.request_id = "rid"
            request.state.api_key_id = "client-ok"
            request.state.rate_limit = 60
            return await call_next(request)

    app.add_middleware(_FakeAuth)
    client = TestClient(app)
    resp = client.get("/v1/ping")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# End-to-end với AuthMiddleware + RateLimitMiddleware (qua main app)
# ---------------------------------------------------------------------------


def test_v1_blocked_after_60_requests_in_window(monkeypatch):
    """AC-1 end-to-end: vượt limit → 429 + Retry-After: 60."""
    import hashlib as _hashlib
    import time as _time

    key = "test-secret"
    key_hash = _hashlib.sha256(key.encode()).hexdigest()
    monkeypatch.setenv("GATEWAY_DEV_KEY", key)
    from src.gateway.app.api import middleware as mw
    from src.gateway.app.main import app as real_app

    mw._rate_limiter._queues[f"dev:{key_hash}"] = deque([_time.monotonic()] * 60)
    try:
        with TestClient(real_app) as client:
            resp = client.get("/v1/models", headers={"Authorization": f"Bearer {key}"})
            assert resp.status_code == 429
            assert resp.headers["Retry-After"] == "60"
            err = resp.json()["error"]
            assert err["code"] == "rate_limit_exceeded"
            assert err["details"]["limit"] == 60
    finally:
        mw._rate_limiter.reset()


def test_health_endpoints_never_throttled(monkeypatch):
    """AC-6: /healthz, /readyz, / không bị throttle."""
    import time as _time

    monkeypatch.setenv("GATEWAY_DEV_KEY", "test-secret")
    from src.gateway.app.api import middleware as mw
    from src.gateway.app.main import app as real_app

    mw._rate_limiter._queues["ip:127.0.0.1"] = deque([_time.monotonic()] * 9999)
    try:
        with TestClient(real_app) as client:
            assert client.get("/healthz").status_code == 200
            assert client.get("/readyz").status_code == 200
    finally:
        mw._rate_limiter.reset()


def test_open_mode_throttled_by_ip(monkeypatch):
    """AC-5: open mode (không auth) bị throttle theo IP."""
    import time as _time

    # Đảm bảo open mode (không có GATEWAY_DEV_KEY, không auth_required)
    monkeypatch.delenv("GATEWAY_DEV_KEY", raising=False)
    monkeypatch.delenv("API_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("APP_ENV", "development")

    from src.gateway.app.api import middleware as mw
    from src.gateway.app.main import app as real_app

    with TestClient(real_app) as client:
        resp = client.get("/v1/models")
        # Điền IP thực tế TestClient dùng vào deque rồi thử lại.
        limiter = mw._rate_limiter
        ip_keys = [k for k in limiter._queues if k.startswith("ip:")]
        assert ip_keys, f"No ip-key found, queues={list(limiter._queues)}"
        limiter._queues[ip_keys[0]] = deque([_time.monotonic()] * 60)
        resp = client.get("/v1/models")
        assert resp.status_code == 429
        assert resp.headers["Retry-After"] == "60"
    mw._rate_limiter.reset()
