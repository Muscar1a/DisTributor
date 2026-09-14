"""Provider-independent N-1/N/N+1 tests for the public request contract."""

import os

import pytest
from fastapi.testclient import TestClient

from src.gateway.app.api.limits import (
    MAX_BODY_BYTES,
    MAX_INPUT_TOKENS,
    MAX_MESSAGES,
    MAX_OUTPUT_TOKENS,
)
from src.gateway.app.main import app


@pytest.fixture(scope="module")
def client():
    previous_dev_key = os.environ.pop("GATEWAY_DEV_KEY", None)
    previous_auth_required = os.environ.get("API_AUTH_REQUIRED")
    os.environ["USE_MOCK_PROVIDERS"] = "true"
    os.environ["API_AUTH_REQUIRED"] = "false"
    try:
        with TestClient(app, raise_server_exceptions=True) as test_client:
            yield test_client
    finally:
        if previous_dev_key is not None:
            os.environ["GATEWAY_DEV_KEY"] = previous_dev_key
        if previous_auth_required is None:
            os.environ.pop("API_AUTH_REQUIRED", None)
        else:
            os.environ["API_AUTH_REQUIRED"] = previous_auth_required


def _payload(*, messages=None, max_tokens=1):
    return {
        "model": "auto",
        "messages": messages or [{"role": "user", "content": "hi"}],
        "max_tokens": max_tokens,
    }


@pytest.mark.parametrize(
    ("requested", "forwarded", "clamped_header"),
    [
        (MAX_OUTPUT_TOKENS - 1, MAX_OUTPUT_TOKENS - 1, None),
        (MAX_OUTPUT_TOKENS, MAX_OUTPUT_TOKENS, None),
        (MAX_OUTPUT_TOKENS + 1, MAX_OUTPUT_TOKENS, "max_tokens"),
    ],
)
def test_output_token_boundary_is_forwarded_or_observably_clamped(
    client, monkeypatch, requested, forwarded, clamped_header
):
    adapter = client.app.state.orchestrator.fallback_executor.adapters["mock"]
    original_complete = adapter.complete
    captured = []

    async def capture_complete(model_id, messages, params):
        captured.append(params.max_tokens)
        return await original_complete(model_id, messages, params)

    monkeypatch.setattr(adapter, "complete", capture_complete)
    response = client.post(
        "/v1/chat/completions",
        json=_payload(max_tokens=requested),
    )

    assert response.status_code == 200
    assert captured == [forwarded]
    assert response.headers.get("X-SR-Clamped") == clamped_header


def test_streaming_clamp_uses_the_same_header_and_provider_limit(client, monkeypatch):
    adapter = client.app.state.orchestrator.fallback_executor.adapters["mock"]
    original_stream = adapter.stream
    captured = []

    async def capture_stream(model_id, messages, params):
        captured.append(params.max_tokens)
        async for chunk in original_stream(model_id, messages, params):
            yield chunk

    monkeypatch.setattr(adapter, "stream", capture_stream)
    response = client.post(
        "/v1/chat/completions",
        json={**_payload(max_tokens=MAX_OUTPUT_TOKENS + 1), "stream": True},
    )

    assert response.status_code == 200
    assert captured == [MAX_OUTPUT_TOKENS]
    assert response.headers["X-SR-Clamped"] == "max_tokens"


@pytest.mark.parametrize(
    ("count", "expected_status", "expected_code"),
    [
        (MAX_MESSAGES - 1, 200, None),
        (MAX_MESSAGES, 200, None),
        (MAX_MESSAGES + 1, 400, "too_many_messages"),
    ],
)
def test_message_count_boundary(client, count, expected_status, expected_code):
    messages = [{"role": "user", "content": "x"} for _ in range(count)]
    response = client.post("/v1/chat/completions", json=_payload(messages=messages))

    assert response.status_code == expected_status
    if expected_code:
        assert response.json()["error"]["code"] == expected_code


@pytest.mark.parametrize(
    ("token_count", "expected_status"),
    [
        (MAX_INPUT_TOKENS - 1, 200),
        (MAX_INPUT_TOKENS, 200),
        (MAX_INPUT_TOKENS + 1, 400),
    ],
)
def test_estimated_input_token_boundary(client, token_count, expected_status):
    # TokenEstimator's public contract is ceil(characters / 4).
    content = "x" * (token_count * 4)
    response = client.post(
        "/v1/chat/completions",
        json=_payload(messages=[{"role": "user", "content": content}]),
    )

    assert response.status_code == expected_status
    if expected_status == 400:
        error = response.json()["error"]
        assert error["code"] == "context_too_long"
        assert error["details"] == {
            "limit": MAX_INPUT_TOKENS,
            "estimated": MAX_INPUT_TOKENS + 1,
        }


def test_generated_openapi_publishes_all_boundaries():
    schema = app.openapi()
    operation = schema["paths"]["/v1/chat/completions"]["post"]
    request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[-1]]

    assert f"{MAX_BODY_BYTES:,}" in request_schema["description"]
    assert request_schema["properties"]["messages"]["maxItems"] == MAX_MESSAGES
    assert str(MAX_INPUT_TOKENS) in request_schema["properties"]["messages"]["description"]
    assert request_schema["properties"]["max_tokens"]["x-sr-clamp-maximum"] == MAX_OUTPUT_TOKENS
    clamped = operation["responses"]["200"]["headers"]["X-SR-Clamped"]
    assert clamped["schema"]["enum"] == ["max_tokens"]
    assert str(MAX_OUTPUT_TOKENS) in clamped["description"]
