import asyncio
import hashlib
import json
import logging
import time
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import WithJsonSchema
from sqlalchemy.orm import Session

from src.gateway.app.api.admin import _redact
from src.gateway.app.api.errors import openai_error_response
from src.gateway.app.api.limits import MAX_BODY_BYTES, MAX_INPUT_TOKENS, MAX_MESSAGES, MAX_OUTPUT_TOKENS
from src.gateway.app.api.schemas import (
    ChatCompletionResponse,
    ErrorEnvelope,
    ModelListResponse,
    ModelResponse,
    UsageResponse,
)
from src.gateway.app.config.loader import load_config
from src.gateway.app.core.classifier_v1_5 import ClassifierV1_5Heuristic
from src.gateway.app.core.classifier_v2 import ClassifierV2AI
from src.gateway.app.core.estimator import TokenEstimator
from src.gateway.app.core.fallback import AllProvidersFailedError
from src.gateway.app.core.interfaces import (
    CompletionParams,
    Message,
    NoCapableModelError,
    ProviderError,
    Tier,
)
from src.gateway.app.core.quota import check_daily_token_budget, get_daily_quota_reset
from src.gateway.app.core.session_router import SessionRouter
from src.gateway.app.core.session_router.state import SessionState
from src.gateway.app.db.crud import (
    create_request_log,
    create_session,
    get_request_log,
    get_routing_state,
    get_session,
    update_request_log,
    update_routing_state,
    update_session_activity,
)
from src.gateway.app.db.session import SessionLocal, get_db

logger = logging.getLogger("smartroute.classifier")

NullablePolicy = Annotated[
    Literal["cost_first", "balanced", "quality_first"] | None,
    WithJsonSchema(
        {
            "oneOf": [
                {"type": "string", "enum": ["cost_first", "balanced", "quality_first"]},
                {"type": "null"},
            ]
        }
    ),
]
NullableTier = Annotated[
    Literal["T1", "T2", "T3"] | None,
    WithJsonSchema({"oneOf": [{"type": "string", "enum": ["T1", "T2", "T3"]}, {"type": "null"}]}),
]
NullableModel = Annotated[str | None, WithJsonSchema({"type": ["string", "null"]})]
NullableUUID = Annotated[
    uuid.UUID | None, WithJsonSchema({"oneOf": [{"type": "string", "format": "uuid"}, {"type": "null"}]})
]


router = APIRouter()

_token_estimator = TokenEstimator()


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant", "system", "user"]
    content: str = Field(min_length=1)


def _pick_v2_adapter(adapters: dict, pricing: dict, model_id: str):
    """Adapter phục vụ `model_id` của classifier v2 — chọn theo PROVIDER của model.

    Chọn theo thứ tự cứng (google→openai→groq) là đưa model_id của provider này cho
    adapter của provider kia. Không tìm được thì trả None: v2 tự suy biến về v1.5 và
    phát signal `v2_fallback`, thay vì gọi nhầm adapter.
    """
    entry = pricing.get(model_id)
    if entry and (adapter := adapters.get(entry.provider)):
        return adapter
    # USE_MOCK_PROVIDERS=true -> registry chỉ có {"mock": ...}; đó là chế độ test/demo.
    if set(adapters) == {"mock"}:
        return adapters["mock"]
    return None


NullableClassifierVersion = Annotated[
    Literal["v1", "v1.5", "v2"] | None,
    WithJsonSchema({"type": ["string", "null"], "enum": ["v1", "v1.5", "v2", None]}),
]


class SmartRouteOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: NullablePolicy = None
    force_model: NullableModel = None
    force_tier: NullableTier = None
    session_id: NullableUUID = None
    allow_tier_downgrade: bool = False
    classifier_version: NullableClassifierVersion = None


class ChatCompletionRequest(BaseModel):
    """Text-only OpenAI-compatible request subset."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "description": (
                f"Public boundaries: HTTP body <= {MAX_BODY_BYTES:,} bytes; "
                f"messages <= {MAX_MESSAGES}; estimated input <= {MAX_INPUT_TOKENS:,} tokens; "
                f"max_tokens is clamped to {MAX_OUTPUT_TOKENS:,}."
            )
        },
    )

    model: str = "auto"
    messages: list[ChatMessage] = Field(
        min_length=1,
        max_length=MAX_MESSAGES,
        description=(
            f"One to {MAX_MESSAGES} text-only messages. Input is also limited to "
            f"{MAX_INPUT_TOKENS} estimated tokens across all messages."
        ),
    )
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(
        default=None,
        ge=1,
        description=(
            f"Requested output-token limit. Values above {MAX_OUTPUT_TOKENS} are accepted, "
            f"clamped to {MAX_OUTPUT_TOKENS}, and reported with X-SR-Clamped: max_tokens."
        ),
        json_schema_extra={"x-sr-clamp-maximum": MAX_OUTPUT_TOKENS},
    )
    top_p: float | None = Field(default=None, ge=0, le=1)
    stop: str | list[str] | None = None
    stream: bool = False
    smartroute: SmartRouteOptions = None


def _signals_payload(signals):
    return [{"name": signal.name, "points": signal.points} for signal in signals]


def _database_api_key_id(request: Request) -> int | None:
    """Return only database-backed key IDs; dev-key hashes are limiter identities."""
    raw_key_id = getattr(request.state, "api_key_id", None)
    return raw_key_id if isinstance(raw_key_id, int) else None


def _pricing_version(cfg: Any) -> str:
    try:
        pricing = getattr(cfg, "pricing", {})
        data = {k: {"input_per_1m_usd": v.input_per_1m_usd, "output_per_1m_usd": v.output_per_1m_usd} for k, v in pricing.items()}
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
    except Exception:
        return "pricing-unknown"


def _active_config_version(cfg: Any) -> str:
    try:
        body = {
            "default_policy": getattr(cfg, "default_policy", "balanced"),
            "t1_max": getattr(cfg, "t1_max", 30),
            "t2_max": getattr(cfg, "t2_max", 60),
            "policies": {
                name: {"tier_shift": rule.tier_shift, "order_by": rule.order_by}
                for name, rule in getattr(cfg, "policies", {}).items()
            },
        }
        return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
    except Exception:
        return "config-unknown"


def _get_model_unit_prices(cfg: Any, model_id: str | None) -> tuple[dict[str, float] | None, float | None, float | None]:
    if not model_id:
        return None, None, None
    try:
        pricing = getattr(cfg, "pricing", {})
        entry = pricing.get(model_id)
        if entry:
            prices = {
                "input_per_1m_usd": float(entry.input_per_1m_usd),
                "output_per_1m_usd": float(entry.output_per_1m_usd),
            }
            return prices, float(entry.input_per_1m_usd), float(entry.output_per_1m_usd)
    except Exception:
        pass
    return None, None, None


def _meta(log):
    return {
        "request_id": str(log.id),
        "difficulty_score": log.difficulty_score,
        "tier": log.tier,
        "signals": log.signals or [],
        "policy": log.policy,
        "model_used": log.model,
        "provider": log.provider,
        "classifier_version": log.classifier_version or "heuristic-v1.5",
        "cost_usd": float(log.cost_usd) if log.cost_usd is not None else None,
        "router_cost_usd": float(log.router_cost_usd) if log.router_cost_usd is not None else 0.0,
        "outcome_evidence": log.outcome_evidence,
        "latency_total_ms": log.latency_total_ms,
        "latency_router_ms": log.latency_router_ms,
        "fallback_count": log.fallback_count or 0,
        "usage_estimated": bool(log.usage_estimated),
        "chain_attempted": log.chain_attempted or [],
        # #225: expose token counts in usage/meta
        "prompt_tokens": log.prompt_tokens,
        "completion_tokens": log.completion_tokens,
        "total_tokens": (log.prompt_tokens or 0) + (log.completion_tokens or 0),
    }


def complete_request_log(
    request_id: str,
    result_data: dict,
    session_id: uuid.UUID | None = None,
    new_routing_state: dict | None = None,
) -> None:
    """Phase 2: use an independent session because the request session may be closed."""
    db = SessionLocal()
    try:
        update_request_log(db, request_id, result_data)
        if session_id:
            update_session_activity(db, session_id)
            if new_routing_state:
                update_routing_state(db, session_id, new_routing_state)
    finally:
        db.close()


_CHAT_RESPONSE_HEADERS = {
    "X-Request-Id": {"required": True, "schema": {"type": "string", "format": "uuid"}},
    "X-SR-Request-Id": {"required": True, "schema": {"type": "string", "format": "uuid"}},
    "X-SR-Score": {"required": True, "schema": {"type": "integer", "minimum": 0, "maximum": 100}},
    "X-SR-Tier": {"required": True, "schema": {"type": "string", "enum": ["T1", "T2", "T3"]}},
    "X-SR-Model": {"required": True, "schema": {"type": "string"}},
    "X-SR-Provider": {"required": True, "schema": {"type": "string"}},
    "X-SR-Cost-USD": {"schema": {"type": "string"}},
    "X-SR-Dropped-Params": {"schema": {"type": "string"}},
    "X-SR-Clamped": {
        "description": (
            f"Present as 'max_tokens' when the requested value was clamped to {MAX_OUTPUT_TOKENS}."
        ),
        "schema": {"type": "string", "enum": ["max_tokens"]},
    },
}


@router.post(
    "/chat/completions",
    tags=["chat"],
    response_model=ChatCompletionResponse,
    responses={
        200: {"headers": _CHAT_RESPONSE_HEADERS},
        422: {"model": ErrorEnvelope, "description": "Validation Error"},
    },
)
async def chat_completions(
    request: ChatCompletionRequest,
    _req: Request,
    background_tasks: BackgroundTasks,
    response: Response,
    db: Session = Depends(get_db),
):

    # AC-5.3: token guard — ước lượng trước khi gọi provider
    estimated_tokens = sum(_token_estimator.estimate_tokens(m.content) for m in request.messages)
    settings = _req.app.state.settings
    max_input_tokens = settings.max_input_tokens
    if estimated_tokens > max_input_tokens:
        request_id = getattr(_req.state, "request_id", str(uuid.uuid4()))
        return openai_error_response(
            status_code=400,
            request_id=request_id,
            message=f"Tổng input ước lượng {estimated_tokens} token vượt giới hạn {max_input_tokens}.",
            error_type="invalid_request_error",
            code="context_too_long",
            param="messages",
            details={"limit": max_input_tokens, "estimated": estimated_tokens},
        )

    # AC-2: per-client daily token budget — chặn trước khi gọi provider để không đốt thêm token.
    _api_key_id = getattr(_req.state, "api_key_id", None)
    _used_today = check_daily_token_budget(db, _api_key_id, settings.daily_token_budget)
    if _used_today is not None:
        _reset_at, _retry_after_seconds = get_daily_quota_reset()
        resp = JSONResponse(
            status_code=429,
            content={
                "error": {
                    "message": (
                        f"Quota limit exceeded ({settings.daily_token_budget:,} tokens). "
                        "Please try again later."
                    ),
                    "type": "quota_exceeded",
                    "param": None,
                    "code": "daily_token_budget_exceeded",
                    "request_id": getattr(_req.state, "request_id", str(uuid.uuid4())),
                    "reset_at": _reset_at.isoformat().replace("+00:00", "Z"),
                    "retry_after_seconds": _retry_after_seconds,
                    "details": {"limit": settings.daily_token_budget, "used": _used_today},
                }
            },
        )
        resp.headers["Retry-After"] = str(_retry_after_seconds)
        return resp

    started = time.perf_counter()
    messages = [Message(role=item.role, content=item.content) for item in request.messages]

    max_tokens_clamped = request.max_tokens is not None and request.max_tokens > MAX_OUTPUT_TOKENS
    effective_max_tokens = MAX_OUTPUT_TOKENS if max_tokens_clamped else request.max_tokens
    params = CompletionParams(
        temperature=request.temperature,
        max_tokens=effective_max_tokens,
        extra={"top_p": request.top_p, "stop": request.stop},
    )

    # AC-3: classify → policy select using real orchestrator components
    orchestrator = _req.app.state.orchestrator
    sr = request.smartroute
    requested_classifier = sr.classifier_version if sr else None

    if requested_classifier == "v2":
        cfg = getattr(_req.app.state, "config", None)
        pricing = cfg.pricing if cfg else {}
        model_id = settings.classifier_v2_model
        fb_exec = orchestrator.fallback_executor
        adapter = _pick_v2_adapter(fb_exec.adapters if fb_exec else {}, pricing, model_id)
        if adapter is None:
            logger.warning(
                "classifier v2 requested nhưng không có adapter cho model %s — dùng heuristic v1.5",
                model_id,
            )
        classifier = ClassifierV2AI(
            adapter=adapter,
            model_id=model_id,
            t1_max=cfg.t1_max if cfg else 30,
            t2_max=cfg.t2_max if cfg else 60,
            pricing=pricing,
            router_timeout_ms=settings.router_timeout_ms,
            cache=getattr(_req.app.state, "classifier_v2_cache", None),
        )
    elif requested_classifier == "v1.5":
        cfg = getattr(_req.app.state, "config", None)
        classifier = ClassifierV1_5Heuristic(
            t1_max=cfg.t1_max if cfg else 30,
            t2_max=cfg.t2_max if cfg else 60,
        )
    else:
        classifier = orchestrator.classifier

    classification = await classifier.classify(messages)
    logger.info(
        "classifier=%s score=%d tier=%s signals=%s",
        classification.classifier_version,
        classification.score,
        classification.tier.value,
        [s.name for s in classification.signals],
    )
    print(
        f"[SmartRoute] classifier={classification.classifier_version} "
        f"score={classification.score} tier={classification.tier.value} "
        f"signals={[s.name for s in classification.signals]}"
    )

    policy = sr.policy if sr else None
    force_model = sr.force_model if sr else None
    user_force_tier = Tier(sr.force_tier) if sr and sr.force_tier else None
    session_id = sr.session_id if sr else None
    allow_tier_downgrade = sr.allow_tier_downgrade if sr else False

    # --- Session routing (§5) — adjust tier based on conversation state ---
    session_router: SessionRouter | None = getattr(_req.app.state, "session_router", None)
    routing_cfg = getattr(_req.app.state, "routing_config", None)
    _session_signals = []
    _new_routing_state = None
    _floor_tier: Tier | None = None
    effective_cls = classification

    if session_router and not force_model and not user_force_tier:
        raw_messages = [{"role": m.role, "content": m.content} for m in request.messages]
        state = None
        if session_id:
            state_dict, last_activity = get_routing_state(db, session_id)
            state = SessionState.from_dict(state_dict)
            ttl = routing_cfg.session_routing_ttl_s if routing_cfg else 7200
            if state.turn_count > 0 and state.is_expired(last_activity, ttl):
                state = SessionState()
        session_tier, _session_signals, _new_routing_state, _floor_tier, effective_score = session_router.route(
            raw_messages, state, classification,
        )
        if effective_score != classification.score:
            import dataclasses
            effective_cls = dataclasses.replace(classification, score=effective_score)

    _quota_guard = getattr(_req.app.state, "quota_guard", None)
    _quota_excluded = _quota_guard.exhausted_models() if _quota_guard else frozenset()
    _circuit_excluded = orchestrator.fallback_executor.circuit.open_set()
    _excluded = _circuit_excluded | _quota_excluded

    try:
        plan = orchestrator.policy_engine.select(
            effective_cls,
            policy=policy,
            force_model=force_model,
            force_tier=user_force_tier,
            floor_tier=_floor_tier,
            exclude=_excluded,
            input_tokens=estimated_tokens,
        )
    except NoCapableModelError as exc:
        if not allow_tier_downgrade:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": str(exc),
                    "type": "invalid_request_error",
                    "code": "unsupported_capability",
                    "param": "model",
                    "details": {"capability": "text"},
                },
            )
        # Requested tier has no capable models at policy time — try fallback tiers now
        _tier_order = [Tier.T1, Tier.T2, Tier.T3]
        _base = user_force_tier or _floor_tier or effective_cls.tier
        _idx = _tier_order.index(_base)
        _candidates = list(reversed(_tier_order[:_idx])) + _tier_order[_idx + 1 :]
        plan = None
        for _ft in _candidates:
            try:
                plan = orchestrator.policy_engine.select(
                    effective_cls,
                    policy=policy,
                    force_tier=_ft,
                    exclude=_excluded,
                    input_tokens=estimated_tokens,
                )
                break
            except NoCapableModelError:
                continue
        if plan is None:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": str(exc),
                    "type": "invalid_request_error",
                    "code": "unsupported_capability",
                    "param": "model",
                    "details": {"capability": "text"},
                },
            )

    router_latency_ms = int((time.perf_counter() - started) * 1000)
    primary_ref = plan.chain[0]

    _state_id = getattr(_req.state, "request_id", None)
    request_id = uuid.UUID(_state_id) if _state_id else uuid.uuid4()

    if session_id:
        existing_session = get_session(db, session_id)
        if existing_session is None:
            create_session(db, {"id": session_id, "api_key_id": _database_api_key_id(_req)})
        elif existing_session.api_key_id != _database_api_key_id(_req):
            raise HTTPException(status_code=404, detail="session_id not found")

    # Phase 1: commit pending row before provider call (preserves issue-28 invariant)
    pending = create_request_log(
        db,
        {
            "id": request_id,

            "api_key_id": _database_api_key_id(_req),
            "session_id": session_id,
            "difficulty_score": effective_cls.score,
            "tier": plan.tier_effective.value,
            "policy": plan.policy_applied,
            "signals": _signals_payload(classification.signals) + _signals_payload(_session_signals),
            "classifier_version": classification.classifier_version,
            "router_cost_usd": classification.cost_usd,
            "model": primary_ref.model_id,
            "provider": primary_ref.provider,
            "chain_attempted": [
                {"model": primary_ref.model_id, "provider": primary_ref.provider, "status": "pending", "error": None}
            ],
            "latency_router_ms": router_latency_ms,
            "status": "pending",
            "fallback_count": 0,
            "stream": request.stream,
            "messages": [{"role": m.role, "content": _redact(m.content)} for m in request.messages],
        },
    )

    # AC-4: sequential fallback execution with optional tier downgrade (#130)
    # tier_requested = original intent (user_force_tier or plan.tier_effective); tier_effective = what actually ran
    tier_requested = user_force_tier or plan.tier_effective
    tier_effective = plan.tier_effective
    all_chain_attempted: list[str] = []
    provider_map = {ref.model_id: ref.provider for ref in plan.chain}
    fb_result = None

    if request.stream:
        _result_bag: dict = {}
        _cid = f"chatcmpl-{request_id.hex}"
        _created = int(time.time())

        async def _sse_generator():
            total_content = ""
            last_usage = None
            last_model = primary_ref.model_id
            last_provider = primary_ref.provider
            _first = True
            _stream_ok = False
            _finalized = False
            last_finish = None

            # Resolve cross-tier chains upfront: upgrades always, downgrades only if opted-in
            _sl = [Tier.T1, Tier.T2, Tier.T3]
            _si = _sl.index(tier_requested)
            _all_chains = [plan.chain]
            for _ft in _sl[_si + 1 :] + (list(reversed(_sl[:_si])) if allow_tier_downgrade else []):
                try:
                    _fp = orchestrator.policy_engine.select(
                        classification, policy=policy, force_tier=_ft,
                        exclude=_excluded, input_tokens=estimated_tokens,
                    )
                    provider_map.update({ref.model_id: ref.provider for ref in _fp.chain})
                    _all_chains.append(_fp.chain)
                except NoCapableModelError:
                    pass

            try:
                _last_exc: Exception | None = None
                for _chain in _all_chains:
                    _bag: dict = {}
                    try:
                        async for chunk in orchestrator.fallback_executor.execute_stream(
                            _chain, messages, params, _bag
                        ):
                            if _first:
                                _first = False
                                if ref := _bag.get("model_ref"):
                                    last_model = ref.model_id
                                    last_provider = ref.provider
                                    if ref.model_id != primary_ref.model_id:
                                        yield f"data: {json.dumps({'id': _cid, 'object': 'chat.completion.chunk', 'created': _created, 'model': ref.model_id, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': None}], 'smartroute_fallback': {'from': primary_ref.model_id, 'to': ref.model_id, 'attempted': _bag.get('chain_attempted', [])}})}\n\n"
                            if chunk.delta:
                                total_content += chunk.delta
                            if chunk.usage:
                                last_usage = chunk.usage
                            if chunk.finish_reason:
                                last_finish = chunk.finish_reason
                            # chunk.delta is None for non-content chunks (role/finish); empty string is valid content (#223)
                            delta = {"content": chunk.delta} if chunk.delta is not None else {}
                            yield f"data: {json.dumps({'id': _cid, 'object': 'chat.completion.chunk', 'created': _created, 'model': last_model, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': chunk.finish_reason}]})}\n\n"
                        _result_bag.update(_bag)
                        _stream_ok = True
                        break
                    except Exception as exc:
                        if total_content:
                            break  # partial content already sent; can't retry transparently
                        _last_exc = exc

                if not _stream_ok and not total_content and _last_exc:
                    yield f"data: {json.dumps({'error': {'message': str(_last_exc), 'type': 'provider_error'}})}\n\n"

                yield "data: [DONE]\n\n"
            finally:
                if not _finalized:
                    _finalized = True
                    _usage = last_usage or _token_estimator.estimate_usage(messages, total_content)
                    _cost = Decimal("0")
                    if orchestrator.cost_calculator:
                        try:
                            _cost = orchestrator.cost_calculator.calc(last_model, _usage)
                        except Exception:
                            pass

                    _chain = _result_bag.get("chain_attempted", [primary_ref.model_id])
                    _chain_db = [
                        {
                            "model": m,
                            "provider": provider_map.get(m, "unknown"),
                            "status": "ok" if m == last_model else "error",
                            "error": None if m == last_model else "retryable",
                        }
                        for m in _chain
                    ]
                    _routing_dict = _new_routing_state.to_dict() if _new_routing_state else None
                    _status = "ok" if _stream_ok else ("cancelled" if total_content else "error")

                    def _phase2_stream():
                        complete_request_log(
                            str(request_id),
                            {
                                "prompt_tokens": _usage.prompt_tokens,
                                "completion_tokens": _usage.completion_tokens,
                                "usage_estimated": last_usage is None,
                                "cost_usd": _cost,
                                "latency_total_ms": int((time.perf_counter() - started) * 1000),
                                "status": _status,
                                "model": last_model,
                                "provider": last_provider,
                                "fallback_count": _result_bag.get("fallback_count", 0),
                                "chain_attempted": _chain_db,
                                "response_content": _redact(total_content),
                            },
                            session_id=session_id,
                            new_routing_state=_routing_dict,
                        )
                        _observer = getattr(_req.app.state, "outcome_observer", None)
                        if _observer:
                            _observer.observe(
                                request_id,
                                session_id,
                                tier_effective.value,
                                total_content,
                                last_finish,
                                effective_cls.score,
                                _new_routing_state.turn_count if _new_routing_state else None,
                            )

                    try:
                        loop = asyncio.get_running_loop()
                        loop.run_in_executor(None, _phase2_stream)
                    except RuntimeError:
                        _phase2_stream()

        stream_headers = {
            "X-SR-Request-Id": str(request_id),
            "X-SR-Score": str(classification.score),
            "X-SR-Tier": tier_requested.value,
            "X-SR-Tier-Effective": tier_effective.value,
            "X-SR-Model": primary_ref.model_id,
            "X-SR-Provider": primary_ref.provider,
            "Cache-Control": "no-cache",
        }
        if max_tokens_clamped:
            stream_headers["X-SR-Clamped"] = "max_tokens"

        return StreamingResponse(
            _sse_generator(),
            media_type="text/event-stream",
            headers=stream_headers,
        )

    try:
        fb_result = await orchestrator.fallback_executor.execute(plan.chain, messages, params)
        all_chain_attempted = list(fb_result.chain_attempted)
    except AllProvidersFailedError as exc:
        all_chain_attempted = list(exc.chain_attempted)
        _tier_order = [Tier.T1, Tier.T2, Tier.T3]
        _idx = _tier_order.index(tier_requested)
        # Upgrades always (safe — higher tier handles any task); downgrades only if opted-in
        _candidates = _tier_order[_idx + 1 :] + (list(reversed(_tier_order[:_idx])) if allow_tier_downgrade else [])
        for fallback_tier in _candidates:
            try:
                fb_plan = orchestrator.policy_engine.select(
                    classification,
                    policy=policy,
                    force_tier=fallback_tier,
                    exclude=orchestrator.fallback_executor.circuit.open_set() | _quota_excluded,
                    input_tokens=estimated_tokens,
                )
            except NoCapableModelError:
                continue
            provider_map.update({ref.model_id: ref.provider for ref in fb_plan.chain})
            try:
                fb_result = await orchestrator.fallback_executor.execute(fb_plan.chain, messages, params)
                all_chain_attempted.extend(fb_result.chain_attempted)
                tier_effective = fallback_tier
                plan = fb_plan
                break
            except AllProvidersFailedError as fb_exc:
                all_chain_attempted.extend(fb_exc.chain_attempted)
    except ProviderError:
        background_tasks.add_task(
            complete_request_log,
            str(request_id),
            {
                "status": "error",
                "latency_total_ms": int((time.perf_counter() - started) * 1000),
            },
            session_id=session_id,
        )
        raise HTTPException(status_code=502, detail="provider_error")

    if fb_result is None:
        background_tasks.add_task(
            complete_request_log,
            str(request_id),
            {
                "status": "error",
                "error": "all_providers_failed",
                "latency_total_ms": int((time.perf_counter() - started) * 1000),
                "chain_attempted": [
                    {"model": m, "provider": provider_map.get(m, "unknown"), "status": "error", "error": "all_failed"}
                    for m in all_chain_attempted
                ],
            },
            session_id=session_id,
        )
        _rid = getattr(_req.state, "request_id", str(request_id))
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": "All providers failed.",
                    "type": "provider_error",
                    "param": None,
                    "code": "provider_error",
                    "request_id": _rid,
                    "details": {"chain_attempted": all_chain_attempted},
                }
            },
        )

    # Resolve actual model used (may differ from primary if fallback/downgrade occurred)
    last_model_id = all_chain_attempted[-1] if all_chain_attempted else primary_ref.model_id
    model_used_provider = provider_map.get(last_model_id, primary_ref.provider)

    cost = Decimal("0")
    if orchestrator.cost_calculator and fb_result.chain_attempted:
        try:
            cost = orchestrator.cost_calculator.calc(last_model_id, fb_result.result.usage)
        except Exception:
            pass

    total_latency_ms = int((time.perf_counter() - started) * 1000)

    total_fallback_count = fb_result.fallback_count + (len(all_chain_attempted) - len(fb_result.chain_attempted))

    # Build final chain_attempted for DB
    chain_db = [
        {
            "model": m,
            "provider": provider_map.get(m, "unknown"),
            "status": "ok" if m == last_model_id else "error",
            "error": None if m == last_model_id else "retryable",
        }
        for m in all_chain_attempted
    ]

    background_tasks.add_task(
        complete_request_log,
        str(request_id),
        {
            "prompt_tokens": fb_result.result.usage.prompt_tokens,
            "completion_tokens": fb_result.result.usage.completion_tokens,
            "usage_estimated": fb_result.result.usage_estimated,
            "cost_usd": cost,
            "latency_total_ms": total_latency_ms,
            "status": "ok",
            "model": last_model_id,
            "provider": model_used_provider,
            "fallback_count": total_fallback_count,
            "chain_attempted": chain_db,
            "response_content": _redact(fb_result.result.content),
        },
        session_id=session_id,
        new_routing_state=_new_routing_state.to_dict() if _new_routing_state else None,
    )

    _observer = getattr(_req.app.state, "outcome_observer", None)
    if _observer:
        background_tasks.add_task(
            _observer.observe,
            request_id,
            session_id,
            tier_effective.value,
            fb_result.result.content,
            fb_result.result.finish_reason,
            effective_cls.score,
            _new_routing_state.turn_count if _new_routing_state else None,
        )

    response.headers["X-SR-Request-Id"] = str(request_id)
    response.headers["X-SR-Score"] = str(classification.score)
    response.headers["X-SR-Tier"] = tier_requested.value
    response.headers["X-SR-Tier-Effective"] = tier_effective.value
    response.headers["X-SR-Model"] = last_model_id
    response.headers["X-SR-Provider"] = model_used_provider
    response.headers["X-SR-Cost-USD"] = str(cost.quantize(Decimal("0.000001")))
    if fb_result.result.dropped_params:
        response.headers["X-SR-Dropped-Params"] = ",".join(fb_result.result.dropped_params)
    if max_tokens_clamped:
        response.headers["X-SR-Clamped"] = "max_tokens"

    return {
        "id": f"chatcmpl-{request_id.hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": last_model_id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": fb_result.result.content},
                "finish_reason": fb_result.result.finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": fb_result.result.usage.prompt_tokens,
            "completion_tokens": fb_result.result.usage.completion_tokens,
            "total_tokens": fb_result.result.usage.prompt_tokens + fb_result.result.usage.completion_tokens,
        },
        "smartroute": {
            **_meta(pending),
            "tier_effective": tier_effective.value,
            "tier_changed": tier_effective != tier_requested,
        },
    }


@router.get("/models", tags=["models"], response_model=ModelListResponse)
async def list_models(request: Request):
    snapshot = await request.app.state.provider_registry.snapshot()
    models = [
        ModelResponse(
            id=model.id,
            object="model",
            provider=model.provider,
            default_tier=model.default_tier,
            capabilities=list(model.capabilities),
            enabled=model.enabled,
        )
        for model in snapshot.models
    ]
    return ModelListResponse(object="list", data=models)


@router.get("/usage/{request_id}", tags=["usage"], response_model=UsageResponse)
async def get_usage(request_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    log = get_request_log(db, str(request_id))
    if log is None:
        raise HTTPException(status_code=404, detail="request_id not found")
    status = "pending" if log.status == "pending" else "complete"
    meta = _meta(log)
    cfg = getattr(request.app.state, "config", None) or load_config()
    pv = _pricing_version(cfg)
    cv = _active_config_version(cfg)
    unit_prices, in_price, out_price = _get_model_unit_prices(cfg, log.model)
    cost = float(log.cost_usd) if log.cost_usd is not None else None
    return {
        "status": status,
        "smartroute": meta,
        "cost_usd": cost,
        "pricing_version": pv,
        "config_version": cv,
        "unit_prices": unit_prices,
        "input_price": in_price,
        "output_price": out_price,
    }
