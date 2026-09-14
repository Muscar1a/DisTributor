"""FallbackExecutor — vòng lặp fallback tuần tự qua chain (FR-09, AC-3).

Luồng (khớp 05_interfaces.md §B.7 và 06_architecture.md runtime flow B):
    for ref in chain:
        if not circuit.allow_request(ref): continue          # model OPEN -> bỏ qua
        try:
            result = await adapter.complete(...)
        except ProviderError as e:
            circuit.record_error(ref, retryable=e.retryable)
            if not e.retryable: raise                        # content-filter / bad request -> dừng ngay (ADR-010)
            continue                                          # retryable -> thử model kế tiếp
        circuit.record_success(ref)
        return result
    raise AllProvidersFailedError(chain_attempted)            # hết chain -> 502 kèm chain_attempted
"""

import asyncio
from dataclasses import dataclass, field

from src.gateway.app.core.circuit import CircuitBreaker
from src.gateway.app.core.interfaces import (
    BaseAdapter,
    CompletionParams,
    CompletionResult,
    Message,
    ModelRef,
    ProviderError,
)


@dataclass
class FallbackResult:
    """Kết quả của một request sau khi đi qua chain fallback."""

    result: CompletionResult
    chain_attempted: list[str] = field(default_factory=list)  # model_id đã thử, đúng thứ tự
    fallback_count: int = 0


class AllProvidersFailedError(Exception):
    """Hết chain fallback -> API layer map thành 502 `provider_error` kèm `chain_attempted` (AC-3.3)."""

    def __init__(self, chain_attempted: list[str], last_error: ProviderError | None = None):
        self.chain_attempted = list(chain_attempted)
        self.last_error = last_error
        super().__init__(f"all providers failed: {chain_attempted}")


class FallbackExecutor:
    """Vòng lặp fallback tuần tự; **owner duy nhất** của retry/fallback (06_architecture.md §2)."""

    def __init__(
        self,
        adapters: dict[str, BaseAdapter],
        circuit: CircuitBreaker | None = None,
    ):
        self._adapters = adapters  # provider -> adapter instance
        self._circuit = circuit or CircuitBreaker()

    @property
    def circuit(self) -> CircuitBreaker:
        return self._circuit

    @property
    def adapters(self) -> dict[str, BaseAdapter]:
        """provider -> adapter. Chỉ đọc; classifier v2 cần để tự gọi LLM (doc 12 §7.4)."""
        return dict(self._adapters)

    async def execute(
        self,
        chain: list[ModelRef],
        messages: list[Message],
        params: CompletionParams,
    ) -> FallbackResult:
        """Thử lần lượt từng model trong chain; dừng ngay khi thành công hoặc lỗi không retryable."""
        chain_attempted: list[str] = []
        fallback_count = 0
        last_error: ProviderError | None = None

        for ref in chain:
            adapter = self._adapters.get(ref.provider)
            if adapter is None:
                continue
            if not self._circuit.allow_request(ref):
                continue  # model đang OPEN -> tự rời chain (AC-3.4)

            chain_attempted.append(ref.model_id)
            # Thử lại 1 lần nếu gặp lỗi transient/retryable (FR-09 fallback chain + retry)
            success = False
            for attempt in range(2):
                try:
                    result = await adapter.complete(ref.model_id, messages, params)
                    success = True
                    break
                except ProviderError as exc:
                    last_error = exc
                    if not exc.retryable:
                        self._circuit.record_error(ref, retryable=False)
                        # ContentFilteredError / BadRequestToProvider -> DỪNG NGAY, không fallback (ADR-010)
                        raise
                    if attempt == 0:
                        await asyncio.sleep(0.05)
                        continue

            if not success:
                # Ghi nhận lỗi vào circuit breaker đúng 1 lần duy nhất cho model này khi hết số lần thử
                self._circuit.record_error(ref, retryable=last_error.retryable if last_error else True)
                fallback_count += 1
                continue

            # Thành công
            self._circuit.record_success(ref)
            return FallbackResult(
                result=result,
                chain_attempted=chain_attempted,
                fallback_count=fallback_count,
            )

        raise AllProvidersFailedError(chain_attempted=chain_attempted, last_error=last_error)

    async def execute_stream(
        self,
        chain: list[ModelRef],
        messages: list[Message],
        params: CompletionParams,
        result_bag: dict,
    ):
        """Yields StreamChunk từ provider đầu tiên thành công trong chain.

        Fallback chỉ xảy ra nếu provider lỗi TRƯỚC chunk đầu tiên.
        result_bag được populate với: chain_attempted, model_ref, fallback_count.
        """
        chain_attempted: list[str] = []
        fallback_count = 0
        last_error: ProviderError | None = None

        for ref in chain:
            adapter = self._adapters.get(ref.provider)
            if adapter is None:
                continue
            if not self._circuit.allow_request(ref):
                continue

            chain_attempted.append(ref.model_id)
            gen = adapter.stream(ref.model_id, messages, params)

            try:
                first = await gen.__anext__()
            except StopAsyncIteration:
                self._circuit.record_success(ref)
                result_bag.update(chain_attempted=chain_attempted, model_ref=ref, fallback_count=fallback_count)
                return
            except ProviderError as exc:
                self._circuit.record_error(ref, retryable=exc.retryable)
                if not exc.retryable:
                    raise
                last_error = exc
                fallback_count += 1
                continue

            self._circuit.record_success(ref)
            result_bag.update(chain_attempted=chain_attempted, model_ref=ref, fallback_count=fallback_count)
            yield first
            async for chunk in gen:
                yield chunk
            return

        result_bag["chain_attempted"] = chain_attempted
        raise AllProvidersFailedError(chain_attempted=chain_attempted, last_error=last_error)
