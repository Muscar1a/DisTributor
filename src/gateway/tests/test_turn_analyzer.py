"""Verify turn_analyzer does not treat pure resubmission as failure."""

from src.gateway.app.core.session_router.turn_analyzer import analyze_turn


def _msgs(*user_texts: str) -> list[dict]:
    out: list[dict] = []
    for text in user_texts:
        out.append({"role": "user", "content": text})
        out.append({"role": "assistant", "content": "ok"})
    return out


def test_repeated_ok_is_not_failure():
    msgs = _msgs("ok", "ok", "ok")
    turn = analyze_turn(msgs)
    assert not turn.failure_signal


def test_repeated_simple_prompt_is_not_failure():
    msgs = _msgs("tôi muốn học Python", "tôi muốn học Python")
    turn = analyze_turn(msgs)
    assert not turn.failure_signal


def test_correction_language_is_still_failure():
    msgs = _msgs("viết hàm sort", "sai rồi, viết lại đi")
    turn = analyze_turn(msgs)
    assert turn.failure_signal


def test_error_artifact_is_still_failure():
    msgs = [
        {"role": "user", "content": "fix this"},
        {"role": "assistant", "content": "here you go"},
        {"role": "user", "content": "TypeError: 'NoneType' is not callable\n  File \"app.py\", line 42"},
    ]
    turn = analyze_turn(msgs)
    assert turn.failure_signal


def test_self_contained_problem_with_content_it_is_new_task():
    """doc 13 §0.1: 'it' trong nội dung đề dài ('if it is non-empty') KHÔNG phải tham chiếu
    hội thoại → đề LeetCode tự chứa phải là new_task, không kế thừa độ khó lượt trước."""
    lcp = (
        'Write a function to find the longest common prefix string amongst an array of strings. '
        'If there is no common prefix, return an empty string "". Example: strs=["flower","flow"] '
        'Output: "fl". Constraints: strs[i] consists of only lowercase English letters if it is non-empty.'
    )
    msgs = [
        {"role": "user", "content": "Fix the deadlock in my async logger"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": lcp},
    ]
    assert analyze_turn(msgs).intent == "new_task"


def test_vietnamese_context_reference_is_not_new_task():
    """doc 13 §0.1: tham chiếu tiếng Việt tường minh ('hàm trên') → follow-up, không new_task."""
    msgs = [
        {"role": "user", "content": "Viết hàm đọc danh sách user từ file json"},
        {"role": "assistant", "content": "def read_users(): ..."},
        {"role": "user", "content": "Viết bộ unit test cho hàm trên giúp mình"},
    ]
    assert analyze_turn(msgs).intent != "new_task"
