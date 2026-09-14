from __future__ import annotations

from typing import Any

from src.gateway.app.adapters.base import BaseAdapter
from src.gateway.app.core.interfaces import (
    CompletionParams,
    CompletionResult,
    Message,
    StreamChunk,
    Usage,
)

# Map logical model_id (models.yaml) -> model_id thật của Groq.
_GROQ_MODEL_MAP = {
    "llama-3.3-70b": "llama-3.3-70b-versatile",
    "groq-compound": "groq/compound",
}


class GroqAdapter(BaseAdapter):
    """Adapter cho Groq — API tương thích chuẩn OpenAI (`/chat/completions`).

    - Request/response gần như giữ nguyên chuẩn OpenAI, chỉ thay đổi model_id.
    - Auth: Bearer token qua header `Authorization`.
    """

    provider = "groq"
    models = ["llama-3.3-70b", "groq-compound"]
    model_capabilities = {
        "llama-3.3-70b": frozenset({"text", "stream"}),
        "groq-compound": frozenset({"text", "stream"}),
    }
    base_url = "https://api.groq.com/openai/v1"
    api_key_env = "GROQ_API_KEY"
    model_map = _GROQ_MODEL_MAP

    def _chat_url(self, model_id: str) -> str:
        return f"{self.base_url}/chat/completions"

    def _health_url(self) -> str:
        return f"{self.base_url}/models"

    def _build_request(
        self,
        model_id: str,
        messages: list[Message],
        params: CompletionParams,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": model_id,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
        }
        if params.temperature is not None:
            request["temperature"] = params.temperature
        if params.max_tokens is not None:
            request["max_tokens"] = params.max_tokens
        # params.extra: pass-through (adapter tự lọc field không hỗ trợ)
        for key, value in params.extra.items():
            if key not in request and key not in ("top_p", "stop"):
                request[key] = value
        return request

    def _parse_completion(
        self,
        data: dict[str, Any],
        model_id: str,
        messages: list[Message],
    ) -> CompletionResult:
        choices = data.get("choices") or []
        if not choices:
            return CompletionResult(
                content="",
                finish_reason="content_filter",
                usage=self._estimator.estimate_usage(messages, ""),
                provider_latency_ms=0,
                usage_estimated=True,
            )

        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        finish_reason = choice.get("finish_reason", "stop")

        usage, usage_estimated = self._parse_usage(data, messages, content)
        return CompletionResult(
            content=content,
            finish_reason=finish_reason,
            usage=usage,
            provider_latency_ms=0,
            usage_estimated=usage_estimated,
        )

    def _parse_usage(self, data: dict[str, Any], messages: list[Message], completion: str) -> tuple[Usage, bool]:
        """Lấy usage từ trường `usage` (chuẩn OpenAI); thiếu/sai -> ước lượng (AC-4.2)."""
        usage = data.get("usage") or {}
        prompt = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if isinstance(prompt, int) and isinstance(completion_tokens, int) and prompt >= 0 and completion_tokens >= 0:
            return Usage(prompt_tokens=prompt, completion_tokens=completion_tokens), False
        return self._estimator.estimate_usage(messages, completion), True

    def _parse_stream_chunk(self, data: dict[str, Any]) -> StreamChunk:
        choices = data.get("choices") or []
        if not choices:
            # Chunk cuối chỉ chứa usage (OpenAI stream_options.include_usage)
            usage = data.get("usage") or {}
            if usage:
                return StreamChunk(
                    delta="",
                    finish_reason="stop",
                    usage=Usage(
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                    ),
                )
            return StreamChunk(delta="")
        delta = (choices[0].get("delta") or {}).get("content") or ""
        finish_reason = choices[0].get("finish_reason")
        return StreamChunk(delta=delta, finish_reason=finish_reason)
