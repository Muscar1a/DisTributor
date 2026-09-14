import base64
import hmac
import hashlib
import json
import os
import secrets
import time
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from src.gateway.app.db.models import User
from src.gateway.app.db.session import get_db

SESSION_COOKIE_NAME = "sr_session"
DEFAULT_TOKEN_EXPIRY = 7 * 24 * 3600  # 7 days


def _get_secret_key() -> bytes:
    key = os.getenv("SESSION_SECRET_KEY") or os.getenv("ADMIN_KEY") or "sr-insecure-secret-key-for-dev"
    return key.encode("utf-8")


def _is_secure_cookie() -> bool:
    return os.getenv("APP_ENV", "development").lower() in {"production", "prod"}


import threading

# Pre-computed bcrypt hash of a random dummy password to prevent timing attacks
DUMMY_BCRYPT_HASH = "$2b$12$7eqJtq98hPqEX7fNZaFWoOinYm3uK0nS6qLzD.3t2oKjB7A9gVv8m"


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    pw_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def verify_password_constant_time(password: str, hashed_password: str | None) -> bool:
    """Verify password in constant time to prevent timing attacks and user enumeration."""
    target_hash = hashed_password if hashed_password else DUMMY_BCRYPT_HASH
    try:
        match = bcrypt.checkpw(password.encode("utf-8"), target_hash.encode("utf-8"))
    except Exception:
        match = False
    return match and (hashed_password is not None)


class AuthRateLimiter:
    """In-memory thread-safe rate limiter for authentication endpoints to prevent brute-force attacks."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = {}

    def is_rate_limited(self, key: str) -> tuple[bool, int]:
        now = time.time()
        with self._lock:
            timestamps = self._attempts.get(key, [])
            valid = [t for t in timestamps if now - t < self.window_seconds]
            self._attempts[key] = valid
            if len(valid) >= self.max_attempts:
                retry_after = int(self.window_seconds - (now - valid[0]))
                return True, max(1, retry_after)
            return False, 0

    def record_attempt(self, key: str) -> None:
        now = time.time()
        with self._lock:
            timestamps = self._attempts.get(key, [])
            valid = [t for t in timestamps if now - t < self.window_seconds]
            valid.append(now)
            self._attempts[key] = valid

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)

    def reset_all(self) -> None:
        with self._lock:
            self._attempts.clear()


login_limiter = AuthRateLimiter(max_attempts=5, window_seconds=60)
register_limiter = AuthRateLimiter(max_attempts=5, window_seconds=60)


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64_decode(data_str: str) -> bytes:
    padding = 4 - (len(data_str) % 4)
    if padding != 4:
        data_str += "=" * padding
    return base64.urlsafe_b64decode(data_str.encode("utf-8"))


def create_session_token(user_id: int, expires_in_seconds: int = DEFAULT_TOKEN_EXPIRY) -> str:
    """Create an HMAC-SHA256 signed session token."""
    payload: dict[str, Any] = {
        "uid": user_id,
        "exp": int(time.time()) + expires_in_seconds,
        "nonce": secrets.token_hex(8),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64_encode(payload_bytes)

    secret = _get_secret_key()
    signature = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64_encode(signature)

    return f"{payload_b64}.{sig_b64}"


def verify_session_token(token: str) -> int | None:
    """Verify HMAC signature and expiration; return user_id if valid, else None."""
    if not token or "." not in token:
        return None

    parts = token.split(".", 1)
    if len(parts) != 2:
        return None

    payload_b64, sig_b64 = parts
    secret = _get_secret_key()
    expected_sig = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()

    try:
        provided_sig = _b64_decode(sig_b64)
    except Exception:
        return None

    if not hmac.compare_digest(expected_sig, provided_sig):
        return None

    try:
        payload_bytes = _b64_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or exp < time.time():
        return None

    user_id = payload.get("uid")
    if not isinstance(user_id, int):
        return None

    return user_id


def set_session_cookie(response: Response, token: str, max_age: int = DEFAULT_TOKEN_EXPIRY) -> None:
    """Attach the HttpOnly session cookie to the response."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=max_age,
        expires=max_age,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_secure_cookie(),
    )


def clear_session_cookie(response: Response) -> None:
    """Clear the session cookie from the client."""
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_is_secure_cookie(),
    )


def extract_token_from_request(request: Request) -> str | None:
    """Extract session token from HttpOnly cookie or Authorization Bearer header."""
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token.strip()

    # Fallback: check Authorization: Bearer <token> if cookie is not sent
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        # Ensure it is a signed session token format (contains '.')
        if "." in token:
            return token

    return None


def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Retrieve current user from session token if present and valid."""
    token = extract_token_from_request(request)
    if not token:
        return None

    user_id = verify_session_token(token)
    if not user_id:
        return None

    user = db.query(User).filter(User.id == user_id, User.active.is_(True)).first()
    return user


def get_current_user_required(
    user: User | None = Depends(get_current_user_optional),
) -> User:
    """Enforce authentication; raise 401 if user is not authenticated."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Authentication required. Please log in.",
                "type": "authentication_error",
                "code": "unauthorized",
            },
        )
    return user
