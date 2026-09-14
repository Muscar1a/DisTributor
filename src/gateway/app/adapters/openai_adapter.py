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

_OPENAI_MODELS = [
    # T1
    "gpt-5-nano",
    "gpt-4.1-nano",
    "gpt-4o-mini",
    "gpt-5.4-nano",
    # T2
    "gpt-5-mini",
    "gpt-4.1-mini",
    "gpt-5.4-mini",
    "o3-mini",
    "o4-mini",
    # T3
    "gpt-5.1",
    "gpt-5",
    "gpt-5.2",
    "gpt-4.1",
    "gpt-4o",
    "gpt-5.4",
]

_OPENAI_MODEL_MAP = {m: m for m in _OPENAI_MODELS}

# Dòng model suy luận (gpt-5.x và o-series) từ chối tham số lấy mẫu.
# Đã verify 19/08/2026 trực tiếp với API:
#   temperature != 1  -> 400 "Unsupported value: 'temperature' does not support 0.7"
#   top_p             -> 400 "Unsupported parameter: 'top_p' is not supported"
# Gửi kèm là hỏng cả request, nên phải bỏ đi thay vì để provider từ chối.
_REASONING_PREFIXES = ("gpt-5", "o1", "o3", "o4")


def _is_reasoning_model(model_id: str) -> bool:
    return model_id.startswith(_REASONING_PREFIXES)


class OpenAIAdapter(BaseAdapter):
    """Adapter cho OpenAI — wire format giống Groq (cả hai dùng chuẩn OpenAI `/chat/completions`).

    - Auth: Bearer token qua header `Authorization`.
    - top_p và stop được pass-through (OpenAI hỗ trợ đầy đủ, khác Groq adapter hiện tại).
    """

    provider = "openai"
    models = _OPENAI_MODELS
    model_capabilities = {m: frozenset({"text", "stream"}) for m in _OPENAI_MODELS}
    base_url = "https://api.openai.com/v1"
    api_key_env = "OPENAI_API_KEY"
    model_map = _OPENAI_MODEL_MAP

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
        # `max_completion_tokens` dùng được cho CẢ hai dòng model (đã verify với
        # gpt-4o-mini lẫn gpt-5-nano), còn `max_tokens` thì dòng gpt-5 từ chối.
        if params.max_tokens is not None:
            if _is_reasoning_model(model_id) and params.max_tokens < 16:
                # Workaround cho OpenAI reasoning models (gpt-5.x, o-series):
                # Provider constraint: OpenAI yêu cầu `max_completion_tokens >= 16` đối với reasoning models
                # vì reasoning tokens cần không gian tối thiểu. Khi client gửi giá trị cực thấp (vd: max_tokens=1
                # ở boundary test), upstream OpenAI từ chối với HTTP 400 ("max_completion_tokens must be >= 16").
                # Ngưỡng sàn 16 token đảm bảo request hợp lệ không bị 400/502 provider_error.
                request["max_completion_tokens"] = 16
            else:
                request["max_completion_tokens"] = params.max_tokens

        if "seed" in params.extra and params.extra["seed"] is not None:
            request["seed"] = params.extra["seed"]
        elif params.temperature == 0.0 or params.temperature is None:
            # Đảm bảo tính tất định khi temperature=0 hoặc reasoning model (như benchmark paired MMLU-20)
            request["seed"] = 42

        if _is_reasoning_model(model_id):
            # Model suy luận không nhận tham số lấy mẫu (temperature, top_p, stop).
            if "reasoning_effort" in params.extra:
                request["reasoning_effort"] = params.extra["reasoning_effort"]
            return request

        if params.temperature is not None:
            request["temperature"] = params.temperature
        if top_p := params.extra.get("top_p"):
            request["top_p"] = top_p
        if stop := params.extra.get("stop"):
            request["stop"] = stop
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
        content = (choice.get("message") or {}).get("content") or ""
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
        usage = data.get("usage") or {}
        prompt = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if isinstance(prompt, int) and isinstance(completion_tokens, int) and prompt >= 0 and completion_tokens >= 0:
            return Usage(prompt_tokens=prompt, completion_tokens=completion_tokens), False
        return self._estimator.estimate_usage(messages, completion), True

    def _parse_stream_chunk(self, data: dict[str, Any]) -> StreamChunk:
        choices = data.get("choices") or []
        if not choices:
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
