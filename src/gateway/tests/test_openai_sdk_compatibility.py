"""Regression coverage for issue #237 using the official OpenAI SDK."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

openai = pytest.importorskip("openai")

from src.gateway.app.main import app  # noqa: E402


def _assert_request_id(value: str | None) -> None:
    assert value is not None
    uuid.UUID(value)


@pytest.fixture
def sdk_clients(monkeypatch):
    monkeypatch.setenv("GATEWAY_DEV_KEY", "test-secret")
    with TestClient(app) as http_client:
        with openai.OpenAI(
            api_key="test-secret",
            base_url="http://testserver/v1",
            http_client=http_client,
        ) as sdk:
            yield sdk, http_client


def test_sdk_raw_success_exposes_standard_request_id(sdk_clients):
    sdk, _ = sdk_clients
    raw = sdk.models.with_raw_response.list()
    _assert_request_id(raw.request_id)
    assert raw.request_id == raw.headers["x-sr-request-id"]


def test_sdk_400_image_content_has_request_id_and_stable_param(sdk_clients):
    sdk, _ = sdk_clients
    with pytest.raises(openai.BadRequestError) as caught:
        sdk.chat.completions.create(
            model="auto",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Describe this image"},
                        {"type": "image_url", "image_url": {"url": "https://example.com/image.png"}},
                    ],
                }
            ],
        )

    error = caught.value
    _assert_request_id(error.request_id)
    assert error.code == "unsupported_parameter"
    assert error.param == "messages.content"


def test_sdk_401_exception_exposes_request_id(sdk_clients):
    _, http_client = sdk_clients
    sdk = openai.OpenAI(
        api_key="wrong-key",
        base_url="http://testserver/v1",
        http_client=http_client,
    )
    with pytest.raises(openai.AuthenticationError) as caught:
        sdk.models.list()
    _assert_request_id(caught.value.request_id)


def test_sdk_404_unsupported_endpoint_is_stable(sdk_clients):
    sdk, _ = sdk_clients
    with pytest.raises(openai.NotFoundError) as caught:
        sdk.responses.create(model="auto", input="hello")

    error = caught.value
    _assert_request_id(error.request_id)
    assert error.code == "unsupported_endpoint"
    assert error.body["details"] == {
        "endpoint": "/v1/responses",
        "capability": "text_chat_completions_only",
    }


@pytest.mark.parametrize(
    "path",
    [
        "/v1/responses",
        "/v1/embeddings",
        "/v1/images/generations",
        "/v1/audio/transcriptions",
    ],
)
def test_unsupported_routes_never_return_fastapi_detail(sdk_clients, path):
    _, http_client = sdk_clients
    response = http_client.post(
        path,
        headers={"Authorization": "Bearer test-secret"},
        json={},
    )
    assert response.status_code == 404
    assert "detail" not in response.json()
    assert response.json()["error"]["code"] == "unsupported_endpoint"
    assert response.json()["error"]["details"]["endpoint"] == path
    assert response.headers["x-request-id"] == response.headers["x-sr-request-id"]
