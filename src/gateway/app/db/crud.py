import json
import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.gateway.app.db.models import APIKey, ConfigSetting, Feedback, RequestLog, SessionFeedback
from src.gateway.app.db.models import Session as SessionModel


def get_api_key_by_hash(db: Session, key_hash: str):
    return db.query(APIKey).filter(APIKey.key_hash == key_hash, APIKey.active).first()


def list_api_keys(db: Session):
    return db.query(APIKey).order_by(APIKey.id).all()


def get_api_key_by_name(db: Session, name: str):
    return db.query(APIKey).filter(func.lower(APIKey.name) == name.lower()).first()


def count_requests_by_api_key(db: Session) -> dict[int, int]:
    rows = db.query(RequestLog.api_key_id, func.count(RequestLog.id)).group_by(RequestLog.api_key_id).all()
    return {api_key_id: count for api_key_id, count in rows if api_key_id is not None}


def create_api_key(db: Session, *, name: str, key_hash: str, key_masked: str, rate_limit: int):
    api_key = APIKey(name=name, key_hash=key_hash, key_masked=key_masked, rate_limit=rate_limit)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key


def revoke_api_key(db: Session, key_id: int):
    api_key = db.query(APIKey).filter(APIKey.id == key_id).first()
    if api_key is None:
        return None
    api_key.active = False
    db.commit()
    db.refresh(api_key)
    return api_key


def create_request_log(db: Session, log_data: dict):
    db_log = RequestLog(**log_data)
    db.add(db_log)
    db.commit()
    db.refresh(db_log)
    return db_log


def get_request_log(db: Session, request_id: str | uuid.UUID):
    try:
        request_uuid = request_id if isinstance(request_id, uuid.UUID) else uuid.UUID(str(request_id))
    except (ValueError, TypeError):
        return None
    return db.query(RequestLog).filter(RequestLog.id == request_uuid).first()


def list_request_logs(db: Session, date_from: datetime | None = None, date_to: datetime | None = None):
    query = db.query(RequestLog)
    if date_from is not None:
        query = query.filter(RequestLog.ts >= date_from)
    if date_to is not None:
        query = query.filter(RequestLog.ts < date_to)
    return query.all()


def list_recent_request_logs(
    db: Session,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
):
    query = db.query(RequestLog)
    if date_from is not None:
        query = query.filter(RequestLog.ts >= date_from)
    if date_to is not None:
        query = query.filter(RequestLog.ts < date_to)
    return query.order_by(RequestLog.ts.desc()).limit(limit).all()


def query_admin_requests(
    db: Session,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    tier: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    min_fallback: int | None = None,
    query_str: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[RequestLog], int]:
    from sqlalchemy import String, cast
    query = db.query(RequestLog)
    if date_from is not None:
        query = query.filter(RequestLog.ts >= date_from)
    if date_to is not None:
        query = query.filter(RequestLog.ts < date_to)
    if tier:
        query = query.filter(RequestLog.tier == tier)
    if provider:
        query = query.filter(RequestLog.provider == provider)
    if status:
        query = query.filter(RequestLog.status == status)
    if min_fallback is not None:
        query = query.filter(RequestLog.fallback_count >= min_fallback)
    if query_str:
        q_cleaned = query_str.strip()
        try:
            val_uuid = uuid.UUID(q_cleaned)
            query = query.filter(RequestLog.id == val_uuid)
        except (ValueError, TypeError):
            query = query.filter(cast(RequestLog.id, String).ilike(f"%{q_cleaned}%"))

    total = query.count()
    offset = max(0, (page - 1) * page_size)
    items = query.order_by(RequestLog.ts.desc()).offset(offset).limit(page_size).all()
    return items, total


def sum_tokens_by_model(
    db: Session,
    day_start: datetime,
    day_end: datetime,
    models: list[str],
) -> dict[str, int]:
    """Tổng prompt_tokens + completion_tokens theo model trong [day_start, day_end)."""
    rows = (
        db.query(
            RequestLog.model,
            func.coalesce(func.sum(RequestLog.prompt_tokens), 0)
            + func.coalesce(func.sum(RequestLog.completion_tokens), 0),
        )
        .filter(
            RequestLog.ts >= day_start,
            RequestLog.ts < day_end,
            RequestLog.model.in_(models),
            RequestLog.status == "ok",
        )
        .group_by(RequestLog.model)
        .all()
    )
    return {model: int(total) for model, total in rows}


def sum_tokens_by_api_key(
    db: Session,
    api_key_id: int,
    day_start: datetime,
    day_end: datetime,
) -> int:
    """Tổng prompt_tokens + completion_tokens của MỘT api_key trong [day_start, day_end).

    Dùng index ix_requests_api_key_id_ts. Đếm mọi row (kể cả error) — token đã tiêu là đã tiêu;
    row pending chưa có token nên coalesce về 0, không sai lệch.
    """
    total = (
        db.query(
            func.coalesce(func.sum(RequestLog.prompt_tokens), 0)
            + func.coalesce(func.sum(RequestLog.completion_tokens), 0)
        )
        .filter(
            RequestLog.api_key_id == api_key_id,
            RequestLog.ts >= day_start,
            RequestLog.ts < day_end,
        )
        .scalar()
    )
    return int(total or 0)


def update_request_log(db: Session, request_id: str | uuid.UUID, update_data: dict):
    db_log = get_request_log(db, request_id)
    if db_log:
        for key, value in update_data.items():
            setattr(db_log, key, value)
        db.commit()
        db.refresh(db_log)
    return db_log


def create_feedback(db: Session, feedback_data: dict):
    db_feedback = Feedback(**feedback_data)
    try:
        db.add(db_feedback)
        db.commit()
        db.refresh(db_feedback)
    except Exception:
        db.rollback()
        raise
    return db_feedback


def create_session(db: Session, session_data: dict):
    db_session = SessionModel(**session_data)
    db.add(db_session)
    db.commit()
    db.refresh(db_session)
    return db_session


def get_session(db: Session, session_id: str | uuid.UUID):
    session_uuid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
    return db.query(SessionModel).filter(SessionModel.id == session_uuid).first()


def update_session_activity(db: Session, session_id: str | uuid.UUID):
    db_session = get_session(db, session_id)
    if db_session:
        db_session.last_activity_at = datetime.utcnow()
        db.commit()
    return db_session


def get_routing_state(db: Session, session_id: str | uuid.UUID) -> tuple[dict | None, datetime | None]:
    """Returns (routing_state dict, last_activity_at) for TTL check."""
    db_session = get_session(db, session_id)
    if db_session is None:
        return None, None
    return db_session.routing_state, db_session.last_activity_at


def update_routing_state(
    db: Session, session_id: str | uuid.UUID, new_state: dict, *, allow_same_turn: bool = False
) -> bool:
    """Optimistic guard: only writes if turn_count is newer (§4.1).

    `allow_same_turn` is for OutcomeObserver, which annotates the *current* turn and
    has already done its own CAS in `patch_routing_state` — without it the write is
    silently dropped by the monotonic guard.
    """
    from sqlalchemy import text as sql_text

    session_uuid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
    new_turn = new_state.get("turn_count", 0)
    cmp = "<=" if allow_same_turn else "<"
    result = db.execute(
        sql_text(
            "UPDATE sessions SET routing_state = :new_state, last_activity_at = :now "
            "WHERE id = :sid "
            f"AND (routing_state IS NULL OR COALESCE(CAST(routing_state->>'turn_count' AS INTEGER), -1) {cmp} :tc)"
        ),
        {"new_state": json.dumps(new_state), "now": datetime.utcnow(), "sid": session_uuid, "tc": new_turn},
    )
    db.commit()
    return result.rowcount > 0


def create_session_feedback(db: Session, feedback_data: dict):
    db_feedback = SessionFeedback(**feedback_data)
    try:
        db.add(db_feedback)
        db.commit()
        db.refresh(db_feedback)
    except Exception:
        db.rollback()
        raise
    return db_feedback


def patch_routing_state(
    db: Session,
    session_id: str | uuid.UUID,
    expected_turn_count: int,
    mutator,
) -> bool:
    """OutcomeObserver-safe state mutation (§9): only applies when turn_count
    still equals expected — a newer router write always wins."""
    state_dict, _ = get_routing_state(db, session_id)
    if not state_dict:
        return False
    if state_dict.get("turn_count", 0) != expected_turn_count:
        return False
    mutator(state_dict)
    return update_routing_state(db, session_id, state_dict, allow_same_turn=True)


def set_request_outcome(db: Session, request_id: str | uuid.UUID, evidence: dict):
    db_log = get_request_log(db, request_id)
    if db_log is None:
        return None
    db_log.outcome_evidence = evidence
    db.commit()
    db.refresh(db_log)
    return db_log


def router_cost_ratio_since(db: Session, since: datetime) -> float | None:
    """Σ router_cost / Σ total cost over completed requests since `since` (§9.1)."""
    total_cost = (
        db.query(func.sum(RequestLog.cost_usd))
        .filter(RequestLog.ts >= since, RequestLog.status == "ok")
        .scalar()
    )
    if not total_cost or float(total_cost) <= 0:
        return None
    router_cost = (
        db.query(func.sum(RequestLog.router_cost_usd))
        .filter(RequestLog.ts >= since, RequestLog.status == "ok")
        .scalar()
    )
    if not router_cost:
        return 0.0
    return float(router_cost) / float(total_cost) * 100


def get_config(db: Session, key: str):
    return db.query(ConfigSetting).filter(ConfigSetting.key == key).first()


def set_config(db: Session, key: str, value: dict):
    db_config = db.query(ConfigSetting).filter(ConfigSetting.key == key).first()
    if db_config:
        db_config.value = value
    else:
        db_config = ConfigSetting(key=key, value=value)
        db.add(db_config)
    db.commit()
    db.refresh(db_config)
    return db_config


def list_sessions(db: Session, limit: int = 50, offset: int = 0, owner_api_key_id: int | None = ...) -> list[SessionModel]:
    q = db.query(SessionModel).filter(SessionModel.requests.any())
    if owner_api_key_id is not ...:
        q = q.filter(SessionModel.api_key_id == owner_api_key_id)
    return q.order_by(SessionModel.last_activity_at.desc()).offset(offset).limit(limit).all()


def count_sessions(db: Session, owner_api_key_id: int | None = ...) -> int:
    q = db.query(func.count(SessionModel.id)).filter(SessionModel.requests.any())
    if owner_api_key_id is not ...:
        q = q.filter(SessionModel.api_key_id == owner_api_key_id)
    return q.scalar() or 0



def get_session_requests(db: Session, session_id: str | uuid.UUID) -> list[RequestLog]:
    session_uuid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
    return (
        db.query(RequestLog)
        .filter(RequestLog.session_id == session_uuid)
        .order_by(RequestLog.ts.asc())
        .all()
    )
