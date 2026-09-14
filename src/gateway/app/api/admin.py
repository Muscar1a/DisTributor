import dataclasses
import hashlib
import json
import re
import secrets
import string
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.gateway.app.config.loader import load_config
from src.gateway.app.db.crud import (
    count_requests_by_api_key,
    create_api_key,
    get_api_key_by_name,
    get_request_log,
    list_api_keys,
    list_recent_request_logs,
    list_request_logs,
    query_admin_requests,
    revoke_api_key,
    sum_tokens_by_model,
)
from src.gateway.app.db.crud import (
    set_config as db_set_config,
)
from src.gateway.app.db.session import get_db

_QUOTA_FILE = Path(__file__).resolve().parent.parent / "config" / "quota.yaml"


@lru_cache(maxsize=1)
def _load_quota():
    return yaml.safe_load(_QUOTA_FILE.read_text(encoding="utf-8"))["openai_quotas"]


router = APIRouter()
KEY_ALPHABET = string.ascii_letters + string.digits
MAX_API_KEY_RPM = 1_000

# #221: redact secret-like values before serving admin previews
_SECRET_RE = re.compile(
    r"(?:"
    r"sk-[A-Za-z0-9\-_]{20,}"
    r"|AIza[0-9A-Za-z\-_]{35}"
    r"|sr-[A-Za-z0-9]{20,}"
    r"|[Bb]earer\s+[A-Za-z0-9._\-]{10,}"
    r"|(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*\S{6,}"
    r")",
    re.IGNORECASE,
)


def _redact(text: str | None) -> str | None:
    if text is None:
        return None
    return _SECRET_RE.sub("[REDACTED]", text)


def _config_version(cfg_dict: dict) -> str:
    return hashlib.sha256(json.dumps(cfg_dict, sort_keys=True).encode()).hexdigest()[:16]


class APIKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    rate_limit_per_min: int = Field(default=60, ge=1, le=MAX_API_KEY_RPM)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value):
        """Trim names before length validation so whitespace-only values fail."""
        return value.strip() if isinstance(value, str) else value


def key_item(api_key, total_requests: int = 0):
    return {
        "id": api_key.id,
        "name": api_key.name,
        "key_masked": api_key.key_masked,
        "rate_limit_per_min": api_key.rate_limit,
        "created_at": api_key.created_at,
        "active": api_key.active,
        "total_requests": total_requests,
    }


@router.get("/keys", tags=["admin"])
def get_keys(db: Session = Depends(get_db)):
    request_counts = count_requests_by_api_key(db)
    return {
        "items": [
            key_item(api_key, request_counts.get(api_key.id, 0))
            for api_key in list_api_keys(db)
        ]
    }


def _duplicate_key_name_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "message": "An API key with this name already exists.",
            "type": "invalid_request_error",
            "code": "duplicate_api_key_name",
            "details": {"field": "name"},
        },
    )


@router.post("/keys", status_code=status.HTTP_201_CREATED, tags=["admin"])
def post_key(payload: APIKeyCreate, db: Session = Depends(get_db)):
    if get_api_key_by_name(db, payload.name) is not None:
        raise _duplicate_key_name_error()

    raw_key = "sr-" + "".join(secrets.choice(KEY_ALPHABET) for _ in range(32))
    try:
        api_key = create_api_key(
            db,
            name=payload.name,
            key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
            key_masked="sr-" + "*" * 4 + raw_key[-4:],
            rate_limit=payload.rate_limit_per_min,
        )
    except IntegrityError as exc:
        db.rollback()
        # The database constraint closes the race between the lookup above and
        # insert, so concurrent requests receive the same stable field error.
        if get_api_key_by_name(db, payload.name) is not None:
            raise _duplicate_key_name_error() from exc
        raise
    return {**key_item(api_key), "key": raw_key}


@router.delete("/keys/{key_id}", tags=["admin"])
def delete_key(key_id: int, db: Session = Depends(get_db)):
    if revoke_api_key(db, key_id) is None:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"ok": True}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _normalize_time_range(
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime | None, datetime | None]:
    """Normalize a [from, to) range to naive UTC and reject reversed bounds."""
    date_from, date_to = _as_utc(date_from), _as_utc(date_to)
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "message": "The 'from' timestamp must be before or equal to 'to'.",
                "type": "invalid_request_error",
                "code": "invalid_time_range",
                "details": {"fields": ["from", "to"], "from_inclusive": True, "to_exclusive": True},
            },
        )
    return date_from, date_to


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.000001")))


@router.get("/stats", tags=["admin"])
async def get_stats(
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    date_from, date_to = _normalize_time_range(date_from, date_to)
    rows = list_request_logs(db, date_from, date_to)
    config = load_config()
    baseline = config.pricing[config.premium_baseline_model]
    completed = [row for row in rows if row.status == "ok"]

    actual_cost = sum((Decimal(row.cost_usd or 0) for row in completed), Decimal(0))
    baseline_cost = sum(
        (
            (
                Decimal(row.prompt_tokens or 0) * Decimal(str(baseline.input_per_1m_usd))
                + Decimal(row.completion_tokens or 0) * Decimal(str(baseline.output_per_1m_usd))
            )
            / Decimal(1_000_000)
            for row in completed
        ),
        Decimal(0),
    )
    # §9.1: savings tính NET — chi phí của chính router cũng là chi phí
    router_cost = sum((Decimal(row.router_cost_usd or 0) for row in completed), Decimal(0))
    net_cost = actual_cost + router_cost
    savings_pct = ((baseline_cost - net_cost) / baseline_cost * 100) if baseline_cost > 0 else Decimal(0)
    latencies = [row.latency_total_ms for row in completed if row.latency_total_ms is not None]
    router_latencies = [row.latency_router_ms for row in completed if row.latency_router_ms is not None]

    by_tier = defaultdict(lambda: {"requests": 0, "cost": Decimal(0)})
    by_provider = defaultdict(lambda: {"requests": 0, "cost": Decimal(0)})
    tokens_by_model = defaultdict(lambda: {"prompt": 0, "completion": 0})
    series = defaultdict(lambda: {"requests": 0, "cost": Decimal(0), "baseline": Decimal(0)})
    for row in rows:
        if row.tier:
            by_tier[row.tier]["requests"] += 1
        if row.provider:
            by_provider[row.provider]["requests"] += 1
        day = row.ts.date().isoformat()
        series[day]["requests"] += 1

        if row.status != "ok":
            continue
        cost = Decimal(row.cost_usd or 0)
        row_baseline = (
            Decimal(row.prompt_tokens or 0) * Decimal(str(baseline.input_per_1m_usd))
            + Decimal(row.completion_tokens or 0) * Decimal(str(baseline.output_per_1m_usd))
        ) / Decimal(1_000_000)
        if row.tier:
            by_tier[row.tier]["cost"] += cost
        if row.provider:
            by_provider[row.provider]["cost"] += cost
        if row.model:
            tokens_by_model[row.model]["prompt"] += row.prompt_tokens or 0
            tokens_by_model[row.model]["completion"] += row.completion_tokens or 0
        series[day]["cost"] += cost
        series[day]["baseline"] += row_baseline

    success_rate = len(completed) / len(rows) if rows else 0.0
    total_tokens = sum(t["prompt"] + t["completion"] for t in tokens_by_model.values())
    return {
        "from": date_from.isoformat() + "Z" if date_from else None,
        "to": date_to.isoformat() + "Z" if date_to else None,
        "baseline_model": config.premium_baseline_model,
        "totals": {
            "requests": len(rows),
            "cost_usd": _money(actual_cost),
            "router_cost_usd": _money(router_cost),
            "net_cost_usd": _money(net_cost),
            "baseline_premium_cost_usd": _money(baseline_cost),
            "savings_pct": round(float(savings_pct), 2),
            "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
            "avg_router_latency_ms": round(sum(router_latencies) / len(router_latencies)) if router_latencies else 0,
            "success_rate": round(success_rate, 6),
            "total_tokens": total_tokens,
        },
        "by_tier": [
            {"tier": key, "requests": value["requests"], "cost_usd": _money(value["cost"])}
            for key, value in sorted(by_tier.items())
        ],
        "by_provider": [
            {"provider": key, "requests": value["requests"], "cost_usd": _money(value["cost"])}
            for key, value in sorted(by_provider.items())
        ],
        "tokens_by_model": [
            {
                "model": key,
                "prompt_tokens": value["prompt"],
                "completion_tokens": value["completion"],
                "total_tokens": value["prompt"] + value["completion"],
            }
            for key, value in sorted(tokens_by_model.items())
        ],
        "series": [
            {
                "date": key,
                "requests": value["requests"],
                "cost_usd": _money(value["cost"]),
                "baseline_premium_cost_usd": _money(value["baseline"]),
            }
            for key, value in sorted(series.items())
        ],
    }


def _format_request_item(row) -> dict:
    return {
        "id": str(row.id),
        "ts": row.ts.isoformat() + "Z" if row.ts else None,
        "api_key_name": row.api_key.name if getattr(row, "api_key", None) else None,
        "difficulty_score": row.difficulty_score,
        "tier": row.tier,
        "policy": row.policy,
        "model": row.model,
        "provider": row.provider,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cost_usd": _money(Decimal(row.cost_usd or 0)) if row.cost_usd is not None else None,
        "latency_total_ms": row.latency_total_ms,
        "latency_router_ms": row.latency_router_ms,
        "fallback_count": row.fallback_count or 0,
        "status": row.status,
        "stream": bool(row.stream),
    }


def _format_request_detail(row) -> dict:
    item = _format_request_item(row)

    prompt_prev = None
    if row.messages:
        try:
            if isinstance(row.messages, list):
                user_msgs = [
                    m.get("content", "")
                    for m in row.messages
                    if isinstance(m, dict) and m.get("role") == "user"
                ]
                if user_msgs:
                    prompt_prev = _redact(str(user_msgs[-1])[:500])
                else:
                    prompt_prev = _redact(str(row.messages)[:500])
            else:
                prompt_prev = _redact(str(row.messages)[:500])
        except Exception:
            prompt_prev = _redact(str(row.messages)[:500])

    resp_prev = _redact(str(row.response_content)[:500]) if row.response_content is not None else None

    fb_obj = None
    if getattr(row, "feedback", None) and row.feedback:
        fb_obj = {
            "tags": row.feedback.tags or [],
            "note": row.feedback.note,
            "ts": row.feedback.ts.isoformat() + "Z" if row.feedback.ts else None,
        }

    item.update(
        {
            "session_id": str(row.session_id) if row.session_id else None,
            "signals": row.signals or [],
            "chain_attempted": row.chain_attempted or [],
            "classifier_version": row.classifier_version,
            "router_cost_usd": _money(Decimal(row.router_cost_usd or 0)) if row.router_cost_usd is not None else None,
            "usage_estimated": bool(row.usage_estimated),
            "outcome_evidence": row.outcome_evidence,
            "error": _redact(row.error),
            "prompt_preview": prompt_prev,
            "response_preview": resp_prev,
            "feedback": fb_obj,
        }
    )
    return item


@router.get("/requests", tags=["admin"])
def get_admin_requests(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    tier: str | None = Query(default=None),
    provider: str | None = Query(default=None),
    status: str | None = Query(default=None),
    min_fallback: int | None = Query(default=None, ge=0),
    q: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    date_from, date_to = _normalize_time_range(date_from, date_to)
    rows, total = query_admin_requests(
        db,
        date_from=date_from,
        date_to=date_to,
        tier=tier,
        provider=provider,
        status=status,
        min_fallback=min_fallback,
        query_str=q,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_format_request_item(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/requests/{request_id}", tags=["admin"])
def get_admin_request_by_id(
    request_id: str,
    db: Session = Depends(get_db),
):
    row = get_request_log(db, request_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Request log not found",
        )
    return _format_request_detail(row)


@router.get("/logs", tags=["admin"])
def get_request_logs(
    date_from: datetime | None = Query(default=None, alias="from"),
    date_to: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    date_from, date_to = _normalize_time_range(date_from, date_to)
    rows = list_recent_request_logs(db, date_from, date_to, limit)
    return {
        "items": [
            {
                "request_id": str(row.id),
                "ts": row.ts.isoformat() + "Z" if row.ts else None,
                "tier": row.tier,
                "model": row.model,
                "provider": row.provider,
                "cost_usd": _money(Decimal(row.cost_usd or 0)) if row.cost_usd is not None else None,
                "latency_total_ms": row.latency_total_ms,
                "status": row.status,
            }
            for row in rows
        ]
    }


@router.get("/usage/quota", tags=["admin"])
def get_quota_usage(
    date_param: str | None = Query(default=None, alias="date"),
    db: Session = Depends(get_db),
):
    if date_param is not None:
        try:
            target_date = date.fromisoformat(date_param)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "date phải có định dạng YYYY-MM-DD",
                    "type": "invalid_request_error",
                    "code": "invalid_param",
                },
            )
    else:
        target_date = datetime.now(UTC).date()

    day_start = datetime(target_date.year, target_date.month, target_date.day)
    day_end = day_start + timedelta(days=1)

    quotas = _load_quota()
    all_models = [m for q in quotas for m in q["models"]]
    usage_map = sum_tokens_by_model(db, day_start, day_end, all_models)

    result = []
    for q in quotas:
        used = sum(usage_map.get(m, 0) for m in q["models"])
        limit = q["limit_tokens"]
        result.append(
            {
                "group": q["group"],
                "limit_tokens": limit,
                "used_tokens": used,
                "remaining_tokens": max(0, limit - used),
                "used_pct": round(used / limit * 100, 2) if limit else 0,
                "models": q["models"],
                "breakdown": {m: usage_map[m] for m in q["models"] if usage_map.get(m, 0) > 0},
            }
        )

    return {"date": target_date.isoformat(), "quotas": result}


class PolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tier_shift: int | None = None
    order_by: str | None = None


class ConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_policy: str | None = None
    t1_max: int | None = None
    t2_max: int | None = None
    policies: dict[str, PolicyPatch] | None = None


@router.get("/config", tags=["admin"])
async def get_config(request: Request):
    cfg = request.app.state.config
    body = {
        "default_policy": cfg.default_policy,
        "t1_max": cfg.t1_max,
        "t2_max": cfg.t2_max,
        "policies": {
            name: {"tier_shift": rule.tier_shift, "order_by": rule.order_by}
            for name, rule in cfg.policies.items()
        },
    }
    body["config_version"] = _config_version(body)
    return body


@router.put("/config", tags=["admin"])
async def update_config(patch: ConfigPatch, request: Request, db: Session = Depends(get_db)):
    cfg = request.app.state.config
    new_policy = patch.default_policy if patch.default_policy is not None else cfg.default_policy
    new_t1 = patch.t1_max if patch.t1_max is not None else cfg.t1_max
    new_t2 = patch.t2_max if patch.t2_max is not None else cfg.t2_max

    new_policies = cfg.policies
    if patch.policies:
        updated_policies = dict(cfg.policies)
        from src.gateway.app.config.loader import Config, PolicyRule
        for pname, prule in patch.policies.items():
            if pname in updated_policies:
                cur = updated_policies[pname]
                new_shift = prule.tier_shift if prule.tier_shift is not None else cur.tier_shift
                new_order = prule.order_by if prule.order_by is not None else cur.order_by
                if new_order not in Config.ORDER_BY_VALUES:
                    raise HTTPException(status_code=422, detail=f"order_by '{new_order}' không hợp lệ")
                updated_policies[pname] = PolicyRule(tier_shift=new_shift, order_by=new_order)
        new_policies = updated_policies

    if new_policy not in new_policies:
        raise HTTPException(status_code=422, detail=f"default_policy '{new_policy}' không tồn tại trong policies")
    if not (0 < new_t1 < new_t2 <= 100):
        raise HTTPException(status_code=422, detail=f"Phải thoả 0 < t1_max({new_t1}) < t2_max({new_t2}) <= 100")

    new_cfg = dataclasses.replace(cfg, default_policy=new_policy, t1_max=new_t1, t2_max=new_t2, policies=new_policies)
    request.app.state.config = new_cfg
    request.app.state.orchestrator.policy_engine.config = new_cfg
    request.app.state.session_router.t1_max = new_t1
    request.app.state.session_router.t2_max = new_t2

    db_set_config(
        db,
        "routing_overrides",
        {
            "default_policy": new_policy,
            "t1_max": new_t1,
            "t2_max": new_t2,
            "policies": {k: {"tier_shift": v.tier_shift, "order_by": v.order_by} for k, v in new_policies.items()},
        },
    )

    new_body = {
        "default_policy": new_policy,
        "t1_max": new_t1,
        "t2_max": new_t2,
        "policies": {k: {"tier_shift": v.tier_shift, "order_by": v.order_by} for k, v in new_policies.items()},
    }
    return {"ok": True, "applied_at": datetime.now(UTC).isoformat(), "config_version": _config_version(new_body)}
