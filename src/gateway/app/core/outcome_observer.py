"""OutcomeObserver — background outcome analysis (doc 08 §9, FR-17).

Chạy trong phase 2 (sau khi provider trả response): soi output của model để
tìm bằng chứng thất bại mà không phải chờ user phản ứng ở lượt sau.

Nguyên tắc (§9 + quyết định thiết kế):
- Bằng chứng fail từ output chỉ ĐÁNH DẤU state (`unresolved_failure`,
  `failed_tier`, `failure_streak`) — không tự cộng failure_boost thay user,
  vì §6.1 quy định refine/continue = chấp nhận ngầm sẽ clear flag.
- Bằng chứng được lưu vào `requests.outcome_evidence` để giải thích được (NFR-05).
- Feedback endpoint dùng `record()` để đổ bằng chứng ngoài vào session state (§6.1d).
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from src.gateway.app.core.zoning import split_zones

logger = logging.getLogger("smartroute.outcome")

# Song ngữ Anh–Việt. Chỉ quét instruction zone (đã bỏ fenced code, inline code,
# stack trace) để tránh false positive khi model trích dẫn văn bản chứa refusal.
_REFUSAL_RES = (
    re.compile(
        r"i\s+(?:cannot|can'?t|am\s+unable\s+to|won'?t)\s+(?:help|assist|provide|generate|comply|do\s+that)",
        re.IGNORECASE,
    ),
    re.compile(r"as an ai(?:\s+language)?\s+model", re.IGNORECASE),
    re.compile(
        r"tôi\s+(?:không\s+thể|xin\s+lỗi[,.]?\s*(?:nhưng\s+)?không\s+thể)"
        r"|không\s+thể\s+(?:hỗ\s+trợ|giúp)",
        re.IGNORECASE,
    ),
)

FAILURE_EVIDENCE = frozenset({"refusal", "truncated_output", "abnormally_short", "feedback_negative"})
POSITIVE_EVIDENCE = frozenset({"feedback_positive"})


@dataclass
class OutcomeEvidence:
    name: str  # refusal | truncated_output | abnormally_short | feedback_negative | feedback_positive
    detail: str
    tier: str | None
    ts: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


def is_refusal_text(content: str | None) -> bool:
    """True khi instruction zone (ngoài code/trace) chứa mẫu refusal."""
    if not content or not content.strip():
        return False
    instruction_zone, _ = split_zones(content)
    text = instruction_zone if instruction_zone else content.strip()
    return any(rx.search(text) for rx in _REFUSAL_RES)


class OutcomeObserver:
    def __init__(
        self,
        db_factory: Callable,
        failure_short_chars: int = 50,
        failure_min_score: int = 40,
    ):
        self.db_factory = db_factory
        self.failure_short_chars = failure_short_chars
        self.failure_min_score = failure_min_score

    # --- Detection (pure) ----------------------------------------------------

    def detect(
        self,
        content: str | None,
        finish_reason: str | None,
        difficulty_score: int,
    ) -> OutcomeEvidence | None:
        if not content or not content.strip():
            return None
        if finish_reason == "length":
            return OutcomeEvidence("truncated_output", "finish_reason=length", None, _now())
        if is_refusal_text(content):
            return OutcomeEvidence("refusal", "refusal pattern in instruction zone", None, _now())
        stripped = content.strip()
        if len(stripped) < self.failure_short_chars and difficulty_score >= self.failure_min_score:
            return OutcomeEvidence("abnormally_short", f"len={len(stripped)} score={difficulty_score}", None, _now())
        return None

    # --- Persistence ---------------------------------------------------------

    def observe(
        self,
        request_id: str | uuid.UUID,
        session_id: uuid.UUID | None,
        tier: str,
        content: str,
        finish_reason: str | None,
        difficulty_score: int,
        expected_turn_count: int | None = None,
    ) -> OutcomeEvidence | None:
        """Phase 2 hook: detect on final output; persist evidence + session state."""
        evidence = self.detect(content, finish_reason, difficulty_score)
        if evidence is None:
            return None
        evidence.tier = tier

        from src.gateway.app.db.crud import set_request_outcome

        db = self.db_factory()
        try:
            set_request_outcome(
                db,
                request_id,
                {"name": evidence.name, "detail": evidence.detail, "tier": evidence.tier, "ts": evidence.ts},
            )
            if session_id:
                apply_evidence_to_state(db, session_id, evidence.name, evidence.tier, expected_turn_count)
        finally:
            db.close()
        logger.info("outcome=%s request=%s session=%s", evidence.name, request_id, session_id)
        return evidence

    def record(
        self,
        session_id: uuid.UUID,
        name: str,
        detail: str,
        tier: str | None = None,
    ) -> bool:
        """Open interface for external evidence sources (§9) — e.g. feedback endpoints."""
        if name not in FAILURE_EVIDENCE and name not in POSITIVE_EVIDENCE:
            return False
        from src.gateway.app.db.crud import get_routing_state

        db = self.db_factory()
        try:
            state_dict, _ = get_routing_state(db, session_id)
            if not state_dict:
                logger.info("outcome=%s session=%s skipped: no routing state", name, session_id)
                return False
            return apply_evidence_to_state(db, session_id, name, tier, state_dict.get("turn_count", 0))
        finally:
            db.close()


def apply_evidence_to_state(
    db,
    session_id: uuid.UUID,
    evidence_name: str,
    tier: str | None,
    expected_turn_count: int | None,
) -> bool:
    """Mutate routing_state per evidence kind; CAS-guarded when turn count given.

    - failure-kind: unresolved_failure=True + failed_tier + streak+1 → failure_lock /
      failed-tier floor / pin-T3 tự kích hoạt ở lượt sau qua SessionRouter.
    - positive-kind (§6.1d): clear cả ba trường.
    """
    from src.gateway.app.core.session_router.state import SessionState
    from src.gateway.app.db.crud import patch_routing_state

    def mutate(state: dict) -> None:
        obj = SessionState.from_dict(state)
        if evidence_name in FAILURE_EVIDENCE:
            obj.unresolved_failure = True
            obj.failed_tier = tier or obj.failed_tier
            obj.failure_streak += 1
        elif evidence_name in POSITIVE_EVIDENCE:
            obj.unresolved_failure = False
            obj.failed_tier = None
            obj.failure_streak = 0
        new_state = obj.to_dict()
        state.clear()
        state.update(new_state)

    if expected_turn_count is None:
        state_dict, _ = patch_state_read(db, session_id)
        if not state_dict:
            return False
        expected_turn_count = state_dict.get("turn_count", 0)
    return patch_routing_state(db, session_id, expected_turn_count, mutate)


def patch_state_read(db, session_id: uuid.UUID) -> tuple[dict | None, object]:
    from src.gateway.app.db.crud import get_routing_state

    return get_routing_state(db, session_id)
