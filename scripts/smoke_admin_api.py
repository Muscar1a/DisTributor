"""Production smoke test for Vercel -> Render admin API connectivity.

The script is read-only: it checks CORS plus GET /admin/keys and
GET /admin/config. Secrets are read from the environment and never printed.
"""

from __future__ import annotations

import json
import os
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def origin_only(value: str, name: str, *, require_https: bool = True) -> str:
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"{name} must be an absolute origin")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"{name} must use HTTP(S)")
    if require_https and parsed.scheme != "https":
        raise ValueError(f"{name} must use HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError(f"{name} must not contain credentials, query parameters, or fragments")
    if parsed.path not in {"", "/"}:
        raise ValueError(f"{name} must be an origin only (no path or secret)")
    return f"{parsed.scheme}://{parsed.netloc}"


def request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None):
    req = Request(url, method=method, headers=headers or {})
    try:
        with urlopen(req, timeout=20) as response:  # noqa: S310 - validated HTTPS production origin
            return response.status, dict(response.headers.items()), response.read()
    except HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def header(headers: dict[str, str], name: str) -> str:
    target = name.lower()
    return next((value for key, value in headers.items() if key.lower() == target), "")


def wait_until_ready(gateway: str, attempts: int, delay_seconds: float) -> None:
    last_error = "gateway did not respond"
    for attempt in range(1, attempts + 1):
        try:
            status, _, _ = request(f"{gateway}/healthz")
            if status == 200:
                print(f"Gateway is healthy (attempt {attempt}/{attempts}).")
                return
            last_error = f"healthz returned HTTP {status}"
        except (URLError, TimeoutError, OSError) as exc:
            last_error = exc.__class__.__name__
        if attempt < attempts:
            time.sleep(delay_seconds)
    raise RuntimeError(last_error)


def assert_json_object(body: bytes, endpoint: str) -> dict:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{endpoint} did not return JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{endpoint} did not return a JSON object")
    return payload


def run() -> None:
    gateway = origin_only(os.environ.get("RENDER_GATEWAY_URL", ""), "RENDER_GATEWAY_URL")
    dashboard = origin_only(os.environ.get("VERCEL_PRODUCTION_ORIGIN", ""), "VERCEL_PRODUCTION_ORIGIN")
    admin_key = os.environ.get("ADMIN_KEY", "")
    if not admin_key:
        raise ValueError("ADMIN_KEY is required")
    if gateway == dashboard:
        raise ValueError("Render gateway and Vercel dashboard origins must be different")

    attempts = int(os.environ.get("SMOKE_MAX_ATTEMPTS", "24"))
    delay = float(os.environ.get("SMOKE_RETRY_DELAY_S", "10"))
    wait_until_ready(gateway, attempts, delay)

    preflight_status, preflight_headers, _ = request(
        f"{gateway}/admin/keys",
        method="OPTIONS",
        headers={
            "Origin": dashboard,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-admin-key,content-type",
        },
    )
    if preflight_status not in {200, 204}:
        raise RuntimeError(f"Admin CORS preflight returned HTTP {preflight_status}")
    if header(preflight_headers, "Access-Control-Allow-Origin") != dashboard:
        raise RuntimeError("Admin CORS preflight did not allow the Vercel production origin")
    allowed_headers = header(preflight_headers, "Access-Control-Allow-Headers").lower()
    if "x-admin-key" not in allowed_headers:
        raise RuntimeError("Admin CORS preflight did not allow X-Admin-Key")

    auth_headers = {"Origin": dashboard, "X-Admin-Key": admin_key}
    for path, required_field in (("/admin/keys", "items"), ("/admin/config", "default_policy")):
        status, response_headers, body = request(f"{gateway}{path}", headers=auth_headers)
        if status != 200:
            raise RuntimeError(f"GET {path} returned HTTP {status}")
        if header(response_headers, "Access-Control-Allow-Origin") != dashboard:
            raise RuntimeError(f"GET {path} omitted the expected CORS response header")
        payload = assert_json_object(body, path)
        if required_field not in payload:
            raise RuntimeError(f"GET {path} response is missing {required_field}")

    print("Production admin API smoke test passed: CORS, /admin/keys, and /admin/config.")


if __name__ == "__main__":
    try:
        run()
    except (ValueError, RuntimeError, URLError, TimeoutError, OSError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from None
