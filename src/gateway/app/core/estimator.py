from src.gateway.app.core.interfaces import Message, Usage

# ~4 ký tự ≈ 1 token (heuristic chung cho tiếng Anh/Việt khi provider không trả usage).
_CHARS_PER_TOKEN = 4


class TokenEstimator:
    """Ước lượng token heuristic khi provider trả usage thiếu/sai (AC-4.2).

    Theo contract B.4: *provider trả thiếu -> adapter tự ước lượng + usage_estimated=True*.
    Module này là nơi duy nhất chứa logic ước lượng, được dùng chung bởi:
      - `CostCalculator` (fallback khi usage thiếu)
      - Các `Adapter` (Gemini/Groq/Mock) khi provider không trả `usage` trong response.
    """

    def estimate_tokens(self, text: str) -> int:
        """Ước lượng số token từ độ dài text (heuristic ~4 ký tự/token)."""
        if not text:
            return 0
        return max(1, (len(text) + _CHARS_PER_TOKEN - 1) // _CHARS_PER_TOKEN)

    def estimate_usage(self, messages: list[Message], completion: str) -> Usage:
        """Ước lượng usage từ messages (prompt) và completion text.

        Prompt gồm toàn bộ message (cả role + content); completion là text trả về.
        """
        prompt_chars = sum(len(m.role) + len(m.content) for m in messages)
        prompt_tokens = self.estimate_tokens(" " * prompt_chars) if prompt_chars else 0
        return Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=self.estimate_tokens(completion),
        )
