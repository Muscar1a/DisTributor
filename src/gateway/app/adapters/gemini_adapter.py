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

# Map logical model_id (models.yaml) -> model_id thật của Gemini API.
# Đã verify 08/08/2026: 2.5-flash-lite & 2.5-flash không còn khả dụng cho user mới (404),
# dùng bản 3.x hoạt động được. gemini-pro giữ 2.5-pro (tồn tại, free tier chỉ bị rate limit).
_GEMINI_MODEL_MAP = {
    "gemini-flash-lite": "gemini-3.1-flash-lite",
    "gemini-flash": "gemini-3.5-flash",
    "gemini-pro": "gemini-2.5-pro",
}

_FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
    "OTHER": "length",
}


class GeminiAdapter(BaseAdapter):
    """Adapter cho Google Gemini — map chuẩn OpenAI sang API native `generateContent`.

    - Đầu ra của gateway là subset text-only OpenAI -> adapter chuyển messages sang
      `contents`/`parts`, và response `candidates`/`usageMetadata` về `CompletionResult`.
    - Auth: API key truyền qua query param `?key=` (khác Groq dùng Bearer header).
    """

    provider = "google"
    models = ["gemini-flash-lite", "gemini-flash", "gemini-pro"]
    model_capabilities = dict.fromkeys(models, frozenset({"text", "stream"}))
    base_url = "https://generativelanguage.googleapis.com/v1beta"
    api_key_env = "GEMINI_API_KEY"
    model_map = _GEMINI_MODEL_MAP

    def _chat_url(self, model_id: str) -> str:
        return f"{self.base_url}/models/{model_id}:generateContent?key={self._api_key}"

    def _stream_url(self, model_id: str) -> str:
        return f"{self.base_url}/models/{model_id}:streamGenerateContent?alt=sse&key={self._api_key}"

    def _prepare_stream_payload(self, payload: dict) -> dict:
        return payload  # Gemini không dùng "stream" field trong body

    def _health_url(self) -> str:
        return f"{self.base_url}/models?key={self._api_key}"

    def _headers(self) -> dict[str, str]:
        # Gemini nhận key qua query param; không cần Authorization header.
        return {"Content-Type": "application/json"}

    def _build_request(
        self,
        model_id: str,
        messages: list[Message],
        params: CompletionParams,
    ) -> dict[str, Any]:
        system_text = "\n".join(m.content for m in messages if m.role == "system" and m.content is not None)
        contents: list[dict[str, Any]] = []
        for m in messages:
            if m.role == "system" or m.content is None:
                continue
            role = "model" if m.role == "assistant" else "user"
            if contents and contents[-1]["role"] == role:
                contents[-1]["parts"].append({"text": m.content})
            else:
                contents.append({
                    "role": role,
                    "parts": [{"text": m.content}],
                })
        request: dict[str, Any] = {"contents": contents}
        if system_text:
            request["systemInstruction"] = {"parts": [{"text": system_text}]}

        generation_config: dict[str, Any] = {}
        if params.temperature is not None:
            generation_config["temperature"] = params.temperature
        if params.max_tokens is not None:
            generation_config["maxOutputTokens"] = params.max_tokens
        if generation_config:
            request["generationConfig"] = generation_config
        return request

    def _parse_completion(
        self,
        data: dict[str, Any],
        model_id: str,
        messages: list[Message],
    ) -> CompletionResult:
        candidates = data.get("candidates") or []
        if not candidates:
            # Prompt bị chặn bởi safety filter -> content_filter
            return CompletionResult(
                content="",
                finish_reason="content_filter",
                usage=self._estimator.estimate_usage(messages, ""),
                provider_latency_ms=0,
                usage_estimated=True,
            )

        candidate = candidates[0]
        parts = ((candidate.get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts)
        raw_finish = candidate.get("finishReason", "STOP")
        finish_reason = _FINISH_REASON_MAP.get(raw_finish, "stop")

        meta = data.get("usageMetadata") or {}
        pt, ct = meta.get("promptTokenCount"), meta.get("candidatesTokenCount")
        if isinstance(pt, int) and isinstance(ct, int) and pt >= 0 and ct >= 0:
            usage, usage_estimated = Usage(prompt_tokens=pt, completion_tokens=ct), False
        else:
            usage, usage_estimated = self._estimator.estimate_usage(messages, text), True
        return CompletionResult(
            content=text,
            finish_reason=finish_reason,
            usage=usage,
            provider_latency_ms=0,
            usage_estimated=usage_estimated,
        )

    def _parse_stream_chunk(self, data: dict[str, Any]) -> StreamChunk:
        candidates = data.get("candidates") or []
        text = ""
        finish_reason = None
        if candidates:
            parts = ((candidates[0].get("content") or {}).get("parts")) or []
            text = "".join(p.get("text", "") for p in parts)
            raw_finish = candidates[0].get("finishReason")
            finish_reason = _FINISH_REASON_MAP.get(raw_finish) if raw_finish else None

        usage = None
        meta = data.get("usageMetadata") or {}
        pt, ct = meta.get("promptTokenCount"), meta.get("candidatesTokenCount")
        if isinstance(pt, int) and isinstance(ct, int):
            usage = Usage(prompt_tokens=pt, completion_tokens=ct)

        return StreamChunk(delta=text, finish_reason=finish_reason, usage=usage)
