"""Test: EMA decays on low-effort continue turns (sticky score fix)."""

from src.gateway.app.core.interfaces import ClassificationResult, Tier
from src.gateway.app.core.session_router import SessionRouter
from src.gateway.app.core.session_router.state import SessionState


def _cls(score: int, signals: list | None = None) -> ClassificationResult:
    return ClassificationResult(
        score=score,
        tier=Tier.T1 if score < 30 else (Tier.T2 if score < 60 else Tier.T3),
        signals=signals or [],
        classifier_version="heuristic-v1.5",
        latency_ms=1,
    )


def test_ema_decays_on_repeated_low_score_continues():
    """Spam 'ok' after a hard turn should decay EMA, not keep it sticky."""
    router = SessionRouter(t1_max=30, t2_max=60)

    # Turn 1: hard task, score 50 → T2
    state = SessionState(turn_count=1, current_tier="T2", ema_score=50.0)
    messages = [
        {"role": "user", "content": "Viết hàm xử lý phức tạp với nhiều bước"},
        {"role": "assistant", "content": "def complex(): pass"},
        {"role": "user", "content": "ok"},
    ]

    # Simulate 5 turns of "ok" (cls.score ≈ 5 each time)
    for i in range(5):
        tier, signals, state, _, _ = router.route(messages, state, _cls(5))
        messages = [
            {"role": "user", "content": "ok"},
            {"role": "assistant", "content": "done"},
            {"role": "user", "content": "ok"},
        ]

    # After 5 low-effort turns, EMA should have decayed well below T2 threshold
    assert state.ema_score < 30, f"EMA should decay below 30, got {state.ema_score:.1f}"


def test_ema_stays_high_during_failure():
    """Failure turns should keep EMA high (model failed, task is still hard)."""
    router = SessionRouter(t1_max=30, t2_max=60)
    state = SessionState(turn_count=1, current_tier="T2", ema_score=50.0)

    messages = [
        {"role": "user", "content": "Viết code"},
        {"role": "assistant", "content": "def foo(): pass"},
        {"role": "user", "content": "Sai rồi, code bị lỗi không chạy được"},
    ]
    _, _, state, _, _ = router.route(messages, state, _cls(10))

    assert state.ema_score >= 40, f"EMA should stay high during failure, got {state.ema_score:.1f}"


def test_ema_stays_high_during_correction():
    """Correction intent should keep EMA high (same hard task)."""
    router = SessionRouter(t1_max=30, t2_max=60)
    state = SessionState(turn_count=1, current_tier="T2", ema_score=50.0)

    messages = [
        {"role": "user", "content": "Viết code"},
        {"role": "assistant", "content": "def foo(): pass"},
        {"role": "user", "content": "doesn't work, still broken"},
    ]
    _, _, state, _, _ = router.route(messages, state, _cls(10))

    assert state.ema_score >= 40, f"EMA should stay high during correction, got {state.ema_score:.1f}"
