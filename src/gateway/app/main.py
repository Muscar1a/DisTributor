from __future__ import annotations

import dataclasses
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.gateway.app.adapters.mock_adapter import MockAdapter
from src.gateway.app.api.admin import router as admin_router
from src.gateway.app.api.chat_completions import router as completions_router
from src.gateway.app.api.compatibility import router as compatibility_router
from src.gateway.app.api.errors import openai_error_response
from src.gateway.app.api.feedback import router as feedback_router
from src.gateway.app.api.health import router as health_router
from src.gateway.app.api.limits import MAX_MESSAGES
from src.gateway.app.api.middleware import AuthMiddleware, BodySizeLimitMiddleware, RateLimitMiddleware
from src.gateway.app.api.sessions import router as sessions_router
from src.gateway.app.config.loader import (
    Config,
    ModelPricing,
    TierRoute,
    load_config,
    load_gateway_settings,
    load_routing_config,
)
from src.gateway.app.core.build_info import get_build_metadata
from src.gateway.app.core.circuit import CircuitBreaker
from src.gateway.app.core.classifier_v1_5 import ClassifierV1_5Heuristic
from src.gateway.app.core.classifier_v2 import LRUCache
from src.gateway.app.core.cost import CostCalculator
from src.gateway.app.core.fallback import FallbackExecutor
from src.gateway.app.core.interfaces import ModelRef, Tier
from src.gateway.app.core.orchestrator import RequestOrchestrator
from src.gateway.app.core.outcome_observer import OutcomeObserver
from src.gateway.app.core.policy import PolicyEngineV1
from src.gateway.app.core.provider_status import ProviderStatusRegistry
from src.gateway.app.core.quota import QuotaGuard
from src.gateway.app.core.session_router import SessionRouter
from src.gateway.app.core.tier_limiter import TierRateLimiter
from src.gateway.app.db.crud import get_config as db_get_config
from src.gateway.app.db.session import SessionLocal

load_dotenv()

_MOCK_MODEL_BY_TIER = {
    Tier.T1: "mock-cheap",
    Tier.T2: "mock-mid",
    Tier.T3: "mock-premium",
}


def _with_mock_routes(config: Config) -> Config:
    """Return a runtime config whose routes match the mock-only adapter registry.

    The checked-in routing config intentionally names real providers. Merely
    loading ``MockAdapter`` while retaining those routes leaves the fallback
    executor with no matching adapter and every request fails with an empty
    ``chain_attempted``. Mock mode therefore needs a complete, internally
    consistent runtime routing snapshot.
    """
    tiers = {
        tier: TierRoute(primary=ModelRef(model_id=model_id, provider="mock"), fallbacks=())
        for tier, model_id in _MOCK_MODEL_BY_TIER.items()
    }
    quality_by_model = {
        "mock-cheap": 1,
        "mock-mid": 5,
        "mock-premium": 10,
    }
    pricing = dict(config.pricing)
    pricing.update(
        {
            model_id: ModelPricing(
                provider="mock",
                input_per_1m_usd=0.0,
                output_per_1m_usd=0.0,
                quality_rank=quality_by_model[model_id],
            )
            for model_id in _MOCK_MODEL_BY_TIER.values()
        }
    )
    return dataclasses.replace(config, tiers=tiers, pricing=pricing)


def _build_adapters(settings) -> dict:
    """Đăng ký adapters dựa vào settings/env. use_mock_providers=true -> chỉ mock."""
    if settings.use_mock_providers:
        return {"mock": MockAdapter()}
    adapters: dict = {}
    if key := os.getenv("GEMINI_API_KEY"):
        from src.gateway.app.adapters.gemini_adapter import GeminiAdapter

        adapters["google"] = GeminiAdapter(api_key=key)
    if key := os.getenv("GROQ_API_KEY"):
        from src.gateway.app.adapters.groq_adapter import GroqAdapter

        adapters["groq"] = GroqAdapter(api_key=key)
    if key := os.getenv("OPENAI_API_KEY"):
        from src.gateway.app.adapters.openai_adapter import OpenAIAdapter

        adapters["openai"] = OpenAIAdapter(api_key=key)
    return adapters


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_config()

    # Apply DB overrides saved via PUT /admin/config (survives restart)
    _db = SessionLocal()
    try:
        _override = db_get_config(_db, "routing_overrides")
        if _override and _override.value:
            v = _override.value
            overrides_kwargs = {k: v[k] for k in ("default_policy", "t1_max", "t2_max") if k in v}
            if "policies" in v and isinstance(v["policies"], dict):
                from src.gateway.app.config.loader import PolicyRule

                overrides_policies = dict(config.policies)
                for pname, pdata in v["policies"].items():
                    if pname in overrides_policies and isinstance(pdata, dict):
                        overrides_policies[pname] = PolicyRule(
                            tier_shift=int(pdata.get("tier_shift", overrides_policies[pname].tier_shift)),
                            order_by=str(pdata.get("order_by", overrides_policies[pname].order_by)),
                        )
                overrides_kwargs["policies"] = overrides_policies
            config = dataclasses.replace(config, **overrides_kwargs)
    finally:
        _db.close()

    settings = load_gateway_settings()
    if settings.use_mock_providers:
        config = _with_mock_routes(config)
    adapters = _build_adapters(settings)

    capabilities: dict[str, frozenset[str]] = {}
    for adapter in adapters.values():
        capabilities.update(adapter.model_capabilities)

    circuit = CircuitBreaker(
        failure_threshold=settings.cb_error_threshold,
        recovery_timeout_s=settings.cb_open_seconds,
    )
    t3_rpm = int(os.getenv("T3_RPM", "0"))
    tier_limiter = TierRateLimiter({"T3": t3_rpm}) if t3_rpm > 0 else None
    orchestrator = RequestOrchestrator(
        classifier=ClassifierV1_5Heuristic(t1_max=config.t1_max, t2_max=config.t2_max),
        policy_engine=PolicyEngineV1(config=config, model_capabilities=capabilities),
        fallback_executor=FallbackExecutor(adapters=adapters, circuit=circuit),
        cost_calculator=CostCalculator(
            pricing={
                k: {"input_per_1m_usd": v.input_per_1m_usd, "output_per_1m_usd": v.output_per_1m_usd}
                for k, v in config.pricing.items()
            }
        ),
        tier_limiter=tier_limiter,
    )

    routing_cfg = load_routing_config()
    session_router = SessionRouter(
        t1_max=config.t1_max,
        t2_max=config.t2_max,
        alpha=routing_cfg.alpha,
        deescalate_margin=routing_cfg.deescalate_margin,
        dwell_turns=routing_cfg.dwell_turns,
        max_session_escalations=routing_cfg.max_session_escalations,
        failure_boost=routing_cfg.failure_boost,
        streak_boost=routing_cfg.streak_boost,
        similarity_threshold=routing_cfg.similarity_threshold,
    )

    app.state.orchestrator = orchestrator
    app.state.config = config
    app.state.circuit = circuit
    app.state.provider_registry = ProviderStatusRegistry(config, adapters, circuit)
    app.state.settings = settings
    app.state.quota_guard = QuotaGuard(db_factory=SessionLocal)
    app.state.session_router = session_router
    app.state.routing_config = routing_cfg
    app.state.outcome_observer = OutcomeObserver(db_factory=SessionLocal)
    # Shared across requests — classifier v2 is rebuilt per-request, a per-instance cache never hits.
    app.state.classifier_v2_cache = LRUCache(capacity=1000)

    yield


app = FastAPI(
    title="DisTributor Gateway",
    description="Multi-provider LLM routing gateway — text-only OpenAI-compatible subset.",
    version=get_build_metadata()["version"],
    lifespan=lifespan,
)


allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")
    if origin.strip()
]

# Allow any domain (tunnel domains, LAN IPs, localhost) by default unless ALLOWED_ORIGIN_REGEX is set
default_origin_regex = r"^https?://.*"

app.add_middleware(RateLimitMiddleware)  # inner: chạy SAU Auth trên request
app.add_middleware(AuthMiddleware)
app.add_middleware(BodySizeLimitMiddleware)  # chạy TRƯỚC Auth: chặn body lớn sớm nhất
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=os.getenv("ALLOWED_ORIGIN_REGEX", default_origin_regex),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "Retry-After",
        "X-Request-Id",
        "X-SR-Request-Id",
        "x-request-id",
        "X-SR-Score",
        "X-SR-Tier",
        "X-SR-Tier-Effective",
        "X-SR-Model",
        "X-SR-Provider",
        "X-SR-Cost-USD",
        "X-SR-Dropped-Params",
        "X-SR-Clamped",
    ],
)  # outermost: CORS headers are included on auth/rate-limit error responses


static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
@app.get("/playground", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
@app.get("/logs", include_in_schema=False)
@app.get("/keys", include_in_schema=False)
@app.get("/config", include_in_schema=False)
@app.get("/settings", include_in_schema=False)
async def playground():
    return FileResponse(static_dir / "index.html")


app.include_router(health_router)
app.include_router(completions_router, prefix="/v1")
app.include_router(compatibility_router, prefix="/v1")
app.include_router(admin_router, prefix="/admin")
app.include_router(feedback_router, prefix="/v1")
app.include_router(sessions_router, prefix="/v1")


# ---------------------------------------------------------------------------
# AC-4: Exception handlers — chuẩn hóa mọi lỗi HTTP thành ErrorEnvelope
# ---------------------------------------------------------------------------

_STATUS_TYPE_MAP: dict[int, tuple[str, str | None]] = {
    400: ("invalid_request_error", None),
    401: ("authentication_error", "invalid_api_key"),
    404: ("not_found_error", "not_found"),
    413: ("invalid_request_error", "payload_too_large"),
    422: ("invalid_request_error", "validation_error"),
    429: ("rate_limit_error", None),
    500: ("internal_error", "internal_error"),
    502: ("provider_error", "provider_error"),
}


@app.exception_handler(StarletteHTTPException)
async def _http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    err_type, err_code = _STATUS_TYPE_MAP.get(exc.status_code, ("internal_error", None))
    param = "request" if exc.status_code == 400 else None
    details: dict = {}
    message = str(exc.detail)
    if isinstance(exc.detail, dict):
        message = str(exc.detail.get("message", message))
        err_type = str(exc.detail.get("type", err_type))
        err_code = exc.detail.get("code", err_code)
        param = exc.detail.get("param", param)
        details = dict(exc.detail.get("details", {}))
    if exc.status_code == 404 and err_code is None:
        err_code = "endpoint_not_found"
        details = {"endpoint": request.url.path, **details}
    return openai_error_response(
        status_code=exc.status_code,
        request_id=request_id,
        message=message,
        error_type=err_type,
        code=err_code,
        param=param,
        details=details,
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    errors = exc.errors()

    # Image/multimodal content → 400 unsupported_parameter (#223: image content must not be 422)
    image_content_errors = [
        e for e in errors
        if "messages" in str(e.get("loc", ""))
        and "content" in str(e.get("loc", ""))
        and e.get("type") in ("string_type", "union_tag_invalid", "literal_error")
    ]
    if image_content_errors:
        return openai_error_response(
            status_code=400,
            request_id=request_id,
            message="Image and multimodal message content is not supported. Only text strings are accepted.",
            error_type="invalid_request_error",
            code="unsupported_parameter",
            param="messages.content",
            details={"parameter": "messages[*].content", "capability": "text_only"},
        )

    # Extra fields (additionalProperties: false) → 400 unsupported_parameter for chat completions
    extra = [e for e in errors if e.get("type") == "extra_forbidden"]
    if extra and request.url.path.endswith("/chat/completions"):
        field = ".".join(str(part) for part in extra[0]["loc"] if part != "body" and not isinstance(part, int))
        return openai_error_response(
            status_code=400,
            request_id=request_id,
            message=f"Tham số '{field}' không được hỗ trợ trong phạm vi text-only của gateway.",
            error_type="invalid_request_error",
            code="unsupported_parameter",
            param=field,
            details={"parameter": field},
        )

    # Specific validator messages
    for err in errors:
        val_msg = str(err.get("msg", ""))
        loc = err.get("loc", ())
        if "messages" in loc and "content" in loc and isinstance(err.get("input"), (list, dict)):
            return openai_error_response(
                status_code=400,
                request_id=request_id,
                message="Image, audio, and file message content are not supported; send text content only.",
                error_type="invalid_request_error",
                code="unsupported_parameter",
                param="messages.content",
                details={"parameter": "messages.content", "capability": "text_only"},
            )
        if "stream=true" in val_msg or ("stream" in str(err.get("loc", "")) and "stream" in val_msg):
            return openai_error_response(
                status_code=400,
                request_id=request_id,
                message="stream=true chưa được hỗ trợ trước mốc M3.",
                error_type="invalid_request_error",
                code="unsupported_parameter",
                param="stream",
                details={"parameter": "stream"},
            )
        if err.get("type") in {"list_too_long", "too_long"} and "messages" in str(err.get("loc", "")):
            return openai_error_response(
                status_code=400,
                request_id=request_id,
                message=f"Vượt giới hạn {MAX_MESSAGES} messages.",
                error_type="invalid_request_error",
                code="too_many_messages",
                param="messages",
                details={"limit": MAX_MESSAGES},
            )

    # Mọi lỗi schema còn lại → 422
    first_error = errors[0] if errors else {}
    validation_param = ".".join(
        str(part) for part in first_error.get("loc", ()) if part != "body" and not isinstance(part, int)
    ) or None
    return openai_error_response(
        status_code=422,
        request_id=request_id,
        message="Body sai schema.",
        error_type="invalid_request_error",
        code="validation_error",
        param=validation_param,
        details={"loc": list(first_error["loc"]), "msg": first_error["msg"]} if errors else {},
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Keep unexpected failures SDK-compatible without exposing internals."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return openai_error_response(
        status_code=500,
        request_id=request_id,
        message="An internal gateway error occurred.",
        error_type="internal_error",
        code="internal_error",
        details={},
    )
