import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.gateway.app.api.feedback import _evidence_name
from src.gateway.app.db.crud import (
    count_sessions,
    create_session_feedback,
    get_session,
    get_session_requests,
    list_sessions,
)
from src.gateway.app.db.session import get_db

router = APIRouter()

SESSION_FEEDBACK_TAGS = [
    "Routing tốt, tiết kiệm chi phí",
    "Routing không nhất quán",
    "Nên dùng model mạnh hơn",
    "Nên dùng model nhỏ hơn",
    "Khác",
]

SESSION_NEGATIVE_TAGS = frozenset({"Nên dùng model mạnh hơn"})
SESSION_POSITIVE_TAGS = frozenset({"Routing tốt, tiết kiệm chi phí", "Nên dùng model nhỏ hơn"})


def _owner_key_id(request: Request) -> int | None:
    raw = getattr(request.state, "api_key_id", None)
    return raw if isinstance(raw, int) else None


class SessionListItem(BaseModel):
    session_id: str
    title: str | None = None
    started_at: str | None = None
    last_activity_at: str | None = None
    total_requests: int = 0
    last_model: str | None = None
    last_tier: str | None = None


class SessionListResponse(BaseModel):
    items: list[SessionListItem]
    total: int


class TurnFeedbackInfo(BaseModel):
    tags: list[str] = Field(default_factory=list)
    note: str | None = None
    ts: str | None = None


class TurnHistoryItem(BaseModel):
    request_id: str
    ts: str | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)
    response_content: str | None = None
    model: str | None = None
    provider: str | None = None
    tier: str | None = None
    difficulty_score: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    latency_total_ms: int | None = None
    status: str | None = None
    feedback: TurnFeedbackInfo | None = None


class SessionFeedbackInfo(BaseModel):
    tags: list[str] = Field(default_factory=list)
    note: str | None = None
    ts: str | None = None


class SessionDetailResponse(BaseModel):
    session_id: str
    title: str | None = None
    started_at: str | None = None
    last_activity_at: str | None = None
    routing_state: dict[str, Any] | None = None
    feedback: SessionFeedbackInfo | None = None
    turns: list[TurnHistoryItem] = Field(default_factory=list)


@router.get("/sessions", tags=["sessions"], response_model=SessionListResponse)
async def list_all_sessions(
    _req: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    owner = _owner_key_id(_req)
    sessions = list_sessions(db, limit=limit, offset=offset, owner_api_key_id=owner)
    total = count_sessions(db, owner_api_key_id=owner)
    items = []
    for s in sessions:
        reqs = s.requests
        first_req = min(reqs, key=lambda r: r.ts) if reqs else None
        last_req = max(reqs, key=lambda r: r.ts) if reqs else None
        title = None
        if first_req and first_req.messages:
            for m in first_req.messages:
                if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                    title = m.get("content").strip()
                    break
        items.append(
            SessionListItem(
                session_id=str(s.id),
                title=title,
                started_at=s.started_at.isoformat() + "Z" if s.started_at else None,
                last_activity_at=s.last_activity_at.isoformat() + "Z" if s.last_activity_at else None,
                total_requests=len(reqs),
                last_model=last_req.model if last_req else None,
                last_tier=last_req.tier if last_req else None,
            )
        )
    return SessionListResponse(items=items, total=total)


@router.get("/sessions/{session_id}", tags=["sessions"], response_model=SessionDetailResponse)
async def get_session_detail(session_id: uuid.UUID, _req: Request, db: Session = Depends(get_db)):
    session = get_session(db, session_id)
    # Return 404 for missing OR unauthorized sessions (prevents object enumeration — #220)
    if session is None or session.api_key_id != _owner_key_id(_req):
        raise HTTPException(status_code=404, detail="session_id not found")

    session_fb = None
    if session.feedback:
        session_fb = SessionFeedbackInfo(
            tags=session.feedback.tags or [],
            note=session.feedback.note,
            ts=session.feedback.ts.isoformat() + "Z" if session.feedback.ts else None,
        )

    requests = get_session_requests(db, session_id)
    turn_items = []
    for req in requests:
        fb_info = None
        if req.feedback:
            fb_info = TurnFeedbackInfo(
                tags=req.feedback.tags or [],
                note=req.feedback.note,
                ts=req.feedback.ts.isoformat() + "Z" if req.feedback.ts else None,
            )
        turn_items.append(
            TurnHistoryItem(
                request_id=str(req.id),
                ts=req.ts.isoformat() + "Z" if req.ts else None,
                messages=req.messages or [],
                response_content=req.response_content,
                model=req.model,
                provider=req.provider,
                tier=req.tier,
                difficulty_score=req.difficulty_score,
                prompt_tokens=req.prompt_tokens,
                completion_tokens=req.completion_tokens,
                cost_usd=float(req.cost_usd) if req.cost_usd is not None else None,
                latency_total_ms=req.latency_total_ms,
                status=req.status,
                feedback=fb_info,
            )
        )

    title = None
    if requests and requests[0].messages:
        for m in requests[0].messages:
            if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
                title = m.get("content").strip()
                break

    return SessionDetailResponse(
        session_id=str(session.id),
        title=title,
        started_at=session.started_at.isoformat() + "Z" if session.started_at else None,
        last_activity_at=session.last_activity_at.isoformat() + "Z" if session.last_activity_at else None,
        routing_state=session.routing_state,
        feedback=session_fb,
        turns=turn_items,
    )


@router.post("/sessions", tags=["sessions"], status_code=status.HTTP_201_CREATED)
async def create_new_session():
    from datetime import datetime
    new_id = uuid.uuid4()
    return {"session_id": str(new_id), "started_at": datetime.utcnow().isoformat() + "Z"}


class SessionFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: uuid.UUID
    tags: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=500)


@router.post("/session-feedback", tags=["sessions"], status_code=status.HTTP_201_CREATED)
async def submit_session_feedback(
    feedback: SessionFeedbackRequest, _req: Request, db: Session = Depends(get_db)
):
    if not feedback.tags and not feedback.note.strip():
        raise HTTPException(status_code=422, detail="tags or note required")
    session = get_session(db, feedback.session_id)
    # 404 on missing OR unauthorized session to prevent enumeration (#220)
    if session is None or session.api_key_id != _owner_key_id(_req):
        raise HTTPException(status_code=404, detail="session_id not found")
    try:
        create_session_feedback(
            db,
            {
                "session_id": feedback.session_id,
                "tags": feedback.tags or None,
                "note": feedback.note.strip() or None,
            },
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="feedback already exists for session_id") from exc

    observer = getattr(_req.app.state, "outcome_observer", None)
    name = _evidence_name(feedback.tags, SESSION_NEGATIVE_TAGS, SESSION_POSITIVE_TAGS)
    if observer and name:
        observer.record(feedback.session_id, name, f"tags={feedback.tags}")
    return {"ok": True}
