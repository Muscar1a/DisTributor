import httpx
import pytest

from src.gateway.app.adapters.mock_adapter import MockAdapter
from src.gateway.app.adapters.openai_adapter import OpenAIAdapter
from src.gateway.app.core.circuit import CircuitBreaker
from src.gateway.app.core.fallback import FallbackExecutor
from src.gateway.app.core.interfaces import (
    CompletionParams,
    Message,
    ModelRef,
    ProviderUnavailable,
    RateLimitError,
)


@pytest.mark.asyncio
async def test_mock_adapter_force_errors():
    adapter = MockAdapter()
    params = CompletionParams()

    # Test normal response
    res = await adapter.complete("mock-cheap", [Message(role="user", content="hello")], params)
    assert "mock-cheap" in res.content

    # Test forced 429
    with pytest.raises(RateLimitError):
        await adapter.complete("mock-cheap", [Message(role="user", content="please #force_429")], params)

    # Test forced 500
    with pytest.raises(ProviderUnavailable):
        await adapter.complete("mock-cheap", [Message(role="user", content="please #force_500")], params)


@pytest.mark.asyncio
async def test_multi_provider_fallback_openai():
    """Gemini (primary) fails → Groq (fallback-1) fails → OpenAI (fallback-2) succeeds."""
    openai_ok = {
        "choices": [{"message": {"role": "assistant", "content": "ok from openai"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }

    class _FailAdapter:
        provider = "fail"
        model_capabilities = {}

        async def complete(self, model_id, messages, params):
            raise ProviderUnavailable("stub 503")

        async def health(self):
            return False

    openai_client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=openai_ok)))
    openai_adapter = OpenAIAdapter(api_key="test-key", client=openai_client)

    chain = [
        ModelRef(model_id="gemini-flash", provider="google"),
        ModelRef(model_id="llama-3.3-70b", provider="groq"),
        ModelRef(model_id="gpt-4o-mini", provider="openai"),
    ]
    executor = FallbackExecutor(
        adapters={"google": _FailAdapter(), "groq": _FailAdapter(), "openai": openai_adapter},
        circuit=CircuitBreaker(),
    )

    result = await executor.execute(chain, [Message(role="user", content="hi")], CompletionParams())
    assert result.result.content == "ok from openai"
    assert result.fallback_count == 2
    assert result.chain_attempted == ["gemini-flash", "llama-3.3-70b", "gpt-4o-mini"]
    await openai_client.aclose()


@pytest.mark.asyncio
async def test_circuit_breaker_no_double_count_on_retry():
    calls = 0

    class _FlakyAdapter:
        provider = "flaky"
        model_capabilities = {}

        async def complete(self, model_id, messages, params):
            nonlocal calls
            calls += 1
            raise ProviderUnavailable("transient 503")

    circuit = CircuitBreaker(failure_threshold=5)
    executor = FallbackExecutor(
        adapters={"flaky": _FlakyAdapter()},
        circuit=circuit,
    )
    ref = ModelRef(model_id="flaky-model", provider="flaky")
    from src.gateway.app.core.fallback import AllProvidersFailedError

    with pytest.raises(AllProvidersFailedError):
        await executor.execute([ref], [Message(role="user", content="hi")], CompletionParams())

    assert calls == 2  # 1 initial attempt + 1 retry
    # Circuit breaker must only record 1 failure for this model, not 2
    assert circuit._failures[("flaky-model", "flaky")] == 1

