import hashlib
import re
import secrets
import string
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.gateway.app.core.auth import (
    clear_session_cookie,
    create_session_token,
    get_current_user_required,
    hash_password,
    login_limiter,
    register_limiter,
    set_session_cookie,
    verify_password_constant_time,
)
from src.gateway.app.db.crud import (
    count_requests_by_api_key,
    create_api_key,
    create_user,
    get_api_key_by_name,
    get_user_by_email,
    list_user_api_keys,
    revoke_user_api_key,
    update_user_preferences,
)
from src.gateway.app.db.models import User
from src.gateway.app.db.session import get_db

router = APIRouter(prefix="/v1", tags=["auth"])
KEY_ALPHABET = string.ascii_letters + string.digits
MAX_API_KEY_RPM = 1_000

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
SCRIPT_REGEX = re.compile(r"<script[\s\S]*?</script>", re.IGNORECASE)
HTML_TAG_REGEX = re.compile(r"<[^>]+>")


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"


class UserRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=72)
    full_name: str | None = Field(default=None, max_length=100)
    preferences: dict[str, Any] | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if any(ord(c) < 32 or ord(c) == 127 for c in v):
            raise ValueError("Email contains invalid control characters.")
        if any(c in v for c in ("'", '"', ";", "--", "/*", "*/", "<", ">")):
            raise ValueError("Email contains disallowed characters.")
        if not EMAIL_REGEX.match(v):
            raise ValueError("Invalid email format.")
        return v

    @field_validator("full_name")
    @classmethod
    def sanitize_full_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        if not trimmed:
            return None
        if any(ord(c) < 32 or ord(c) == 127 for c in trimmed):
            raise ValueError("Full name contains invalid control characters.")
        if SCRIPT_REGEX.search(trimmed):
            trimmed = SCRIPT_REGEX.sub("", trimmed)
        if HTML_TAG_REGEX.search(trimmed):
            trimmed = HTML_TAG_REGEX.sub("", trimmed).strip()
        if not trimmed:
            raise ValueError("Full name cannot consist only of HTML tags.")
        return trimmed

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if any(ord(c) < 32 and c not in "\t\n\r" for c in v):
            raise ValueError("Password contains invalid control characters.")
        return v


class UserLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=1, max_length=72)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        v = v.strip().lower()
        if any(ord(c) < 32 or ord(c) == 127 for c in v):
            raise ValueError("Email contains invalid control characters.")
        return v


class UserPreferencesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_policy: Literal["balanced", "cost-first", "quality-first"] | None = None
    default_classifier_version: Literal["v1", "v1.5", "v2"] | None = None
    budget_monthly_usd: float | None = Field(default=None, ge=0, le=1_000_000)


class UserKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100)
    rate_limit_per_min: int = Field(default=60, ge=1, le=MAX_API_KEY_RPM)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("API key name cannot be blank.")
        if any(ord(c) < 32 or ord(c) == 127 for c in trimmed):
            raise ValueError("API key name contains invalid control characters.")
        if HTML_TAG_REGEX.search(trimmed):
            trimmed = HTML_TAG_REGEX.sub("", trimmed).strip()
        if not trimmed:
            raise ValueError("API key name cannot consist only of HTML tags.")
        return trimmed


def user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "preferences": user.preferences or {},
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def user_key_item(api_key, total_requests: int = 0) -> dict[str, Any]:
    return {
        "id": api_key.id,
        "name": api_key.name,
        "key_masked": api_key.key_masked,
        "rate_limit_per_min": api_key.rate_limit,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        "active": api_key.active,
        "total_requests": total_requests,
    }


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(
    payload: UserRegisterRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    client_ip = get_client_ip(request)
    is_limited, retry_after = register_limiter.is_rate_limited(client_ip)
    if is_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": f"Too many registration attempts. Please retry in {retry_after} seconds.",
                "type": "rate_limit_error",
                "code": "auth_rate_limited",
            },
            headers={"Retry-After": str(retry_after)},
        )

    existing = get_user_by_email(db, payload.email)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "An account with this email already exists.",
                "type": "invalid_request_error",
                "code": "duplicate_email",
            },
        )

    pw_hash = hash_password(payload.password)
    user = create_user(
        db,
        email=payload.email,
        password_hash=pw_hash,
        full_name=payload.full_name,
        preferences=payload.preferences,
    )

    register_limiter.record_attempt(client_ip)

    token = create_session_token(user.id)
    set_session_cookie(response, token)

    return {
        "status": "ok",
        "user": user_to_dict(user),
    }


@router.post("/auth/login", status_code=status.HTTP_200_OK)
def login(
    payload: UserLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    client_ip = get_client_ip(request)
    is_limited, retry_after = login_limiter.is_rate_limited(client_ip)
    if is_limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": f"Too many failed login attempts. Please retry in {retry_after} seconds.",
                "type": "rate_limit_error",
                "code": "auth_rate_limited",
            },
            headers={"Retry-After": str(retry_after)},
        )

    user = get_user_by_email(db, payload.email)
    pw_valid = verify_password_constant_time(
        payload.password,
        user.password_hash if user else None,
    )

    if user is None or not pw_valid:
        login_limiter.record_attempt(client_ip)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": "Invalid email or password.",
                "type": "authentication_error",
                "code": "invalid_credentials",
            },
        )

    if not user.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Account is disabled.",
                "type": "authentication_error",
                "code": "account_disabled",
            },
        )

    login_limiter.reset(client_ip)

    token = create_session_token(user.id)
    set_session_cookie(response, token)

    return {
        "status": "ok",
        "user": user_to_dict(user),
    }


@router.post("/auth/logout", status_code=status.HTTP_200_OK)
def logout(response: Response):
    clear_session_cookie(response)
    return {"status": "ok", "message": "Successfully logged out."}


@router.get("/auth/me", status_code=status.HTTP_200_OK)
def me(current_user: User = Depends(get_current_user_required)):
    return {
        "status": "ok",
        "user": user_to_dict(current_user),
    }


@router.put("/auth/preferences", status_code=status.HTTP_200_OK)
def update_preferences(
    payload: UserPreferencesUpdateRequest,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    updates = payload.model_dump(exclude_none=True)
    updated_user = update_user_preferences(db, current_user, updates)
    return {
        "status": "ok",
        "preferences": updated_user.preferences or {},
    }


# ─── User Personal API Keys ──────────────────────────────────────────────────


@router.get("/user/keys", status_code=status.HTTP_200_OK)
def get_user_keys(
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    keys = list_user_api_keys(db, current_user.id)
    request_counts = count_requests_by_api_key(db)
    return {
        "items": [
            user_key_item(k, request_counts.get(k.id, 0))
            for k in keys
        ]
    }


@router.post("/user/keys", status_code=status.HTTP_201_CREATED)
def create_personal_api_key(
    payload: UserKeyCreateRequest,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    if get_api_key_by_name(db, payload.name) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "An API key with this name already exists.",
                "type": "invalid_request_error",
                "code": "duplicate_api_key_name",
            },
        )

    raw_key = "sr-" + "".join(secrets.choice(KEY_ALPHABET) for _ in range(32))
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_masked = "sr-" + "*" * 4 + raw_key[-4:]

    try:
        api_key = create_api_key(
            db,
            name=payload.name,
            key_hash=key_hash,
            key_masked=key_masked,
            rate_limit=payload.rate_limit_per_min,
            user_id=current_user.id,
        )
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "An API key with this name already exists.",
                "type": "invalid_request_error",
                "code": "duplicate_api_key_name",
            },
        )

    return {
        **user_key_item(api_key),
        "key": raw_key,
    }


@router.delete("/user/keys/{key_id}", status_code=status.HTTP_200_OK)
def delete_personal_api_key(
    key_id: int,
    current_user: User = Depends(get_current_user_required),
    db: Session = Depends(get_db),
):
    revoked = revoke_user_api_key(db, current_user.id, key_id)
    if revoked is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "message": "API key not found.",
                "type": "invalid_request_error",
                "code": "key_not_found",
            },
        )
    return {"status": "ok", "revoked_key_id": key_id}
