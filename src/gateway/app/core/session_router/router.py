"""SessionRouter — stateful multi-turn routing (08_adaptive_routing.md §5).

Sits between classifier and PolicyEngine. Pure computation on state + turn analysis;
DB read/write is the caller's responsibility (orchestrator phase 2).
"""

from __future__ import annotations

from ..interfaces import ClassificationResult, Signal, Tier
from .state import SessionState
from .turn_analyzer import Turn, analyze_turn, count_hard_signals

TIER_ORDER = [Tier.T1, Tier.T2, Tier.T3]
TIER_INDEX = {t: i for i, t in enumerate(TIER_ORDER)}


def _tier(name: str) -> Tier:
    return Tier(name)


def _tier_from_score(score: int, t1_max: int, t2_max: int) -> Tier:
    if score < t1_max:
        return Tier.T1
    if score < t2_max:
        return Tier.T2
    return Tier.T3


def _gap_to_threshold(score: int, tier: Tier, t1_max: int, t2_max: int) -> int:
    """How far below current tier's lower threshold the score sits."""
    if tier == Tier.T3:
        return t2_max - score
    if tier == Tier.T2:
        return t1_max - score
    return score


class SessionRouter:
    def __init__(
        self,
        t1_max: int = 30,
        t2_max: int = 60,
        alpha: float = 0.45,
        deescalate_margin: int = 15,
        dwell_turns: int = 1,
        max_session_escalations: int = 3,
        failure_boost: int = 15,
        streak_boost: int = 10,
        similarity_threshold: float = 0.85,
    ):
        self.t1_max = t1_max
        self.t2_max = t2_max
        self.alpha = alpha
        self.deescalate_margin = deescalate_margin
        self.dwell_turns = dwell_turns
        self.max_session_escalations = max_session_escalations
        self.failure_boost = failure_boost
        self.streak_boost = streak_boost
        self.similarity_threshold = similarity_threshold

    def route(
        self,
        messages: list,
        state: SessionState | None,
        cls: ClassificationResult,
    ) -> tuple[Tier, list[Signal], SessionState, Tier | None, int]:
        """Returns (tier, explain_signals, updated_state, floor_tier, effective_score)."""
        turn = analyze_turn(messages, self.similarity_threshold)

        # doc 13 §5: LLM chấm intent (nếu có) ưu tiên trên trục new_task↔continue/refine/meta.
        # correction/failure vẫn tính bằng cấu trúc (stack trace mới, resubmission) — tin cậy cao,
        # rẻ, phải đúng cả khi LLM vắng (fallback → cls.intent = None → regex lo).
        if (
            cls.intent in ("new_task", "continue", "refine", "meta")
            and not turn.failure_signal
            and turn.intent != "correction"
        ):
            turn.intent = cls.intent

        if state is None or state.turn_count == 0:
            state = self._init_state_from_messages(messages, cls)

        signals: list[Signal] = []
        score = cls.score

        # §6.1: clear unresolved_failure at start of turn based on current intent
        if state.unresolved_failure and not turn.failure_signal:
            if turn.positive_ack or turn.intent == "new_task":
                state.unresolved_failure = False
                state.failed_tier = None
            elif turn.intent in ("refine", "meta", "continue"):
                state.unresolved_failure = False
                state.failed_tier = None

        # 1) Effective score — inherit difficulty via intent
        if turn.intent in ("continue", "refine", "correction"):
            score = max(score, int(state.ema_score))
            if score > cls.score:
                signals.append(Signal("ema_inherit", score - cls.score))
        if turn.intent == "new_task":
            score = cls.score
            signals.append(Signal("new_task_reset", 0))

        # Failure boost
        if turn.failure_signal and state.session_escalation_count < self.max_session_escalations:
            boost = self.failure_boost + self.streak_boost * min(state.failure_streak, 2)
            score += boost
            signals.append(Signal("failure_boost", boost))

        score = max(0, min(100, score))

        # 2) Raw tier from thresholds
        raw_tier = _tier_from_score(score, self.t1_max, self.t2_max)
        cur = _tier(state.current_tier)

        # Inherited EMA holds difficulty on continue/refine turns but must not let a trivial
        # turn escalate above cur — else a free "ok" inherits the ceiling and gets billed one
        # tier higher than the hard turn itself (pentest SR-1). Escalation needs a genuine
        # reason on THIS turn: the real classifier score, or a failure signal.
        real_tier = _tier_from_score(cls.score, self.t1_max, self.t2_max)
        escalation_warranted = TIER_INDEX[real_tier] > TIER_INDEX[cur] or turn.failure_signal

        # 3) Hysteresis
        if TIER_INDEX[raw_tier] > TIER_INDEX[cur]:
            if not escalation_warranted:
                tier = cur
                signals.append(Signal("hold_inherited_ceiling", 0))
            else:
                tier = self._escalate(raw_tier, cur, cls, turn, signals)
        elif TIER_INDEX[raw_tier] < TIER_INDEX[cur]:
            tier = self._deescalate(raw_tier, cur, cls.score, turn, state, signals)
        else:
            tier = cur

        # Failure lock: unresolved failure → don't de-escalate (except meta)
        floor_tier: Tier | None = None
        if state.unresolved_failure and turn.intent != "meta":
            floor_tier = cur
            if TIER_INDEX[tier] < TIER_INDEX[cur]:
                tier = cur
                signals.append(Signal("failure_lock", 0))

        # Don't route back to a tier that already failed
        if turn.failure_signal and state.failed_tier:
            failed_idx = TIER_INDEX.get(_tier(state.failed_tier), 0)
            if failed_idx + 1 < len(TIER_ORDER):
                cand = TIER_ORDER[failed_idx + 1]
                if floor_tier is None or TIER_INDEX[cand] > TIER_INDEX[floor_tier]:
                    floor_tier = cand
            if TIER_INDEX[tier] <= failed_idx and failed_idx + 1 < len(TIER_ORDER):
                tier = TIER_ORDER[failed_idx + 1]
                signals.append(Signal("failed_tier_floor", 0))

        # Budget exhausted but still failing → pin T3 (§6.2)
        if (
            turn.failure_signal
            and state.session_escalation_count >= self.max_session_escalations
            and state.unresolved_failure
        ):
            tier = Tier.T3
            floor_tier = Tier.T3
            signals.append(Signal("escalation_budget_exhausted", 0))

        signals.append(Signal(f"intent_{turn.intent}", 0))

        effective_score = score
        # EMA tracks real turn complexity, not inherited ceiling — prevents sticky score on low-effort continues
        ema_input = score if (turn.failure_signal or turn.intent == "correction") else cls.score
        new_state = self._update_state(state, tier, score, turn, ema_input=ema_input)

        return tier, signals, new_state, floor_tier, effective_score

    def _escalate(
        self, raw_tier: Tier, cur: Tier, cls: ClassificationResult, turn: Turn, signals: list[Signal]
    ) -> Tier:
        hard_count, has_jump = count_hard_signals(cls.signals, turn)
        # Jump straight to T3 for clear debugging cases
        if raw_tier == Tier.T3 and hard_count >= 2 and has_jump:
            signals.append(Signal("jump_t3_hard_signals", 0))
            return Tier.T3
        # Otherwise max +1 tier per turn
        next_idx = min(TIER_INDEX[cur] + 1, len(TIER_ORDER) - 1)
        tier = TIER_ORDER[next_idx]
        signals.append(Signal("escalate_plus_one", 0))
        return tier

    def _deescalate(
        self,
        raw_tier: Tier,
        cur: Tier,
        score: int,
        turn: Turn,
        state: SessionState,
        signals: list[Signal],
    ) -> Tier:
        if turn.intent == "correction":
            signals.append(Signal("hold_correction", 0))
            return cur
        if state.unresolved_failure:
            signals.append(Signal("hold_unresolved", 0))
            return cur
        current_turn = state.turn_count + 1
        if current_turn - state.last_escalation_turn < self.dwell_turns:
            signals.append(Signal("hold_dwell", 0))
            return cur
        gap = _gap_to_threshold(score, cur, self.t1_max, self.t2_max)
        if gap < self.deescalate_margin:
            signals.append(Signal("hold_margin", 0))
            return cur
        if turn.intent == "new_task":
            signals.append(Signal("deescalate_new_task", 0))
            return raw_tier
        if turn.intent == "meta":
            signals.append(Signal("deescalate_meta", 0))
            return raw_tier
        # refine/continue: max -1 tier
        prev_idx = max(TIER_INDEX[cur] - 1, 0)
        signals.append(Signal("deescalate_minus_one", 0))
        return TIER_ORDER[prev_idx]

    def _update_state(
        self, state: SessionState, tier: Tier, effective_score: int, turn: Turn,
        *, ema_input: int | None = None,
    ) -> SessionState:
        ema_val = ema_input if ema_input is not None else effective_score
        new = SessionState(
            turn_count=state.turn_count + 1,
            current_tier=tier.value,
            tier_history=(state.tier_history + [tier.value])[-5:],
            ema_score=self.alpha * ema_val + (1 - self.alpha) * state.ema_score,
            failure_streak=state.failure_streak,
            unresolved_failure=state.unresolved_failure,
            failed_tier=state.failed_tier,
            last_escalation_turn=state.last_escalation_turn,
            session_escalation_count=state.session_escalation_count,
            last_user_msg_hash=state.last_user_msg_hash,
        )

        # Escalation tracking
        if TIER_INDEX[tier] > TIER_INDEX.get(_tier(state.current_tier), 0):
            new.last_escalation_turn = new.turn_count
            new.session_escalation_count = state.session_escalation_count + 1

        # Failure tracking (§6.1)
        if turn.failure_signal:
            new.failure_streak = state.failure_streak + 1
            new.unresolved_failure = True
            new.failed_tier = state.current_tier
        elif turn.positive_ack or turn.intent == "new_task":
            new.failure_streak = 0
            new.unresolved_failure = False
            new.failed_tier = None
        elif turn.intent in ("refine", "meta", "continue") and not turn.failure_signal:
            # Working on the response = implicit acceptance (§6.1 condition a)
            new.failure_streak = 0
            new.unresolved_failure = False
            new.failed_tier = None

        if turn.intent == "new_task":
            new.ema_score = float(effective_score)

        return new

    def _init_state_from_messages(self, messages: list, cls: ClassificationResult) -> SessionState:
        """Degraded mode (§5.3): derive approximate state from messages array."""
        user_count = sum(
            1
            for m in (messages or [])
            if (m.get("role") if isinstance(m, dict) else getattr(m, "role", "")) == "user"
        )
        if user_count <= 1:
            return SessionState(turn_count=0, ema_score=float(cls.score), current_tier="T1")
        # Approximate ema from recent messages (cap 3)
        return SessionState(
            turn_count=max(0, user_count - 1),
            ema_score=float(cls.score) * 0.8,
            current_tier="T1",
        )
