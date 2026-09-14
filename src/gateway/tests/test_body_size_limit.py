"""DOS-1: BodySizeLimitMiddleware rejects oversized bodies before parsing.
See docs/review/pentest_scoring_and_routing.md."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.gateway.app.api.limits import MAX_BODY_BYTES
from src.gateway.app.api.middleware import BodySizeLimitMiddleware


def _client(max_bytes: int) -> TestClient:
    app = FastAPI()

    @app.post("/v1/echo")
    async def echo(payload: dict):
        return {"ok": True}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_bytes)
    return TestClient(app)


def test_body_over_limit_rejected():
    client = _client(100)
    r = client.post("/v1/echo", json={"x": "a" * 500})
    assert r.status_code == 413
    err = r.json()["error"]
    assert err["code"] == "request_too_large"
    assert err["details"]["limit"] == 100
    assert err["param"] == "body"
    assert r.headers["x-request-id"] == r.headers["x-sr-request-id"] == err["request_id"]


def test_body_under_limit_passes():
    client = _client(100_000)
    r = client.post("/v1/echo", json={"x": "hi"})
    assert r.status_code == 200


def test_get_without_body_passes():
    app = FastAPI()

    @app.get("/healthz")
    async def health():
        return {"ok": True}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=1)
    client = TestClient(app)
    assert client.get("/healthz").status_code == 200


@pytest.mark.parametrize(
    ("size", "expected_status"),
    [
        (MAX_BODY_BYTES - 1, 200),
        (MAX_BODY_BYTES, 200),
        (MAX_BODY_BYTES + 1, 413),
    ],
)
def test_exact_public_body_byte_boundary(size, expected_status):
    app = FastAPI()

    @app.post("/v1/raw")
    async def raw(request: Request):
        return {"size": len(await request.body())}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    response = TestClient(app).post(
        "/v1/raw",
        content=b"x" * size,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == expected_status
    if expected_status == 200:
        assert response.json()["size"] == size
    else:
        error = response.json()["error"]
        assert error["code"] == "request_too_large"
        assert error["details"] == {"limit": MAX_BODY_BYTES, "size": MAX_BODY_BYTES + 1}
