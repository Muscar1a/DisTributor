"""SessionState — routing state persisted in sessions.routing_state JSONB (§4).

Fixed-size (~300 bytes), tier_history capped at 5, validated on write.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class SessionState:
    turn_count: int = 0
    current_tier: str = "T1"
    tier_history: list[str] = field(default_factory=list)
    ema_score: float = 0.0
    failure_streak: int = 0
    unresolved_failure: bool = False
    failed_tier: str | None = None
    last_escalation_turn: int = 0
    session_escalation_count: int = 0
    last_user_msg_hash: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "turn_count": self.turn_count,
            "current_tier": self.current_tier,
            "tier_history": self.tier_history[-5:],
            "ema_score": round(self.ema_score, 1),
            "failure_streak": self.failure_streak,
            "unresolved_failure": self.unresolved_failure,
            "failed_tier": self.failed_tier,
            "last_escalation_turn": self.last_escalation_turn,
            "session_escalation_count": self.session_escalation_count,
            "last_user_msg_hash": self.last_user_msg_hash,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> SessionState:
        if not data:
            return cls()
        return cls(
            turn_count=int(data.get("turn_count", 0)),
            current_tier=str(data.get("current_tier", "T1")),
            tier_history=list(data.get("tier_history", []))[-5:],
            ema_score=float(data.get("ema_score", 0.0)),
            failure_streak=int(data.get("failure_streak", 0)),
            unresolved_failure=bool(data.get("unresolved_failure", False)),
            failed_tier=data.get("failed_tier"),
            last_escalation_turn=int(data.get("last_escalation_turn", 0)),
            session_escalation_count=int(data.get("session_escalation_count", 0)),
            last_user_msg_hash=str(data.get("last_user_msg_hash", "")),
            updated_at=str(data.get("updated_at", "")),
        )

    def is_expired(self, last_activity_at: datetime | None, ttl_s: int) -> bool:
        if last_activity_at is None:
            return False
        now = datetime.now(UTC)
        if last_activity_at.tzinfo is None:
            last_activity_at = last_activity_at.replace(tzinfo=UTC)
        return (now - last_activity_at).total_seconds() > ttl_s
