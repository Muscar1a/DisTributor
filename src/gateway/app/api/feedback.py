import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.gateway.app.db.crud import create_feedback, get_request_log
from src.gateway.app.db.session import get_db

router = APIRouter()

FEEDBACK_TAGS = [
    "Nên dùng model mạnh hơn",
    "Nên dùng model nhỏ hơn",
    "Chất lượng kém",
    "Chậm",
    "Khác",
]

# §6.1d — feedback là nguồn evidence ngoài của OutcomeObserver.
# "Nên dùng model nhỏ hơn" = over-routing, tức câu trả lời không hỏng → clear failure flag.
NEGATIVE_TAGS = frozenset({"Chất lượng kém", "Nên dùng model mạnh hơn"})
POSITIVE_TAGS = frozenset({"Nên dùng model nhỏ hơn"})


def _evidence_name(tags: list[str], negative: frozenset, positive: frozenset) -> str | None:
    if set(tags) & negative:
        return "feedback_negative"
    if set(tags) & positive:
        return "feedback_positive"
    return None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: uuid.UUID
    tags: list[str] = Field(default_factory=list)
    note: str = Field(default="", max_length=500)


def _owner_key_id(request: Request) -> int | None:
    raw = getattr(request.state, "api_key_id", None)
    return raw if isinstance(raw, int) else None


@router.post("/feedback", tags=["feedback"], status_code=status.HTTP_201_CREATED)
async def submit_feedback(feedback: FeedbackRequest, _req: Request, db: Session = Depends(get_db)):
    if not feedback.tags and not feedback.note.strip():
        raise HTTPException(status_code=422, detail="tags or note required")
    log = get_request_log(db, feedback.request_id)
    # 404 on missing OR unauthorized request — prevents object enumeration (#220)
    if log is None or log.api_key_id != _owner_key_id(_req):
        raise HTTPException(status_code=404, detail="request_id not found")
    try:
        create_feedback(
            db,
            {
                "request_id": feedback.request_id,
                "tags": feedback.tags or None,
                "note": feedback.note.strip() or None,
            },
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="feedback already exists for request_id") from exc

    observer = getattr(_req.app.state, "outcome_observer", None)
    name = _evidence_name(feedback.tags, NEGATIVE_TAGS, POSITIVE_TAGS)
    if observer and log.session_id and name:
        observer.record(log.session_id, name, f"tags={feedback.tags}", log.tier)
    return {"ok": True}
