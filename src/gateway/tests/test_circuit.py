from __future__ import annotations

import pytest

from src.gateway.app.core.circuit import CLOSED, HALF_OPEN, OPEN, CircuitBreaker
from src.gateway.app.core.fallback import AllProvidersFailedError, FallbackExecutor
from src.gateway.app.core.interfaces import (
    BadRequestToProvider,
    CompletionParams,
    CompletionResult,
    ContentFilteredError,
    Message,
    ModelRef,
    ProviderUnavailable,
    RateLimitError,
    Usage,
)


def _ref(model_id: str, provider: str = "mock") -> ModelRef:
    return ModelRef(model_id=model_id, provider=provider)


# --- AC-3.4: CLOSED -> OPEN -> HALF_OPEN state machine ---


def test_circuit_starts_closed():
    cb = CircuitBreaker()
    assert cb.state_of(_ref("mock-cheap")) == CLOSED
    assert not cb.open_set()
    assert cb.allow_request(_ref("mock-cheap")) is True


def test_circuit_opens_after_threshold_consecutive_errors():
    cb = CircuitBreaker(failure_threshold=5)
    ref = _ref("mock-cheap")
    for _ in range(4):
        cb.record_error(ref, retryable=True)
        assert cb.state_of(ref) == CLOSED
    cb.record_error(ref, retryable=True)
    assert cb.state_of(ref) == OPEN
    assert (ref.model_id, ref.provider) in cb.open_set()
    assert cb.allow_request(ref) is False  # OPEN (chưa hết 300s) -> chặn


def test_circuit_does_not_count_non_retryable_errors():
    cb = CircuitBreaker(failure_threshold=2)
    ref = _ref("mock-cheap")
    # content-filter / bad-request (retryable=False) không được đếm (ADR-010)
    cb.record_error(ref, retryable=False)
    cb.record_error(ref, retryable=False)
    assert cb.state_of(ref) == CLOSED


def test_circuit_transitions_open_to_half_open_after_recovery_window():
    fake_now = {"t": 1000.0}
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout_s=300, now=lambda: fake_now["t"])

    ref = _ref("mock-premium")
    cb.record_error(ref, retryable=True)
    cb.record_error(ref, retryable=True)
    assert cb.state_of(ref) == OPEN
    assert cb.allow_request(ref) is False

    # Sau 300s -> HALF_OPEN, cho thử đúng 1 request
    fake_now["t"] += 301
    assert cb.allow_request(ref) is True
    assert cb.state_of(ref) == HALF_OPEN

    # Request thứ 2 trong HALF_OPEN bị chặn (chỉ 1 probe)
    assert cb.allow_request(ref) is False


def test_circuit_half_open_success_closes_and_resets():
    fake_now = {"t": 0.0}
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout_s=300, now=lambda: fake_now["t"])
    ref = _ref("mock-mid")

    cb.record_error(ref, retryable=True)
    cb.record_error(ref, retryable=True)
    fake_now["t"] += 301
    assert cb.allow_request(ref) is True  # HALF_OPEN probe

    cb.record_success(ref)
    assert cb.state_of(ref) == CLOSED
    assert cb.allow_request(ref) is True


def test_circuit_half_open_failure_reopens():
    fake_now = {"t": 0.0}
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout_s=300, now=lambda: fake_now["t"])
    ref = _ref("mock-mid")

    cb.record_error(ref, retryable=True)
    cb.record_error(ref, retryable=True)
    fake_now["t"] += 301
    assert cb.allow_request(ref) is True  # HALF_OPEN probe

    cb.record_error(ref, retryable=True)
    assert cb.state_of(ref) == OPEN
    # reset bộ đếm sau khi reopen
    assert cb.snapshot()[(ref.model_id, ref.provider)]["consecutive_failures"] == 0


def test_circuit_open_set_only_contains_open():
    cb = CircuitBreaker(failure_threshold=1)
    ok = _ref("mock-cheap")
    bad = _ref("mock-mid")
    cb.record_error(bad, retryable=True)
    cb.record_success(ok)
    assert (bad.model_id, bad.provider) in cb.open_set()
    assert (ok.model_id, ok.provider) not in cb.open_set()


# --- AC-3.1: fallback sang model kế tiếp khi primary lỗi retryable ---


class _FakeAdapter:
    """Adapter fake: mô phỏng lỗi theo (model_id, trigger)."""

    provider = "mock"

    def __init__(self, model_errors: dict[str, type[Exception] | None]):
        self._model_errors = model_errors

    async def complete(self, model_id, messages, params) -> CompletionResult:
        err = self._model_errors.get(model_id)
        if err is not None:
            raise err(f"forced error for {model_id}")
        return CompletionResult(
            content=f"ok-{model_id}",
            finish_reason="stop",
            usage=Usage(prompt_tokens=5, completion_tokens=3),
            provider_latency_ms=10,
        )


@pytest.mark.asyncio
async def test_fallback_executor_switches_to_next_model():
    adapter = _FakeAdapter(
        {
            "mock-cheap": RateLimitError,  # primary lỗi 429
            "mock-mid": None,  # fallback ok
        }
    )
    executor = FallbackExecutor(adapters={"mock": adapter})
    chain = [_ref("mock-cheap"), _ref("mock-mid")]

    outcome = await executor.execute(chain, [Message(role="user", content="hi")], CompletionParams())

    assert outcome.result.content == "ok-mock-mid"
    assert outcome.fallback_count == 1
    assert outcome.chain_attempted == ["mock-cheap", "mock-mid"]


@pytest.mark.asyncio
async def test_fallback_executor_returns_first_success():
    adapter = _FakeAdapter({"mock-cheap": None, "mock-mid": None})
    executor = FallbackExecutor(adapters={"mock": adapter})
    chain = [_ref("mock-cheap"), _ref("mock-mid")]

    outcome = await executor.execute(chain, [Message(role="user", content="hi")], CompletionParams())

    assert outcome.result.content == "ok-mock-cheap"
    assert outcome.fallback_count == 0
    assert outcome.chain_attempted == ["mock-cheap"]


# --- AC-3.3: hết chain -> AllProvidersFailedError kèm chain_attempted ---


@pytest.mark.asyncio
async def test_fallback_executor_exhausted_chain_raises():
    adapter = _FakeAdapter({"mock-cheap": ProviderUnavailable, "mock-mid": ProviderUnavailable})
    executor = FallbackExecutor(adapters={"mock": adapter})
    chain = [_ref("mock-cheap"), _ref("mock-mid")]

    with pytest.raises(AllProvidersFailedError) as exc_info:
        await executor.execute(chain, [Message(role="user", content="hi")], CompletionParams())

    assert exc_info.value.chain_attempted == ["mock-cheap", "mock-mid"]


# --- AC-3.5 / ADR-010: content-filter KHÔNG fallback, dừng ngay ---


@pytest.mark.asyncio
async def test_fallback_executor_content_filter_stops_immediately():
    adapter = _FakeAdapter(
        {
            "mock-cheap": ContentFilteredError,  # không retryable
            "mock-mid": None,  # không được gọi
        }
    )
    executor = FallbackExecutor(adapters={"mock": adapter})
    chain = [_ref("mock-cheap"), _ref("mock-mid")]

    with pytest.raises(ContentFilteredError):
        await executor.execute(chain, [Message(role="user", content="bad")], CompletionParams())


@pytest.mark.asyncio
async def test_fallback_executor_bad_request_stops_immediately():
    adapter = _FakeAdapter({"mock-cheap": BadRequestToProvider, "mock-mid": None})
    executor = FallbackExecutor(adapters={"mock": adapter})
    chain = [_ref("mock-cheap"), _ref("mock-mid")]

    with pytest.raises(BadRequestToProvider):
        await executor.execute(chain, [Message(role="user", content="hi")], CompletionParams())


# --- AC-3.4: circuit OPEN loại model khỏi chain ---


@pytest.mark.asyncio
async def test_fallback_executor_skips_open_circuit_model():
    cb = CircuitBreaker(failure_threshold=1)
    adapter = _FakeAdapter({"mock-cheap": None, "mock-mid": None})
    executor = FallbackExecutor(adapters={"mock": adapter}, circuit=cb)

    # mock-cheap đang OPEN -> bị bỏ qua, dùng mock-mid
    cb.record_error(_ref("mock-cheap"), retryable=True)
    chain = [_ref("mock-cheap"), _ref("mock-mid")]

    outcome = await executor.execute(chain, [Message(role="user", content="hi")], CompletionParams())

    assert outcome.result.content == "ok-mock-mid"
    assert outcome.chain_attempted == ["mock-mid"]  # mock-cheap không nằm trong chain_attempted vì bị chặn


# --- circuit.record_error được gọi đúng khi adapter lỗi qua executor ---


@pytest.mark.asyncio
async def test_fallback_executor_records_errors_on_circuit():
    cb = CircuitBreaker(failure_threshold=1)
    adapter = _FakeAdapter({"mock-cheap": RateLimitError, "mock-mid": None})
    executor = FallbackExecutor(adapters={"mock": adapter}, circuit=cb)
    chain = [_ref("mock-cheap"), _ref("mock-mid")]

    await executor.execute(chain, [Message(role="user", content="hi")], CompletionParams())

    # mock-cheap lỗi 1 lần retryable -> circuit OPEN
    assert cb.state_of(_ref("mock-cheap")) == OPEN
    # mock-mid thành công -> CLOSED
    assert cb.state_of(_ref("mock-mid")) == CLOSED
