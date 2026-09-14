"""AC-1/AC-2/AC-3: Bearer auth + per-request UUID injection.

Auth rules by path:
  /healthz /readyz /  → no auth (security: [] in v1_f1.yaml)
  /admin/*            → X-Admin-Key vs ADMIN_KEY env (fail closed when unset)
  /v1/*               → Bearer gateway key
                          AC-1: GATEWAY_DEV_KEY static key (dev/CI mode)
                          AC-2: DB SHA-256 hash lookup (production)
                          open mode: GATEWAY_DEV_KEY not set → passthrough (dev/CI)
  other (docs, /)     → passthrough
  OPTIONS             → always passthrough (CORS preflight)

Sau AuthMiddleware là RateLimitMiddleware (xem `11_client_rate_limiting.md`)
giới hạn RPM per-client.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from src.gateway.app.api.errors import add_request_id_headers, openai_error_response
from src.gateway.app.api.limits import MAX_BODY_BYTES
from src.gateway.app.core.api_keys import verify_db_api_key
from src.gateway.app.core.client_limiter import ClientRateLimiter

_NO_AUTH_PATHS = frozenset({"/healthz", "/readyz", "/"})
_ADMIN_PREFIX = "/admin"
_V1_PREFIX = "/v1"

# Trần body cứng — chặn memory-amplification DoS trước khi đọc/parse body (token guard chạy
# quá muộn, sau khi Pydantic đã dựng cả 50 message vào RAM). 1MB thừa sức cho request hợp lệ
# (input cap 8000 token ≈ 32KB). Env MAX_BODY_BYTES để chỉnh.
_rate_limiter = ClientRateLimiter()


def _error_401(request_id: str) -> JSONResponse:
    return openai_error_response(
        status_code=401,
        request_id=request_id,
        message="Thiếu hoặc sai gateway key.",
        error_type="authentication_error",
        code="invalid_api_key",
    )


def _error_429(request_id: str, retry_after: int) -> JSONResponse:
    return openai_error_response(
        status_code=429,
        request_id=request_id,
        message="Rate limit exceeded for this API key.",
        error_type="rate_limit_error",
        code="rate_limit_exceeded",
        headers={"Retry-After": str(retry_after)},
    )


def _admin_not_configured(request_id: str) -> JSONResponse:
    return openai_error_response(
        status_code=503,
        request_id=request_id,
        message="Admin API is unavailable because ADMIN_KEY is not configured.",
        error_type="internal_error",
        code="admin_auth_not_configured",
    )


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies by Content-Length before any parsing (DoS-1).

    ponytail: chỉ xét Content-Length header — bao phủ client JSON thường (luôn gửi header này).
    Chunked không Content-Length rơi về giới hạn của uvicorn; nâng lên đọc-đếm byte nếu cần.
    """

    def __init__(self, app, max_bytes: int | None = None):
        super().__init__(app)
        self._max_bytes = (
            max_bytes
            if max_bytes is not None
            else int(os.getenv("MAX_BODY_BYTES", str(MAX_BODY_BYTES)))
        )

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                size = int(cl)
            except ValueError:
                size = -1
            if size > self._max_bytes:
                request_id = getattr(request.state, "request_id", None) or str(uuid.uuid4())
                return openai_error_response(
                    status_code=413,
                    request_id=request_id,
                    message=f"Body {size} bytes vượt giới hạn {self._max_bytes} bytes.",
                    error_type="invalid_request_error",
                    code="request_too_large",
                    param="body",
                    details={"limit": self._max_bytes, "size": size},
                )
        return await call_next(request)


class AuthMiddleware(BaseHTTPMiddleware):
    """AC-1/AC-2/AC-3: request_id generation + Bearer/Admin key validation."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        error = self._check_auth(request)
        if error is not None:
            return error

        response = await call_next(request)
        return add_request_id_headers(response, request_id)

    def _check_auth(self, request: Request) -> JSONResponse | None:
        """Returns 401 JSONResponse if auth fails, None to proceed."""
        path = request.url.path
        request_id = request.state.request_id

        # Preflight + health: always allow
        if request.method == "OPTIONS" or path in _NO_AUTH_PATHS:
            return None

        if path.startswith(_ADMIN_PREFIX):
            admin_key = os.getenv("ADMIN_KEY", "")
            if not admin_key:
                return _admin_not_configured(request_id)
            if request.headers.get("X-Admin-Key") != admin_key:
                return _error_401(request_id)
            return None

        # Auth & user routes handle their own cookie/session auth
        if path.startswith("/v1/auth") or path.startswith("/v1/user"):
            return None

        if path.startswith(_V1_PREFIX):
            dev_key = os.getenv("GATEWAY_DEV_KEY", "")
            auth_required = os.getenv("API_AUTH_REQUIRED", "").lower() in {"1", "true", "yes"} or os.getenv(
                "APP_ENV", "development"
            ).lower() in {"production", "prod"}
            auth = request.headers.get("Authorization", "")

            # Local/CI open mode remains available explicitly outside production.
            if not auth and not dev_key and not auth_required:
                request.state.api_key_id = None
                request.state.rate_limit = 60
                return None

            if not auth.startswith("Bearer "):
                return _error_401(request_id)
            key = auth[7:].strip()
            if not key:
                return _error_401(request_id)

            # AC-1: static dev key
            if key == dev_key:
                request.state.api_key_id = f"dev:{hashlib.sha256(dev_key.encode()).hexdigest()}"
                request.state.rate_limit = 60
                return None

            # AC-2: DB hash lookup (AC-3 from #58)
            api_key = verify_db_api_key(key)
            if api_key is None:
                return _error_401(request_id)
            request.state.api_key_id = api_key.id
            request.state.rate_limit = api_key.rate_limit
            request.state.user_id = getattr(api_key, "user_id", None)
            if request.state.user_id and hasattr(api_key, "user") and api_key.user:
                request.state.user_preferences = dict(api_key.user.preferences or {})
            return None

        # Docs, OpenAPI spec, etc.: passthrough
        return None


def _resolve_client_id(request: Request) -> str | None:
    """Client identity cho rate limiter.

    Priority: api_key_id (DB key) → "dev:<hash>" (đã set bởi AuthMiddleware)
    → request.client.host (open mode). `None` nếu không xác định được.
    """
    api_key_id = getattr(request.state, "api_key_id", None)
    if api_key_id is not None:
        return api_key_id
    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window RPM gate per-client (xem `11_client_rate_limiting.md`).

    Chạy SAU AuthMiddleware: `request.state.api_key_id` và
    `request.state.rate_limit` phải đã được set. Skip health/docs/open mode
    passthrough.
    """

    def __init__(self, app, limiter: ClientRateLimiter | None = None):
        super().__init__(app)
        self._limiter = limiter

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        path = request.url.path
        if request.method == "OPTIONS" or path in _NO_AUTH_PATHS:
            return await call_next(request)

        limiter = self._limiter or _rate_limiter

        client_id = _resolve_client_id(request)
        limit = getattr(request.state, "rate_limit", 0) or 0

        allowed = await limiter.is_allowed(client_id, limit)
        if not allowed:
            request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
            return openai_error_response(
                status_code=429,
                request_id=request_id,
                message="Vượt giới hạn request. Thử lại sau 60 giây.",
                error_type="rate_limit_error",
                code="rate_limit_exceeded",
                details={"limit": limit, "window_seconds": 60},
                headers={"Retry-After": "60"},
            )

        return await call_next(request)
