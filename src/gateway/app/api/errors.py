"""OpenAI-compatible error responses and request-ID headers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi.responses import JSONResponse

STANDARD_REQUEST_ID_HEADER = "X-Request-Id"
LEGACY_REQUEST_ID_HEADER = "X-SR-Request-Id"


def request_id_headers(request_id: str) -> dict[str, str]:
    """Return the standard OpenAI header plus SmartRoute's legacy alias."""
    return {
        STANDARD_REQUEST_ID_HEADER: request_id,
        LEGACY_REQUEST_ID_HEADER: request_id,
    }


def add_request_id_headers(response, request_id: str):
    for name, value in request_id_headers(request_id).items():
        response.headers[name] = value
    return response


def openai_error_response(
    *,
    status_code: int,
    request_id: str,
    message: str,
    error_type: str,
    code: str | None,
    param: str | None = None,
    details: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build the one error shape used by SDK-facing HTTP paths."""
    response_headers = request_id_headers(request_id)
    if headers:
        response_headers.update(headers)
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "param": param,
                "code": code,
                "request_id": request_id,
                "details": dict(details or {}),
            }
        },
    )
