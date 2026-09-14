"""ClassifierV1Heuristic — chấm độ khó prompt bằng luật, không gọi LLM (FR-02).

Bảng tín hiệu và trọng số lấy nguyên từ `docs/design/02_prd.md` §6.2; ngưỡng tier
lấy từ `docs/design/05_interfaces.md` §D (`thresholds`). Không tự ý đổi số ở đây —
đổi phải qua PR sửa tài liệu trước.

Ràng buộc từ contract B.2 (`interfaces.py`):
  * không bao giờ raise — lỗi nội bộ/quá hạn trả về T2 + signal `classifier_error`;
  * tự cắt theo `router_timeout_ms` (mặc định 800ms);
  * thuần chức năng — không I/O, không đọc config ngoài constructor.
"""

import os
import re
import time

from .interfaces import BaseClassifier, ClassificationResult, Message, Signal, Tier

CLASSIFIER_VERSION = "heuristic-v1"

# Giá trị trả về khi classifier lỗi hoặc quá hạn (ADR-009 — an toàn giữa).
FALLBACK_TIER = Tier.T2
FALLBACK_SCORE = 45

# Ngưỡng mặc định — PRD §6.2: score < 30 -> T1, 30–59 -> T2, >= 60 -> T3.
DEFAULT_T1_MAX = 30
DEFAULT_T2_MAX = 60
DEFAULT_ROUTER_TIMEOUT_MS = 800

# --- Ngưỡng phụ của từng tín hiệu (PRD §6.2) --------------------------------
LENGTH_MID_TOKENS = 50  # >= mức này bắt đầu cộng điểm độ dài
LENGTH_LONG_TOKENS = 300  # > mức này là prompt dài
LONG_CONTEXT_TOKENS = 2_000  # ngữ cảnh đính kèm dài
LONG_CREATIVE_WORDS = 500  # yêu cầu sáng tạo dài
FAST_PATH_MAX_WORDS = 8  # câu ngắn đủ điều kiện fast-path

# --- Regex nhận diện tín hiệu (song ngữ Việt–Anh ngay từ v1) ---------------
# Dùng re.IGNORECASE; đã bỏ dấu tiếng Việt ở nơi có thể để bắt cả gõ không dấu.

_CODE_FENCE_RE = re.compile(r"```")
_CODE_TOKEN_RE = re.compile(
    r"\b(def|class|import|from|return|SELECT|INSERT|UPDATE|DELETE|function|const|let|var|async|await)\b",
    re.IGNORECASE,
)
_CODE_KEYWORD_RE = re.compile(
    r"(debug|refactor|fix\s*bug|sửa\s*lỗi|sua\s*loi|viết\s*hàm|viet\s*ham|viết\s*code|viet\s*code"
    r"|code\s*review|stack\s*trace|traceback|compile|exception|unit\s*test)",
    re.IGNORECASE,
)

_MATH_KEYWORD_RE = re.compile(
    r"(chứng\s*minh|chung\s*minh|giải\s*phương\s*trình|giai\s*phuong\s*trinh|tích\s*phân|tich\s*phan"
    r"|đạo\s*hàm|dao\s*ham|xác\s*suất|xac\s*suat|solve|prove|integral|derivative|equation|probability"
    r"|calculate|compute)",
    re.IGNORECASE,
)
# "tính/tinh" đứng riêng dễ nhầm ("tính cách", "tính năng") nên phải đi kèm số.
_MATH_EXPR_RE = re.compile(r"\d\s*[+\-*/^%=]\s*\d")
_MATH_SYMBOL_RE = re.compile(r"[√∫∑∏≤≥≠±∞π]")

_MULTI_STEP_RE = re.compile(
    r"(phân\s*tích|phan\s*tich|so\s*sánh|so\s*sanh|đánh\s*giá|danh\s*gia|lập\s*kế\s*hoạch|lap\s*ke\s*hoach"
    r"|từng\s*bước|tung\s*buoc|vì\s*sao|vi\s*sao|tại\s*sao|tai\s*sao|step\s*by\s*step|analyze|compare"
    r"|evaluate|plan\s+out|why\s+does|explain\s+why)",
    re.IGNORECASE,
)

_OUTPUT_CONSTRAINT_RE = re.compile(
    r"(json\s*schema|trả\s*về\s*json|tra\s*ve\s*json|đúng\s*định\s*dạng|dung\s*dinh\s*dang"
    r"|dạng\s*bảng|dang\s*bang|markdown\s*table|as\s+json|in\s+json|csv|yaml"
    r"|đúng\s*\d+\s*(từ|tu|chữ|chu|dòng|dong)|exactly\s*\d+\s*(words|lines|bullets))",
    re.IGNORECASE,
)

_LONG_CREATIVE_RE = re.compile(
    r"(viết\s*bài|viet\s*bai|viết\s*truyện|viet\s*truyen|bài\s*luận|bai\s*luan|essay|short\s*story"
    r"|blog\s*post|write\s+an?\s+article)",
    re.IGNORECASE,
)
_WORD_COUNT_REQUEST_RE = re.compile(r"(\d{3,5})\s*(từ|tu|chữ|chu|words)", re.IGNORECASE)

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|chào|chao|xin\s*chào|xin\s*chao|good\s*(morning|afternoon|evening)"
    r"|cảm\s*ơn|cam\s*on|thanks|thank\s*you|ok|okay|bye|tạm\s*biệt|tam\s*biet)\b",
    re.IGNORECASE,
)


def estimate_tokens(text: str) -> int:
    """Ước lượng số token không cần tokenizer — giữ classifier thuần CPU, không I/O.

    Lấy giá trị lớn hơn giữa hai cách xấp xỉ: ~1.3 token/từ (hợp với tiếng Anh) và
    ~4 ký tự/token (hợp với tiếng Việt có dấu, vốn tốn nhiều token hơn mỗi từ).
    """
    if not text:
        return 0
    words = len(text.split())
    return max(int(words * 1.3), len(text) // 4)


class ClassifierV1Heuristic(BaseClassifier):
    """Chấm điểm 0–100 bằng cộng dồn tín hiệu, rồi ánh xạ sang tier.

    Ngưỡng đặt **bảo thủ** (nghiêng về tier cao khi phân vân) để bảo vệ chất lượng —
    rủi ro R1 trong `06_architecture.md`: đẩy nhầm task khó xuống model rẻ tốn kém
    hơn nhiều so với việc trả dư tiền cho một request dễ.
    """

    def __init__(
        self,
        t1_max: int = DEFAULT_T1_MAX,
        t2_max: int = DEFAULT_T2_MAX,
        router_timeout_ms: int | None = None,
    ) -> None:
        self.t1_max = t1_max
        self.t2_max = t2_max
        if router_timeout_ms is None:
            router_timeout_ms = int(os.getenv("ROUTER_TIMEOUT_MS", DEFAULT_ROUTER_TIMEOUT_MS))
        self.router_timeout_ms = router_timeout_ms

    # -- API công khai ------------------------------------------------------

    async def classify(self, messages: list[Message]) -> ClassificationResult:
        started = time.perf_counter()
        try:
            score, signals = self._score(messages, started)
            tier = self._to_tier(score)
        except Exception:  # noqa: BLE001 — contract B.2: tuyệt đối không raise ra ngoài
            return self._fallback(started)
        return ClassificationResult(
            score=score,
            tier=tier,
            signals=signals,
            classifier_version=CLASSIFIER_VERSION,
            latency_ms=self._elapsed_ms(started),
        )

    # -- Chấm điểm ----------------------------------------------------------

    def _score(self, messages: list[Message], started: float) -> tuple[int, list[Signal]]:
        prompt = self._prompt_text(messages)
        context_tokens = sum(estimate_tokens(m.content or "") for m in messages)
        prompt_tokens = estimate_tokens(prompt)

        signals: list[Signal] = []
        score = 0

        for name, points in (
            ("code", self._code_points(prompt)),
            ("math", self._math_points(prompt)),
            ("multi_step", self._multi_step_points(prompt)),
            ("output_constraint", self._output_constraint_points(prompt)),
            ("long_creative", self._long_creative_points(prompt)),
            ("length", self._length_points(prompt_tokens)),
            ("long_context", 10 if context_tokens > LONG_CONTEXT_TOKENS else 0),
        ):
            if points:
                signals.append(Signal(name, points))
                score += points

        self._check_deadline(started)

        # Fast-path Easy chỉ áp dụng khi KHÔNG có tín hiệu nào ở trên (PRD §6.2).
        # Phải xét sau cùng: một câu ngắn kèm tài liệu 5.000 token vẫn là việc nặng,
        # ép nó xuống T1 là đúng rủi ro R1 mà kiến trúc cảnh báo.
        if not signals and self._is_fast_path_easy(prompt):
            return 0, [Signal("fast_path_easy", 0)]

        return max(0, min(100, score)), signals

    def _length_points(self, prompt_tokens: int) -> int:
        if prompt_tokens > LENGTH_LONG_TOKENS:
            return 18
        if prompt_tokens >= LENGTH_MID_TOKENS:
            return 10
        return 0

    def _code_points(self, prompt: str) -> int:
        if _CODE_FENCE_RE.search(prompt) or _CODE_TOKEN_RE.search(prompt) or _CODE_KEYWORD_RE.search(prompt):
            return 22
        return 0

    def _math_points(self, prompt: str) -> int:
        if _MATH_KEYWORD_RE.search(prompt) or _MATH_EXPR_RE.search(prompt) or _MATH_SYMBOL_RE.search(prompt):
            return 20
        return 0

    def _multi_step_points(self, prompt: str) -> int:
        if _MULTI_STEP_RE.search(prompt) or prompt.count("?") >= 2:
            return 15
        return 0

    def _output_constraint_points(self, prompt: str) -> int:
        return 10 if _OUTPUT_CONSTRAINT_RE.search(prompt) else 0

    def _long_creative_points(self, prompt: str) -> int:
        if not _LONG_CREATIVE_RE.search(prompt):
            return 0
        match = _WORD_COUNT_REQUEST_RE.search(prompt)
        if match and int(match.group(1)) > LONG_CREATIVE_WORDS:
            return 10
        return 0

    def _is_fast_path_easy(self, prompt: str) -> bool:
        if _GREETING_RE.search(prompt):
            return True
        return 0 < len(prompt.split()) <= FAST_PATH_MAX_WORDS

    # -- Tiện ích -----------------------------------------------------------

    def _to_tier(self, score: int) -> Tier:
        if score < self.t1_max:
            return Tier.T1
        if score < self.t2_max:
            return Tier.T2
        return Tier.T3

    def _prompt_text(self, messages: list[Message]) -> str:
        """Chấm trên message user cuối cùng — đó là yêu cầu thật sự cần định tuyến.

        System prompt và lượt trước chỉ tính vào `long_context`, không tính độ khó,
        để một system prompt dài không kéo mọi request lên T3.
        """
        for message in reversed(messages or []):
            if message.role == "user" and message.content:
                return message.content
        return ""

    def _check_deadline(self, started: float) -> None:
        if self._elapsed_ms(started) > self.router_timeout_ms:
            raise TimeoutError("classifier vượt ROUTER_TIMEOUT_MS")

    def _elapsed_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _fallback(self, started: float) -> ClassificationResult:
        return ClassificationResult(
            score=FALLBACK_SCORE,
            tier=FALLBACK_TIER,
            signals=[Signal("classifier_error", 0)],
            classifier_version=CLASSIFIER_VERSION,
            latency_ms=self._elapsed_ms(started),
        )
