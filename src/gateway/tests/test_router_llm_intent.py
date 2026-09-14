"""doc 13 §5: SessionRouter ưu tiên intent do LLM chấm, giữ regex làm nền khi vắng."""

from src.gateway.app.core.interfaces import ClassificationResult, Tier
from src.gateway.app.core.session_router import SessionRouter
from src.gateway.app.core.session_router.state import SessionState


def _cls(score: int, intent: str | None = None) -> ClassificationResult:
    return ClassificationResult(
        score=score,
        tier=Tier.T1 if score < 30 else (Tier.T2 if score < 60 else Tier.T3),
        signals=[],
        classifier_version="llm-v2",
        latency_ms=1,
        intent=intent,
    )


def _msgs(prev: str, last: str) -> list[dict]:
    return [
        {"role": "user", "content": prev},
        {"role": "assistant", "content": "ok"},
        {"role": "user", "content": last},
    ]


def test_llm_new_task_intent_blocks_ema_inherit():
    """Ca Two Sum: bài easy (score 10) sau bài khó (ema cao). Regex tưởng continue → dính ema.
    LLM chấm new_task → reset ema → T1."""
    router = SessionRouter(t1_max=30, t2_max=60)
    state = SessionState(turn_count=1, current_tier="T2", ema_score=45.0)
    msgs = _msgs(
        "Fix the deadlock in my async logger",
        "Given an array nums and a target, return indices of two numbers adding to target",
    )
    tier, signals, *_ = router.route(msgs, state, _cls(10, intent="new_task"))
    assert tier == Tier.T1
    assert any(s.name == "new_task_reset" for s in signals)
    assert not any(s.name == "ema_inherit" for s in signals)


def test_llm_intent_none_falls_back_to_regex():
    """Fallback (LLM vắng): intent=None → regex quyết. 'ok' → continue → kế thừa ema."""
    router = SessionRouter(t1_max=30, t2_max=60)
    state = SessionState(turn_count=1, current_tier="T2", ema_score=45.0)
    tier, signals, *_ = router.route(_msgs("previous hard task", "ok"), state, _cls(5, intent=None))
    assert any(s.name == "ema_inherit" for s in signals)


def test_structural_failure_wins_over_llm_intent():
    """LLM nói new_task nhưng lượt kèm stack trace mới → failure structural thắng, không reset."""
    router = SessionRouter(t1_max=30, t2_max=60)
    state = SessionState(turn_count=1, current_tier="T2", ema_score=45.0)
    trace = 'Traceback (most recent call last):\n  File "x.py", line 1, in f\nValueError: boom'
    tier, signals, *_ = router.route(_msgs("previous task", trace), state, _cls(20, intent="new_task"))
    assert not any(s.name == "new_task_reset" for s in signals)
