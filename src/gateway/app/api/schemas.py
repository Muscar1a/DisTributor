import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field
from pydantic.json_schema import WithJsonSchema

NullableString = Annotated[str | None, WithJsonSchema({"type": ["string", "null"]})]
NullableInteger = Annotated[int | None, WithJsonSchema({"type": ["integer", "null"]})]
NullableNumber = Annotated[float | None, WithJsonSchema({"type": ["number", "null"]})]
NullableDateTime = Annotated[str | None, WithJsonSchema({"type": ["string", "null"], "format": "date-time"})]


class SignalResponse(BaseModel):
    name: str
    points: int


class ChainAttemptResponse(BaseModel):
    model: str
    provider: str
    status: Annotated[str, WithJsonSchema({"type": "string", "enum": ["ok", "error", "skipped"]})]
    error: NullableString = None


class SmartRouteMetaResponse(BaseModel):
    request_id: uuid.UUID
    difficulty_score: int = Field(ge=0, le=100)
    tier: Literal["T1", "T2", "T3"]
    signals: list[SignalResponse]
    policy: Literal["cost_first", "balanced", "quality_first"]
    model_used: str
    provider: str
    classifier_version: str
    cost_usd: NullableNumber = None
    router_cost_usd: float = 0.0  # §9.1 — chi phí của chính router (0 với heuristic)
    outcome_evidence: dict | None = None  # §9 — bằng chứng thất bại quan sát được
    latency_total_ms: NullableInteger = None
    latency_router_ms: NullableInteger = None
    fallback_count: int = Field(ge=0)
    usage_estimated: bool = False
    chain_attempted: list[ChainAttemptResponse] = Field(default_factory=list)
    tier_effective: Literal["T1", "T2", "T3"] | None = None
    tier_changed: bool = False
    # #225: token counts exposed in meta for usage endpoint
    prompt_tokens: NullableInteger = None
    completion_tokens: NullableInteger = None
    total_tokens: int = 0


class AssistantMessageResponse(BaseModel):
    role: Literal["assistant"]
    content: str


class ChoiceResponse(BaseModel):
    index: int = Field(ge=0)
    message: AssistantMessageResponse
    finish_reason: Literal["stop", "length", "content_filter"]


class Usage(BaseModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ChatCompletionResponse(BaseModel):
    id: str
    object: Literal["chat.completion"]
    created: int
    model: str
    choices: list[ChoiceResponse] = Field(min_length=1)
    usage: Usage
    smartroute: SmartRouteMetaResponse


class UsageResponse(BaseModel):
    status: Literal["pending", "complete"]
    smartroute: SmartRouteMetaResponse
    cost_usd: NullableNumber = None
    pricing_version: NullableString = None
    config_version: NullableString = None
    input_price: float | None = None
    output_price: float | None = None
    unit_prices: dict[str, float] | None = None


class ModelResponse(BaseModel):
    id: str
    object: Literal["model"]
    provider: str
    default_tier: Literal["T1", "T2", "T3"]
    capabilities: list[Literal["text", "stream"]]
    enabled: bool


class ModelListResponse(BaseModel):
    object: Literal["list"]
    data: list[ModelResponse]


class ProviderHealthResponse(BaseModel):
    provider: str
    status: Literal["available", "disabled", "unavailable", "unhealthy"]
    configured: bool
    available: bool
    circuit: Literal["closed", "open", "half_open"]
    consecutive_errors: int = Field(ge=0)
    open_until: NullableDateTime = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    commit_sha: str
    build_timestamp: str
    db: Literal["ok", "unavailable"]
    classifier_error_rate: float = Field(ge=0, le=1)
    providers: list[ProviderHealthResponse]


class ReadinessChecks(BaseModel):
    database: Literal["ok", "unavailable"]
    config: Literal["ok", "invalid"]
    providers: Literal["ok", "degraded", "unavailable"]


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadinessChecks


class ErrorBody(BaseModel):
    message: str
    type: Literal[
        "invalid_request_error",
        "authentication_error",
        "not_found_error",
        "quota_exceeded",
        "rate_limit_error",
        "provider_error",
        "internal_error",
    ]
    param: NullableString
    code: NullableString
    request_id: uuid.UUID
    details: dict[str, Any]


class ErrorEnvelope(BaseModel):
    error: ErrorBody
