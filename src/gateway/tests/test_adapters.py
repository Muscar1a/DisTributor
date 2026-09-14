from __future__ import annotations

import httpx
import pytest

from src.gateway.app.adapters.gemini_adapter import GeminiAdapter
from src.gateway.app.adapters.groq_adapter import GroqAdapter
from src.gateway.app.adapters.mock_adapter import MockAdapter
from src.gateway.app.adapters.openai_adapter import OpenAIAdapter
from src.gateway.app.core.interfaces import (
    BaseAdapter,
    CompletionParams,
    Message,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimitError,
)

# --- GeminiAdapter: mapping request/response + taxonomy ---

_GEMINI_OK = {
    "candidates": [
        {
            "content": {"parts": [{"text": "Hello from Gemini"}], "role": "model"},
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 4},
}


def _gemini_transport(status=200, payload=None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(":generateContent")
        assert "key=" in request.url.query.decode()
        return httpx.Response(status, json=payload or _GEMINI_OK)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_gemini_complete_maps_openai_to_native():
    client = httpx.AsyncClient(transport=_gemini_transport())
    adapter = GeminiAdapter(api_key="test-key", client=client)

    result = await adapter.complete(
        "gemini-flash-lite",
        [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="Hi"),
        ],
        CompletionParams(temperature=0.5, max_tokens=100),
    )

    assert result.content == "Hello from Gemini"
    assert result.finish_reason == "stop"
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 4
    assert result.usage_estimated is False
    assert result.provider_latency_ms >= 0
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_complete_estimates_usage_when_missing():
    payload = {"candidates": [{"content": {"parts": [{"text": "Hi"}], "role": "model"}, "finishReason": "STOP"}]}
    client = httpx.AsyncClient(transport=_gemini_transport(payload=payload))
    adapter = GeminiAdapter(api_key="test-key", client=client)

    result = await adapter.complete("gemini-flash-lite", [Message(role="user", content="Hi")], CompletionParams())

    assert result.usage_estimated is True
    assert result.usage.prompt_tokens > 0
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_complete_content_filter_when_no_candidates():
    payload = {"promptFeedback": {"blockReason": "SAFETY"}}
    client = httpx.AsyncClient(transport=_gemini_transport(payload=payload))
    adapter = GeminiAdapter(api_key="test-key", client=client)

    result = await adapter.complete("gemini-flash-lite", [Message(role="user", content="bad")], CompletionParams())

    assert result.finish_reason == "content_filter"
    assert result.content == ""
    await client.aclose()


@pytest.mark.asyncio
async def test_gemini_health_requires_api_key():
    adapter = GeminiAdapter(api_key="", client=httpx.AsyncClient(transport=_gemini_transport()))
    assert await adapter.health() is False
    await adapter._client.aclose()


@pytest.mark.asyncio
async def test_gemini_health_rejects_invalid_credentials():
    transport = httpx.MockTransport(lambda _request: httpx.Response(401, json={"error": "unauthorized"}))
    adapter = GeminiAdapter(api_key="invalid", client=httpx.AsyncClient(transport=transport))
    assert await adapter.health() is False
    await adapter._client.aclose()


# --- GroqAdapter: mapping request/response + taxonomy ---

_GROQ_OK = {
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hello from Groq"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


def _groq_transport(status=200, payload=None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(status, json=payload or _GROQ_OK)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_groq_complete_maps_openai_format():
    client = httpx.AsyncClient(transport=_groq_transport())
    adapter = GroqAdapter(api_key="test-key", client=client)

    result = await adapter.complete(
        "llama-3.3-70b",
        [Message(role="user", content="Hi")],
        CompletionParams(temperature=0.2),
    )

    assert result.content == "Hello from Groq"
    assert result.finish_reason == "stop"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5
    assert result.usage_estimated is False
    await client.aclose()


@pytest.mark.asyncio
async def test_groq_estimates_usage_when_missing():
    payload = {"choices": [{"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}]}
    client = httpx.AsyncClient(transport=_groq_transport(payload=payload))
    adapter = GroqAdapter(api_key="test-key", client=client)

    result = await adapter.complete("llama-3.3-70b", [Message(role="user", content="Hi")], CompletionParams())

    assert result.usage_estimated is True
    assert result.usage.prompt_tokens > 0
    await client.aclose()


# --- Error taxonomy (B.5): 429 / 5xx / timeout ---


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,expected",
    [
        (429, RateLimitError),
        (401, ProviderUnavailable),
        (403, ProviderUnavailable),
        (404, ProviderUnavailable),
        (500, ProviderUnavailable),
        (503, ProviderUnavailable),
    ],
)
async def test_adapter_maps_status_errors(status, expected):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GroqAdapter(api_key="test-key", client=client)

    with pytest.raises(expected):
        await adapter.complete("llama-3.3-70b", [Message(role="user", content="Hi")], CompletionParams())
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
async def test_retryable_errors_allow_fallback(status):
    """#111: auth/config errors (401/403) must be retryable so fallback continues."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GroqAdapter(api_key="test-key", client=client)

    with pytest.raises(ProviderError) as exc_info:
        await adapter.complete("llama-3.3-70b", [Message(role="user", content="Hi")], CompletionParams())
    assert exc_info.value.retryable is True
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 422])
async def test_content_errors_are_not_retryable(status):
    """400/422 = request content issue, should NOT fallback (ADR-010)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "bad"}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GroqAdapter(api_key="test-key", client=client)

    with pytest.raises(ProviderError) as exc_info:
        await adapter.complete("llama-3.3-70b", [Message(role="user", content="Hi")], CompletionParams())
    assert exc_info.value.retryable is False
    await client.aclose()


@pytest.mark.asyncio
async def test_adapter_maps_timeout_to_provider_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = GroqAdapter(api_key="test-key", client=client)

    with pytest.raises(ProviderTimeout):
        await adapter.complete("llama-3.3-70b", [Message(role="user", content="Hi")], CompletionParams())
    await client.aclose()


# --- Model mapping: logical -> provider model_id ---


def test_gemini_model_resolution():
    adapter = GeminiAdapter()
    assert adapter._resolve_model("gemini-flash-lite") == "gemini-3.1-flash-lite"
    assert adapter._resolve_model("gemini-flash") == "gemini-3.5-flash"
    assert adapter._resolve_model("gemini-pro") == "gemini-2.5-pro"


def test_groq_model_resolution():
    adapter = GroqAdapter()
    assert adapter._resolve_model("llama-3.3-70b") == "llama-3.3-70b-versatile"
    assert adapter._resolve_model("deepseek-r1-distill-llama-70b") == "deepseek-r1-distill-llama-70b"


# --- Request body mapping (build request) ---


def test_gemini_build_request_splits_system_message():
    adapter = GeminiAdapter()
    body = adapter._build_request(
        "gemini-2.5-flash",
        [
            Message(role="system", content="You are a cat."),
            Message(role="user", content="Meow?"),
            Message(role="assistant", content="Meow!"),
        ],
        CompletionParams(temperature=1.0, max_tokens=50),
    )
    assert body["systemInstruction"] == {"parts": [{"text": "You are a cat."}]}
    assert body["contents"][0]["role"] == "user"
    assert body["contents"][1]["role"] == "model"
    assert body["generationConfig"]["temperature"] == 1.0
    assert body["generationConfig"]["maxOutputTokens"] == 50


def test_gemini_build_request_preserves_empty_string_and_merges_turns():
    adapter = GeminiAdapter()
    body = adapter._build_request(
        "gemini-flash",
        [
            Message(role="user", content="hello"),
            Message(role="user", content=""),
            Message(role="user", content="world"),
        ],
        CompletionParams(),
    )
    # Consecutive user messages must be merged into 1 turn, preserving empty string
    assert len(body["contents"]) == 1
    assert body["contents"][0]["role"] == "user"
    assert [p["text"] for p in body["contents"][0]["parts"]] == ["hello", "", "world"]


def test_openai_build_request_reasoning_model_token_floor():
    adapter = OpenAIAdapter(api_key="test")
    # Reasoning model with max_tokens=1 gets floored to 16
    body = adapter._build_request(
        "gpt-5.4-nano",
        [Message(role="user", content="solve")],
        CompletionParams(max_tokens=1),
    )
    assert body["max_completion_tokens"] == 16
    assert "temperature" not in body  # temperature stripped for reasoning models
    assert body["seed"] == 42  # default seed 42 when temperature is 0 or None


def test_groq_build_request_keeps_openai_format():
    adapter = GroqAdapter()
    body = adapter._build_request(
        "llama-3.3-70b-versatile",
        [Message(role="system", content="sys"), Message(role="user", content="hi")],
        CompletionParams(temperature=0.0),
    )
    assert body["model"] == "llama-3.3-70b-versatile"
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    assert body["temperature"] == 0.0


# --- MockAdapter (AC-1, AC-2, AC-3) ---


def test_mock_inherits_base_adapter():
    # AC-1: kế thừa đúng contract
    assert issubclass(MockAdapter, BaseAdapter)
    assert MockAdapter.provider == "mock"
    assert set(MockAdapter.models) == {"mock-cheap", "mock-mid", "mock-premium"}


@pytest.mark.asyncio
async def test_mock_complete_success(mock_messages):
    # AC-2: trả CompletionResult hợp lệ, latency 200ms, không raise
    adapter = MockAdapter()
    result = await adapter.complete("mock-cheap", mock_messages, CompletionParams())

    assert result.content
    assert result.finish_reason == "stop"
    assert result.provider_latency_ms == 200
    assert result.usage.prompt_tokens >= 0
    assert result.usage.completion_tokens >= 0
    assert result.usage_estimated is False


@pytest.mark.asyncio
async def test_mock_complete_force_429():
    # AC-3: #force_429 → RateLimitError (retryable → kích hoạt fallback)
    adapter = MockAdapter()
    with pytest.raises(RateLimitError):
        await adapter.complete(
            "mock-cheap",
            [Message(role="user", content="hello #force_429")],
            CompletionParams(),
        )


@pytest.mark.asyncio
async def test_mock_complete_force_500():
    # AC-3: #force_500 → ProviderUnavailable (retryable → kích hoạt fallback)
    adapter = MockAdapter()
    with pytest.raises(ProviderUnavailable):
        await adapter.complete(
            "mock-cheap",
            [Message(role="user", content="hello #force_500")],
            CompletionParams(),
        )


@pytest.mark.asyncio
async def test_mock_health_always_true():
    assert await MockAdapter().health() is True


# --- OpenAIAdapter ---


_OPENAI_OK = {
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "Hello from OpenAI"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}


def _openai_transport(status=200, payload=None):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["Authorization"].startswith("Bearer ")
        return httpx.Response(status, json=payload or _OPENAI_OK)

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_openai_complete_maps_openai_format():
    client = httpx.AsyncClient(transport=_openai_transport())
    adapter = OpenAIAdapter(api_key="test-key", client=client)

    result = await adapter.complete(
        "gpt-4o-mini",
        [Message(role="user", content="Hi")],
        CompletionParams(temperature=0.5, max_tokens=100),
    )

    assert result.content == "Hello from OpenAI"
    assert result.finish_reason == "stop"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 5
    assert result.usage_estimated is False
    await client.aclose()


@pytest.mark.asyncio
async def test_openai_estimates_usage_when_missing():
    payload = {"choices": [{"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}]}
    client = httpx.AsyncClient(transport=_openai_transport(payload=payload))
    adapter = OpenAIAdapter(api_key="test-key", client=client)

    result = await adapter.complete("gpt-4o-mini", [Message(role="user", content="Hi")], CompletionParams())

    assert result.usage_estimated is True
    assert result.usage.prompt_tokens > 0
    await client.aclose()


def test_openai_model_resolution():
    adapter = OpenAIAdapter()
    assert adapter._resolve_model("gpt-4o-mini") == "gpt-4o-mini"
    assert adapter._resolve_model("gpt-4o") == "gpt-4o"


@pytest.mark.asyncio
async def test_openai_health_requires_api_key():
    adapter = OpenAIAdapter(api_key="", client=httpx.AsyncClient(transport=_openai_transport()))
    assert await adapter.health() is False
    await adapter._client.aclose()


# --- OpenAI: tham số theo dòng model (verify 19/08/2026 với API thật) ---


def test_openai_build_request_uses_max_completion_tokens():
    """`max_tokens` bị dòng gpt-5 từ chối; `max_completion_tokens` chạy cho cả hai dòng."""
    adapter = OpenAIAdapter(api_key="test-key")
    for model_id in ("gpt-4o-mini", "gpt-5-nano"):
        body = adapter._build_request(
            model_id,
            [Message(role="user", content="Hi")],
            CompletionParams(max_tokens=256),
        )
        assert body["max_completion_tokens"] == 256
        assert "max_tokens" not in body


def test_openai_build_request_drops_sampling_params_for_reasoning_models():
    """gpt-5.x / o-series trả 400 nếu nhận temperature khác 1 hoặc top_p."""
    adapter = OpenAIAdapter(api_key="test-key")
    params = CompletionParams(temperature=0.7, max_tokens=64, extra={"top_p": 0.9, "stop": "END"})

    reasoning = adapter._build_request("gpt-5-nano", [Message(role="user", content="Hi")], params)
    assert "temperature" not in reasoning
    assert "top_p" not in reasoning
    assert "stop" not in reasoning
    assert reasoning["max_completion_tokens"] == 64

    classic = adapter._build_request("gpt-4o-mini", [Message(role="user", content="Hi")], params)
    assert classic["temperature"] == 0.7
    assert classic["top_p"] == 0.9
    assert classic["stop"] == "END"
