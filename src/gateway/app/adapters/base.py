"""BaseAdapter — lớp nền dùng chung cho mọi provider adapter (contract B.4, B.5).

Chia sẻ pipeline HTTP chung cho provider thật:
    build request -> gọi HTTP -> parse response -> map lỗi taxonomy -> estimate usage (AC-4.2)

Subclass (GeminiAdapter, GroqAdapter...) chỉ cần cung cấp:
    - `base_url`, `api_key_env`, `model_map`  (cấu hình provider)
    - `_build_request()`  (map từ chuẩn OpenAI -> chuẩn riêng provider)
    - `_parse_completion()` (map response provider -> CompletionResult)
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from src.gateway.app.core.estimator import TokenEstimator
from src.gateway.app.core.interfaces import (
    BaseAdapter as CoreBaseAdapter,
)
from src.gateway.app.core.interfaces import (
    CompletionParams,
    CompletionResult,
    Message,
    ProviderError,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimitError,
    StreamChunk,
)


class BaseAdapter(CoreBaseAdapter):
    """Pipeline HTTP chung cho provider thật; subclass cung cấp mapping riêng."""

    base_url: str = ""
    api_key_env: str = ""
    model_map: dict[str, str] = {}  # logical model_id (models.yaml) -> provider model_id
    timeout_s: float = 60.0

    def __init__(
        self,
        api_key: str | None = None,
        timeout_s: float | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._api_key = api_key if api_key is not None else os.getenv(self.api_key_env, "")
        self._timeout_s = timeout_s or float(os.getenv("REQUEST_TIMEOUT_S", self.timeout_s))
        self._client = client or httpx.AsyncClient(timeout=self._timeout_s)
        self._estimator = TokenEstimator()

    # ------------------------------------------------------------------ #
    # Config helpers (subclass có thể override)
    # ------------------------------------------------------------------ #
    def _resolve_model(self, model_id: str) -> str:
        """Map logical model_id -> model_id thật của provider."""
        return self.model_map.get(model_id, model_id)

    def _chat_url(self, model_id: str) -> str:
        raise NotImplementedError

    def _stream_url(self, model_id: str) -> str:
        return self._chat_url(model_id)

    def _prepare_stream_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
        return payload

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    # ------------------------------------------------------------------ #
    # Mapping methods — subclass PHẢI implement
    # ------------------------------------------------------------------ #
    def _build_request(
        self,
        model_id: str,
        messages: list[Message],
        params: CompletionParams,
    ) -> dict[str, Any]:
        """Map request từ chuẩn OpenAI sang format riêng của provider."""
        raise NotImplementedError

    def _parse_completion(
        self,
        data: dict[str, Any],
        model_id: str,
        messages: list[Message],
    ) -> CompletionResult:
        """Map response provider -> CompletionResult (kèm usage, finish_reason)."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Error taxonomy (B.5) — dùng chung cho mọi provider
    # ------------------------------------------------------------------ #
    def _map_status_error(self, exc: httpx.HTTPStatusError) -> ProviderError:
        status = exc.response.status_code
        if status == 429:
            return RateLimitError(f"{self.provider}: rate limited (429): {exc.response.text[:200]}")
        if status in (401, 403):
            # auth/config lỗi của provider → provider khác có thể xử lý (#111)
            return ProviderUnavailable(f"{self.provider}: auth/config error ({status}): {exc.response.text[:200]}")
        if status == 404:
            return ProviderUnavailable(f"{self.provider}: model not found (404): {exc.response.text[:200]}")
        if status >= 500:
            return ProviderUnavailable(f"{self.provider}: server error {status}: {exc.response.text[:200]}")
        # 4xx còn lại (400/422) = request content lỗi, không retry (ADR-010)
        return ProviderError(f"{self.provider}: HTTP {status}: {exc.response.text[:200]}")

    # ------------------------------------------------------------------ #
    # Core methods (contract B.4)
    # ------------------------------------------------------------------ #
    async def complete(
        self,
        model_id: str,
        messages: list[Message],
        params: CompletionParams,
    ) -> CompletionResult:
        resolved = self._resolve_model(model_id)
        payload = self._build_request(resolved, messages, params)
        start = time.perf_counter()
        try:
            resp = await self._client.post(self._chat_url(resolved), json=payload, headers=self._headers())
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"{self.provider}: timeout sau {self._timeout_s}s") from exc
        except httpx.HTTPStatusError as exc:
            raise self._map_status_error(exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.provider}: network error: {exc}") from exc

        latency_ms = int((time.perf_counter() - start) * 1000)
        result = self._parse_completion(resp.json(), resolved, messages)
        result.provider_latency_ms = latency_ms
        return result

    async def stream(
        self,
        model_id: str,
        messages: list[Message],
        params: CompletionParams,
    ) -> AsyncIterator[StreamChunk]:
        resolved = self._resolve_model(model_id)
        payload = self._prepare_stream_payload(self._build_request(resolved, messages, params))
        try:
            async with self._client.stream(
                "POST", self._stream_url(resolved), json=payload, headers=self._headers()
            ) as resp:
                if resp.status_code >= 400:
                    await resp.aread()
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data or data == "[DONE]":
                        continue
                    yield self._parse_stream_chunk(json.loads(data))
        except httpx.TimeoutException as exc:
            raise ProviderTimeout(f"{self.provider}: timeout sau {self._timeout_s}s") from exc
        except httpx.HTTPStatusError as exc:
            raise self._map_status_error(exc) from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"{self.provider}: network error: {exc}") from exc

    def _parse_stream_chunk(self, data: dict[str, Any]) -> StreamChunk:
        raise NotImplementedError

    async def health(self) -> bool:
        """Provider sẵn sàng khi có API key; gọi GET nhẹ để xác nhận reachable."""
        if not self._api_key:
            return False
        try:
            resp = await self._client.get(self._health_url(), headers=self._headers())
            # Authentication, quota and provider failures all mean this
            # configured adapter cannot currently serve gateway traffic.
            return resp.status_code < 400
        except httpx.HTTPError:
            return False

    def _health_url(self) -> str:
        raise NotImplementedError

