import asyncio
import re
from collections.abc import AsyncIterator

from src.gateway.app.core.interfaces import (
    BadRequestToProvider,
    BaseAdapter,
    CompletionParams,
    CompletionResult,
    ContentFilteredError,
    Message,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimitError,
    StreamChunk,
    Usage,
)

_TRIGGER_RE = re.compile(r"#force_(429|500|timeout|filter|400)(?:@(\S+))?")
_TRIGGER_MAP = {
    "429": (RateLimitError, "Forced 429 Rate Limit Error"),
    "500": (ProviderUnavailable, "Forced 500 Provider Unavailable Error"),
    "timeout": (ProviderTimeout, "Forced provider timeout"),
    "filter": (ContentFilteredError, "Forced content filter refusal"),
    "400": (BadRequestToProvider, "Forced 400 Bad Request"),
}


class MockAdapter(BaseAdapter):
    provider = "mock"
    models = ["mock-cheap", "mock-mid", "mock-premium"]
    model_capabilities = {
        "mock-cheap": frozenset({"text", "stream"}),
        "mock-mid": frozenset({"text", "stream"}),
        "mock-premium": frozenset({"text", "stream"}),
    }

    async def _simulate_delay_and_check_errors(self, model_id: str, messages: list[Message]):
        await asyncio.sleep(0.2)  # 200ms delay

        for msg in messages:
            for m in _TRIGGER_RE.finditer(msg.content):
                trigger, target_model = m.group(1), m.group(2)
                if target_model and target_model != model_id:
                    continue
                exc_cls, exc_msg = _TRIGGER_MAP[trigger]
                raise exc_cls(exc_msg)

    async def complete(self, model_id: str, messages: list[Message], params: CompletionParams) -> CompletionResult:
        await self._simulate_delay_and_check_errors(model_id, messages)

        last_prompt = messages[-1].content if messages else ""
        content = f"Mock response for '{last_prompt[:30]}...' using {model_id}."

        return CompletionResult(
            content=content,
            finish_reason="stop",
            usage=Usage(prompt_tokens=len(last_prompt) // 4, completion_tokens=len(content) // 4),
            provider_latency_ms=200,
        )

    async def stream(
        self, model_id: str, messages: list[Message], params: CompletionParams
    ) -> AsyncIterator[StreamChunk]:
        await self._simulate_delay_and_check_errors(model_id, messages)

        chunks = ["This ", "is ", "a ", "mock ", "stream ", "response."]
        for chunk in chunks:
            yield StreamChunk(delta=chunk, finish_reason=None)
            await asyncio.sleep(0.05)

        yield StreamChunk(delta="", finish_reason="stop", usage=Usage(prompt_tokens=5, completion_tokens=len(chunks)))

    async def health(self) -> bool:
        return True
