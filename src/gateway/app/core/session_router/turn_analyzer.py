"""TurnAnalyzer — stateless, pure, <100ms (08_adaptive_routing.md §5.1).

Classifies turn intent and detects failure signals from the messages array.
No I/O, no DB, no config reads at runtime.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# --- Intent classification (priority order per §5.1 consequence matrix) ------
# correction > new_task > meta > refine > continue

_CORRECTION_RE = re.compile(
    r"(doesn'?t\s*work|not\s*work|still\s*(fail|wrong|broken|error|crash)"
    r"|sai\s*r[oồ]i|v[aẫ]n\s*l[oỗ]i|kh[oô]ng\s*(đúng|dung|chạy|chay|hoạt|hoat)"
    r"|b[iị]\s*l[oỗ]i|wrong\s*(output|result|answer)|incorrect|broken"
    r"|that'?s\s*not\s*right|fix\s*(this|it|that)|try\s*again)",
    re.IGNORECASE,
)

# Leading imperative verb: strong enough to open the FIRST turn, but NOT to
# reset a live session — "viết unit test cho hàm đó" is a follow-up, not a new
# task (doc 08 §5.2/§11.3: a false continue→new_task cuts ema and under-routes).
_DELIVERABLE_VERB_RE = re.compile(
    r"^(write|create|build|make|implement|design|generate|develop|tạo|tao|viết|viet|xây|xay|thiết\s*kế|thiet\s*ke)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Explicit topic switch: the only new_task evidence trusted MID-session.
_TOPIC_SWITCH_RE = re.compile(
    r"(chuyển\s*sang|chuyen\s*sang|switch\s*to|now\s*(do|write|create|build)"
    r"|sang\s*(việc|viec|bài|bai)\s*(khác|khac|mới|moi)"
    r"|unrelated|new\s*topic|khác\s*nhé|khac\s*nhe|bài\s*mới|bai\s*moi)",
    re.IGNORECASE | re.MULTILINE,
)

_META_RE = re.compile(
    r"(format\s*lại|format\s*lai|reformat|gi[aả]i\s*thích|giai\s*thich|explain"
    r"|rename|đ[oổ]i\s*tên|doi\s*ten|th[eê]m\s*docstring|them\s*docstring"
    r"|d[iị]ch\s*comment|dich\s*comment|translate|add\s*comment|th[eê]m\s*comment"
    r"|prettify|beautify|lint|clean\s*up\s*format)",
    re.IGNORECASE,
)

_REFINE_RE = re.compile(
    r"(simplify|t[oố]i\s*[uư]u|toi\s*uu|optimize|vi[eế]t\s*g[oọ]n|viet\s*gon"
    r"|refactor|improve|make\s*it\s*(shorter|faster|cleaner|simpler|better)"
    r"|rút\s*gọn|rut\s*gon|cải\s*thiện|cai\s*thien)",
    re.IGNORECASE,
)

# --- Error artifact detection ------------------------------------------------

_ERROR_ARTIFACT_RE = re.compile(
    r"(Traceback\s*\(most\s*recent\s*call\s*last\)"
    r'|File\s*"[^"]+",\s*line\s*\d+'
    r"|^\w+(Error|Exception):"
    r"|FAILED\s+test_"
    r"|AssertionError|AssertionError"  # common typo + correct
    r"|AssertionError|AssertionError"
    r"|panic:"
    r"|Exception\s+in\s+thread)",
    re.IGNORECASE | re.MULTILINE,
)

# ponytail: fingerprint = sha1(exception_name + last_trace_line, normalized)
_EXCEPTION_LINE_RE = re.compile(r"^\s*(\w+(?:Error|Exception|Panic)\b.*)", re.MULTILINE)

# --- Positive ack (§6.1 — clears unresolved_failure) ------------------------

_POSITIVE_ACK_RE = re.compile(
    r"(works?\s*now|ch[aạ]y\s*đ[uư][oợ]c|chay\s*duoc|đ[uư][oợ]c\s*r[oồ]i|duoc\s*roi"
    r"|ok\s*c[aả]m\s*[oơ]n|ok\s*cam\s*on|thanks.*fix|that\s*fix"
    r"|c[aả]m\s*[oơ]n|cam\s*on\s*nh[eé]|perfect|great|looks?\s*good"
    r"|hoạt\s*động\s*rồi|hoat\s*dong\s*roi)",
    re.IGNORECASE,
)

# --- Concurrency keywords (hard signal for jump-to-T3) ----------------------

_CONCURRENCY_RE = re.compile(
    r"\b(race\s*condition|deadlock|thread|async|lock|mutex|concurrent|semaphore"
    r"|atomic|synchroniz|data\s*race)\b",
    re.IGNORECASE,
)

# --- Hard signal names (for count_hard_signals) ------------------------------

HARD_SIGNAL_NAMES = frozenset({"code", "math_logic", "multi_step", "error_artifact", "concurrency_keywords"})
JUMP_T3_SIGNALS = frozenset({"error_artifact", "concurrency_keywords"})


@dataclass
class Turn:
    intent: str  # new_task | continue | refine | correction | meta
    failure_signal: bool
    positive_ack: bool
    has_error_artifact: bool
    has_concurrency: bool


def classify_intent(last_msg: str, prev_user_msg: str | None) -> str:
    if _CORRECTION_RE.search(last_msg):
        return "correction"
    if prev_user_msg is None:
        # First turn: any deliverable request opens a new task (doc 08 §5.3).
        if _DELIVERABLE_VERB_RE.search(last_msg) or _TOPIC_SWITCH_RE.search(last_msg):
            return "new_task"
    elif not _refers_to_context(last_msg) and (
        _TOPIC_SWITCH_RE.search(last_msg) or _DELIVERABLE_VERB_RE.search(last_msg)
    ):
        # Mid-session: an explicit topic switch or a self-contained deliverable task
        # resets to new_task. If it refers to context (e.g. "viết unit test cho hàm trên"),
        # _refers_to_context is True and it stays a follow-up.
        return "new_task"
    if _META_RE.search(last_msg):
        return "meta"
    if _REFINE_RE.search(last_msg):
        return "refine"
    return "continue"


# Tham chiếu hội thoại tiếng Việt: "hàm trên", "đoạn code đó", "biến này", "ở trên"...
_VN_CONTEXT_REF_RE = re.compile(
    r"(hàm|đoạn|code|class|biến|function|kết\s*quả|đoạn\s*code)\s*(trên|này|đó|ấy|vừa)"
    r"|ở\s*trên|phía\s*trên|bên\s*trên|vừa\s*(rồi|nãy|xong)|trên\s*đó",
    re.IGNORECASE,
)

# Anaphora ("it/this", "hàm trên") chỉ mang nghĩa tham chiếu ở câu NGẮN (doc 08 §5; doc 13 §0.1).
# Một đề bài tự chứa dài chứa "it" trong nội dung ("if it is non-empty") KHÔNG phải tham chiếu
# hội thoại — coi nó là task mới. ponytail: ngưỡng 200 ký tự, tune nếu lọt đề ngắn/câu follow dài.
def _refers_to_context(text: str) -> bool:
    if len(text) > 200:
        return False
    return bool(
        re.search(r"\b(it|this|that|its|the\s+(code|fix|solution|result|output|error))\b", text, re.IGNORECASE)
        or _VN_CONTEXT_REF_RE.search(text)
    )


def _fingerprint_error(text: str) -> str | None:
    match = _EXCEPTION_LINE_RE.search(text)
    if not match:
        return None
    normalized = re.sub(r"\s+", " ", match.group(1).strip())
    return hashlib.sha1(normalized.encode()).hexdigest()[:16]


def _has_new_error_artifact(messages: list[dict], last_msg: str) -> bool:
    if not _ERROR_ARTIFACT_RE.search(last_msg):
        return False
    fp = _fingerprint_error(last_msg)
    if fp is None:
        return True
    for msg in messages[:-1]:
        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        if content and _fingerprint_error(content) == fp:
            return False
    return True


def _jaccard_similarity(a: str, b: str) -> float:
    def tokenize(s: str) -> set[str]:
        return {t.lower() for t in re.findall(r"\w+", s)}
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _is_resubmission(last_msg: str, prev_user_msg: str | None, threshold: float) -> bool:
    if prev_user_msg is None:
        return False
    len_a, len_b = len(last_msg), len(prev_user_msg)
    if max(len_a, len_b) == 0:
        return False
    if abs(len_a - len_b) / max(len_a, len_b) > 0.30:
        return False
    return _jaccard_similarity(last_msg, prev_user_msg) > threshold


def analyze_turn(
    messages: list,
    similarity_threshold: float = 0.85,
) -> Turn:
    last_msg = _last_user_content(messages)
    prev_user_msg = _prev_user_content(messages)

    intent = classify_intent(last_msg, prev_user_msg)

    has_error = _has_new_error_artifact(messages, last_msg)
    has_correction = _CORRECTION_RE.search(last_msg) is not None

    failure_signal = has_correction or has_error
    positive_ack = bool(_POSITIVE_ACK_RE.search(last_msg))
    has_concurrency = bool(_CONCURRENCY_RE.search(last_msg))

    return Turn(
        intent=intent,
        failure_signal=failure_signal,
        positive_ack=positive_ack,
        has_error_artifact=has_error,
        has_concurrency=has_concurrency,
    )


def count_hard_signals(
    classifier_signals: list,
    turn: Turn,
) -> tuple[int, bool]:
    """Returns (count, has_jump_signal). §5.1: jump T3 needs count>=2 AND >=1 jump signal."""
    names: set[str] = set()
    for sig in classifier_signals:
        n = sig.name if hasattr(sig, "name") else sig.get("name", "")
        if n == "math":
            n = "math_logic"
        if n in HARD_SIGNAL_NAMES:
            names.add(n)
    if turn.has_error_artifact:
        names.add("error_artifact")
    if turn.has_concurrency:
        names.add("concurrency_keywords")
    has_jump = bool(names & JUMP_T3_SIGNALS)
    return len(names), has_jump


def _last_user_content(messages: list) -> str:
    for msg in reversed(messages or []):
        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
        if role == "user" and content:
            return content
    return ""


def _prev_user_content(messages: list) -> str | None:
    found_last = False
    for msg in reversed(messages or []):
        role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        if role == "user" and content:
            if not found_last:
                found_last = True
                continue
            return content
    return None
