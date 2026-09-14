"""Contract Layer B — ranh giới giữa BE (orchestration, API) và AI-core.

Nguồn sự thật: `docs/design/05_interfaces.md` §B. Mọi thay đổi ở đây phải sửa
tài liệu trước (label `interface-change`, bump version) rồi mới sửa code.

BE không cần biết classifier/adapter làm gì bên trong — chỉ gọi đúng chữ ký dưới đây.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

# --- B.1 Kiểu dữ liệu chung -------------------------------------------------


class Tier(str, Enum):  # noqa: UP042 — contract §B.1 chốt `str, Enum`; đổi sang StrEnum phải sửa tài liệu trước
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class Signal:
    name: str  # vd "code", "multi_step", "classifier_error"
    points: int


@dataclass
class ModelRef:
    model_id: str  # vd "gemini-flash-lite"
    provider: str  # vd "google"


@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int


# --- B.2 Classifier — hợp đồng chấm độ khó (FR-02, FR-12) -------------------


@dataclass
class ClassificationResult:
    score: int  # 0..100
    tier: Tier
    signals: list[Signal]  # giải thích được (NFR-05)
    classifier_version: str  # "heuristic-v1" | "llm-v2" | "embed-v2"
    latency_ms: int
    cost_usd: Decimal = Decimal("0")  # §9.1 — chi phí của chính router; 0 với heuristic
    intent: str | None = None  # doc 13 — nhãn intent lượt do LLM chấm; None khi fallback/không có


class BaseClassifier(ABC):
    """Cam kết hành vi (phần của contract):

    1. Không bao giờ raise. Lỗi nội bộ/timeout -> tier=T2, score=45,
       signals=[Signal("classifier_error", 0)] (an toàn giữa).
    2. Tự giới hạn thời gian <= ROUTER_TIMEOUT_MS (env, mặc định 800ms).
    3. Thuần chức năng: không ghi DB, không đọc config ngoài constructor.
    """

    @abstractmethod
    async def classify(self, messages: list[Message]) -> ClassificationResult: ...


# --- B.3 Policy Engine — hợp đồng chọn model (FR-11, FR-04) -----------------


@dataclass
class RoutingPlan:
    chain: list[ModelRef]  # thứ tự thử; phần tử 0 là primary
    tier_effective: Tier  # tier sau khi áp tier_shift của policy / force_tier
    policy_applied: str


class NoCapableModelError(Exception):
    """Không còn model nào đủ capability — API layer map thành 400 unsupported_capability."""


class BasePolicyEngine(ABC):
    """Cam kết: `chain` không rỗng, không chứa phần tử trong `exclude`, và mọi model
    trong chain đều có đủ `required_capabilities`; tier rỗng sau lọc -> dùng chain của
    tier liền kề cao hơn; hết model phù hợp -> raise NoCapableModelError;
    `force_model` hợp lệ -> chain một phần tử.
    """

    @abstractmethod
    def select(
        self,
        classification: ClassificationResult,
        policy: str | None = None,  # None -> default_policy trong config
        force_model: str | None = None,
        force_tier: Tier | None = None,
        floor_tier: Tier | None = None,
        required_capabilities: frozenset[str] = frozenset({"text"}),
        exclude: frozenset[tuple[str, str]] = frozenset(),  # (model_id, provider) đang circuit OPEN
        input_tokens: int | None = None,  # §8: lọc model có context_window < input
    ) -> RoutingPlan: ...


# --- B.4 Adapter — hợp đồng gọi provider (FR-03) ----------------------------


@dataclass
class CompletionParams:
    temperature: float | None = None
    max_tokens: int | None = None
    extra: dict = field(default_factory=dict)  # pass-through, adapter tự lọc field hỗ trợ


@dataclass
class CompletionResult:
    content: str
    finish_reason: str  # "stop" | "length" | "content_filter"
    usage: Usage  # BẮT BUỘC chính xác — nguồn tính cost
    provider_latency_ms: int
    usage_estimated: bool = False
    dropped_params: list[str] = field(default_factory=list)


@dataclass
class StreamChunk:
    delta: str
    finish_reason: str | None = None
    usage: Usage | None = None  # chỉ khác None ở chunk cuối


class BaseAdapter(ABC):
    provider: str  # định danh duy nhất, vd "google"
    models: list[str]  # model_id adapter này phục vụ
    model_capabilities: dict[str, frozenset[str]]  # nguồn cho A.1b & lọc B.3

    @abstractmethod
    async def complete(self, model_id: str, messages: list[Message], params: CompletionParams) -> CompletionResult: ...

    @abstractmethod
    def stream(
        self, model_id: str, messages: list[Message], params: CompletionParams
    ) -> AsyncIterator[StreamChunk]: ...

    @abstractmethod
    async def health(self) -> bool: ...


# --- B.5 Taxonomy lỗi — điều khiển fallback (FR-09) ------------------------
# Mỗi adapter phải bắt lỗi thô của SDK/HTTP và map về đúng taxonomy này.
# BE tuyệt đối không xử lý lỗi riêng của từng provider.
# Circuit breaker đếm trên retryable=True.
#
# Tên lớp lấy nguyên từ contract §B.5 nên bỏ qua N818 (quy tắc "phải kết thúc bằng Error"):
# adapter của cả hai nhóm map lỗi theo đúng các tên này, đổi tên là breaking change.


class ProviderError(Exception):
    retryable: bool = False  # gateway CHỈ fallback khi retryable=True


class RateLimitError(ProviderError):
    retryable = True  # 429


class ProviderUnavailable(ProviderError):  # noqa: N818
    retryable = True  # 5xx / network


class ProviderTimeout(ProviderError):  # noqa: N818
    retryable = True  # quá REQUEST_TIMEOUT_S


class ContentFilteredError(ProviderError):
    retryable = False  # trả lỗi cho client (ADR-010)


class BadRequestToProvider(ProviderError):  # noqa: N818
    retryable = False  # bug mapping, log + trả 500
