"""Runtime-safe application build metadata."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

DEFAULT_APP_VERSION = "0.1.0"
UNKNOWN_BUILD_VALUE = "unknown"
_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _first_nonempty_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return None


def _short_commit_sha(value: str | None) -> str:
    if value is None or _COMMIT_PATTERN.fullmatch(value) is None:
        return UNKNOWN_BUILD_VALUE
    return value[:7].lower()


def _build_timestamp(value: str | None) -> str:
    if value is None:
        return UNKNOWN_BUILD_VALUE

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return UNKNOWN_BUILD_VALUE
    if parsed.tzinfo is None:
        return UNKNOWN_BUILD_VALUE

    return parsed.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def get_build_metadata() -> dict[str, str]:
    """Return public, non-sensitive metadata for health and version reporting."""
    version = _first_nonempty_env("APP_VERSION") or DEFAULT_APP_VERSION
    commit_sha = _short_commit_sha(_first_nonempty_env("GIT_COMMIT_SHA", "RENDER_GIT_COMMIT"))
    timestamp = _build_timestamp(_first_nonempty_env("BUILD_TIMESTAMP"))
    return {
        "version": version,
        "commit_sha": commit_sha,
        "build_timestamp": timestamp,
    }
