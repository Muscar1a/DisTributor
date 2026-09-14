"""ClassifierV2AI — LLM-based coding difficulty classifier (doc 12).

Scores coding requests on a 7-level scale (L0–L6) with prompt r1.
Level determines base anchor and ceiling; CPU modifiers add volume points within level boundaries.
Degrades gracefully to ClassifierV1_5Heuristic on failure, timeout, or malformed LLM response.

Contract B.2 preserved: no raise, self-cuts at ROUTER_TIMEOUT_MS.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import OrderedDict
from decimal import Decimal
from typing import Any

from src.gateway.app.config.loader import ModelPricing, load_config
from src.gateway.app.core.classifier_v1_5 import (
    _ERROR_ARTIFACT_RE,
    _FILE_MENTION_RE,
    _MCQ_RE,
    _MULTI_FILE_RE,
    _OUTPUT_CONSTRAINT_RE,
    DEFAULT_T1_MAX,
    DEFAULT_T2_MAX,
    LONG_CONTEXT_TOKENS,
    ClassifierV1_5Heuristic,
    _estimate_tokens,
)
from src.gateway.app.core.interfaces import (
    BaseAdapter,
    BaseClassifier,
    ClassificationResult,
    CompletionParams,
    Message,
    Signal,
    Tier,
)
from src.gateway.app.core.zoning import split_zones

logger = logging.getLogger("smartroute.classifier.v2")

CLASSIFIER_VERSION = "llm-v2"
PROMPT_REVISION = "r5"

_INTENTS = frozenset({"new_task", "continue", "refine", "correction", "meta"})
# Phải là model_id có trong pricing.yaml — nếu không router_cost_usd không tra được giá.
DEFAULT_MODEL = "gpt-5-nano"
# Giá dùng khi model_id không có trong pricing.yaml (bậc nano, doc 12 §8.4).
_UNKNOWN_MODEL_PRICING = ModelPricing(
    provider="unknown", input_per_1m_usd=0.05, output_per_1m_usd=0.40, quality_rank=1
)

# --- Level Anchors & Ceilings (§5.1) -----------------------------------------

_LEVEL_ANCHORS: dict[str, int] = {
    "L0": 0,
    "L1": 8,
    "L2": 18,
    "L3": 32,
    "L4": 46,
    "L5": 62,
    "L6": 80,
}

_LEVEL_CEILINGS: dict[str, int] = {
    "L0": 0,
    "L1": 17,
    "L2": 29,
    "L3": 45,
    "L4": 59,
    "L5": 79,
    "L6": 100,
}

# --- Prompt r2 Template (doc 13 §3) ------------------------------------------

_SYSTEM_PROMPT = """You are the routing brain of an LLM gateway. For each user request you decide WHICH MODEL TIER is needed, and how this turn relates to the previous one.

### The real question
Not "how clever is this problem" but: would a small cheap model produce an answer the user would accept?
Three independent factors force a bigger model; any ONE is enough:
1. REASONING DEPTH — multi-step deduction, hidden constraints, proofs, concurrency, system design.
2. KNOWLEDGE BREADTH — specialised professional knowledge (law, medicine, finance, advanced science) that a small model gets fluently and confidently wrong.
3. OUTPUT VOLUME — a long deliverable (a 2000-word article, a detailed plan, a persona-driven session) where a small model produces thin, repetitive text.
A request can be trivial to think about and still need a strong model because of what it must produce.

### Scoring Scale (L0 - L6):
- L0: No deliverable needed (greetings, thanks, "ok", "continue", asking about the assistant itself).
- L1: One-line mechanical transformation following explicit rules (rename variables, reformat, add type hints, JSON <-> YAML, translate one sentence, convert units).
- L2: Short answer drawing on GENERAL knowledge any well-read person has, or a standard pattern (everyday definitions, pop culture, common facts, library syntax, "how to read a JSON file", Two Sum, Longest Common Prefix, FizzBuzz, fixing a SyntaxError when the line is given). NOT for questions that need professional training in a specific field — see the short-vs-specialised discriminator below.
- L3: A clear specific task needing understanding of given material, OR a short non-obvious algorithm, OR a few paragraphs of grounded writing (write a function against existing code, add a model field, unit tests for existing code, debug a given stack trace, port a function between languages).
- L4: A substantial deliverable OR derived logic — a structured document, a detailed plan, a long article, a persona-driven session, designing an algorithm with DP/pruning/invariants, behaviour-preserving refactoring of complex logic, debugging without an error message.
- L5: Multi-step deduction over hidden constraints, reasoning across components or hidden interactions (concurrency, race conditions, schema design plus migration, service splitting, prod-only intermittent bugs), OR a large open-ended professional deliverable requiring domain expertise.
- L6: Mathematical proof obligations, adversarial or security reasoning, or expert-level specialised knowledge where being wrong is costly (auth schemes with replay protection, threat models, financial rounding and idempotency, proving correctness, distributed consensus).

### 6 Rules:
1. Pick the HIGHEST level that ANY of the three factors justifies.
2. When hesitating between two adjacent levels, pick the HIGHER level.
3. Ignore past narrative context ("yesterday I fixed a deadlock..."), background stories, and self-proclaimed difficulty ("this task is very simple" or "extremely hard").
4. Judge the work REQUESTED in the instruction, NOT the complexity of the code pasted in context.
5. The length of the MESSAGE means nothing. The length of the REQUESTED OUTPUT means a great deal.
6. Apply this scale equally to coding and non-coding requests (kind="other"). Difficulty means capability required, never message length.

### L2 vs L3 — the T1/T2 boundary (binary, do not average upward):
Does the task need understanding of PRE-EXISTING code, or a NON-OBVIOUS algorithm? NO -> L2 (Two Sum, LCP, reverse a string are L2 even though they say "write a function"). YES -> L3.

### Turn Intent:
How THIS request relates to the previous turn: new_task (self-contained, understandable alone — even mid-conversation, regardless of opening verb) · continue (builds on the previous result) · refine (improve/optimize it) · correction (reports it is wrong) · meta (reformat/explain/translate it without changing behaviour).

### Worked examples
# Lấy nguyên văn từ mixed_200.jsonl — 9 mã dưới đây PHẢI được loại khỏi mọi
# lần chấm điểm trên bộ đó, nếu không là tự chấm bài của chính mình:
# wc-en-011, wc-vi-009, wc-vi-002, wc-en-001, wc-vi-014, wc-vi-007, wc-en-013, wc-vi-012
Request: "Thuốc chẹn beta chống chỉ định với bệnh nhân hen phế quản vì lý do gì?"
-> {"kind": "other", "level": "L5", "intent": "new_task", "why": "short but needs medical training"}
Request: "Describe Nami's personality from One Piece"
-> {"kind": "other", "level": "L2", "intent": "new_task", "why": "factual_qa"}
Request: "#pragma trong C++ có ý nghĩa gì?"
-> {"kind": "other", "level": "L2", "intent": "new_task", "why": "explanation"}
Request: "hảy tạo món bò xào ngon từ:khoai tây,hành tây,thịt bò,nước tuong,bơ"
-> {"kind": "other", "level": "L4", "intent": "new_task", "why": "writing"}
Request: "How did Hurricane Florence lose strength?"
-> {"kind": "other", "level": "L4", "intent": "new_task", "why": "explanation"}
Request: "Bài 1: Một ôtô dự định đi từ A đến B với vận tốc 40km/h.Lúc xuất phát ôtô chạy với vận tốc đó(40km/h) Nhưng khi còn 60km nữa thì được nửa quãng đường AB, ôtô tăng tốc ..."
-> {"kind": "other", "level": "L4", "intent": "new_task", "why": "math_reasoning"}
Request: "Hãy giả làm một Copywriter với 10 năm kinh nghiệm. Viết bài dài hơn 2000 từ với từ khóa mục tiêu [vi metamask la gi]. Bài viết 100% độc đáo, không đạo văn và được tối ..."
-> {"kind": "other", "level": "L5", "intent": "new_task", "why": "writing"}
Request: "Could you write me an android application that has a login page and can connect to a server"
-> {"kind": "coding", "level": "L5", "intent": "new_task", "why": "coding"}
Request: "tôi có Hồ sơ sức khỏe điện tử (EHR) tôi muốn áp dụng công nghệ AI và công nghệ IOT vào. hãy trình bày chi tiết cho tôi"
-> {"kind": "other", "level": "L5", "intent": "new_task", "why": "analysis_planning"}

### Output Format:
Return ONLY a valid JSON object with this exact schema:
{"kind": "coding" | "other", "level": "L0" | "L1" | "L2" | "L3" | "L4" | "L5" | "L6", "intent": "new_task" | "continue" | "refine" | "correction" | "meta", "why": "<concise reason, at most 10 words>"}"""


def _format_user_prompt(
    instruction_zone: str,
    artifact_present: bool,
    artifact_tokens: int,
    has_error_artifact: bool,
    previous_user_turn: str,
) -> str:
    return (
        f"### Input:\n"
        f"previous_user_turn: {previous_user_turn or '(none — this is the first turn)'}\n"
        f"instruction_zone: {instruction_zone}\n"
        f"artifact_present: {artifact_present}\n"
        f"artifact_tokens: {artifact_tokens}\n"
        f"has_error_artifact: {has_error_artifact}\n\n"
        f"Respond ONLY with JSON."
    )


class LRUCache:
    """In-memory LRU cache for classifier v2 decisions.

    ponytail: không khoá — chỉ an toàn trong một event loop một luồng, đúng cách
    gateway đang chạy. Cần chia sẻ giữa thread/worker thì đổi sang Redis, đừng thêm lock.
    """

    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def get(self, key: str) -> dict[str, Any] | None:
        if key not in self._cache:
            return None
        self._cache.move_to_end(key)
        return self._cache[key]

    def set(self, key: str, value: dict[str, Any]) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self.capacity:
            self._cache.popitem(last=False)

    def clear(self) -> None:
        self._cache.clear()


class ClassifierV2AI(BaseClassifier):
    """LLM-based coding difficulty classifier on 7-level scale L0–L6 (doc 12)."""

    def __init__(
        self,
        adapter: BaseAdapter | None = None,
        model_id: str | None = None,
        t1_max: int = DEFAULT_T1_MAX,
        t2_max: int = DEFAULT_T2_MAX,
        router_timeout_ms: int = 2500,
        fallback_classifier: ClassifierV1_5Heuristic | None = None,
        cache_capacity: int = 1000,
        pricing: dict[str, ModelPricing] | None = None,
        cache: LRUCache | None = None,
    ) -> None:
        self.adapter = adapter
        self.model_id = model_id or DEFAULT_MODEL
        # Contract B.2: đọc config đúng một lần trong constructor.
        if pricing is None:
            try:
                pricing = load_config().pricing
            except Exception:  # noqa: BLE001 — thiếu config không được làm hỏng routing
                pricing = {}
        self.model_pricing = pricing.get(self.model_id) or _UNKNOWN_MODEL_PRICING
        self.t1_max = t1_max
        self.t2_max = t2_max
        self.router_timeout_ms = router_timeout_ms
        self.fallback_classifier = fallback_classifier or ClassifierV1_5Heuristic(
            t1_max=t1_max,
            t2_max=t2_max,
            router_timeout_ms=router_timeout_ms,
        )
        # Cache phải sống QUA nhiều request. Instance v2 được dựng lại mỗi request
        # (chat_completions), nên cache riêng của instance = luôn rỗng, không bao giờ hit.
        # Nhận cache dùng chung từ app.state; chỉ tự tạo khi gọi lẻ (test/CLI).
        self._cache = cache or LRUCache(capacity=cache_capacity)

    async def classify(self, messages: list[Message]) -> ClassificationResult:
        started = time.perf_counter()
        prompt_text = self._prompt_text(messages)
        # Lượt user áp chót — intent cần nó để phán quan hệ (doc 13 §3). Cắt 200 ký tự.
        previous_user_turn = self._prev_user_text(messages)[:200]
        context_tokens = sum(_estimate_tokens(m.content or "") for m in messages)

        # Step 1: Text zoning (§6)
        instruction, artifact = split_zones(prompt_text)

        # Truncate instruction zone if > 1500 chars (900 first + 600 last)
        if len(instruction) > 1500:
            # Dấu phân cách để hai đoạn không dính liền thành từ giả ở mối nối.
            instruction_for_llm = instruction[:900] + "\n[...]\n" + instruction[-600:]
        else:
            instruction_for_llm = instruction

        artifact_present = bool(artifact.strip())
        artifact_tokens = _estimate_tokens(artifact)
        has_error_artifact = bool(_ERROR_ARTIFACT_RE.search(artifact))

        # Đề thi trắc nghiệm: cấu trúc rõ tới mức không cần hỏi LLM (issue #209).
        # Chặn ở đây thay vì trong prompt thì tiết kiệm cả token lẫn độ trễ — và
        # vẫn đúng khi LLM lỗi. Đo trên MMLU-Pro: bắt 415/420, không dính
        # HumanEval+ câu nào.
        if _MCQ_RE.search(prompt_text):
            return ClassificationResult(
                score=_LEVEL_ANCHORS["L5"],
                tier=self._to_tier(_LEVEL_ANCHORS["L5"]),
                signals=[Signal("genre_mcq", _LEVEL_ANCHORS["L5"])],
                classifier_version=CLASSIFIER_VERSION,
                latency_ms=self._elapsed_ms(started),
                cost_usd=Decimal("0"),
                intent=None,
            )

        # Check deadline before invoking adapter
        if self._elapsed_ms(started) > self.router_timeout_ms:
            return self._fallback_result(messages, started)

        # If no adapter configured, fallback immediately
        if not self.adapter:
            return self._fallback_result(messages, started)

        # Check LRU cache (§7.4)
        cache_key = self._cache_key(
            instruction_for_llm, artifact_present, artifact_tokens, has_error_artifact, previous_user_turn
        )
        cached_val = self._cache.get(cache_key)
        cost_usd = Decimal("0")

        parsed_response = cached_val
        if parsed_response is None:
            try:
                llm_messages = [
                    Message(role="system", content=_SYSTEM_PROMPT),
                    Message(
                        role="user",
                        content=_format_user_prompt(
                            instruction_zone=instruction_for_llm,
                            artifact_present=artifact_present,
                            artifact_tokens=artifact_tokens,
                            has_error_artifact=has_error_artifact,
                            previous_user_turn=previous_user_turn,
                        ),
                    ),
                ]
                is_reasoning = self.model_id.startswith(("gpt-5", "o1", "o3", "o4"))
                params = CompletionParams(
                    temperature=0.0,
                    max_tokens=500 if is_reasoning else 48,
                    extra={"reasoning_effort": "low"} if is_reasoning else {},
                )
                # Contract B.2 §2 — tự cắt trong ROUTER_TIMEOUT_MS. Không có wait_for thì
                # provider treo bao lâu, classify treo bấy lâu: kiểm deadline trước/sau
                # lời gọi không cắt được cái ở giữa.
                budget_s = (self.router_timeout_ms - self._elapsed_ms(started)) / 1000
                completion = await asyncio.wait_for(
                    self.adapter.complete(self.model_id, llm_messages, params), timeout=budget_s
                )

                if completion.usage:
                    # Estimate cost or record token usage
                    cost_usd = self._estimate_cost(completion.usage)

                parsed_response = self._parse_llm_json(completion.content)
                if parsed_response:
                    self._cache.set(cache_key, parsed_response)
            except Exception as exc:  # noqa: BLE001
                # TimeoutError có str() rỗng — log cả tên lớp, nếu không dòng log vô nghĩa.
                logger.warning("ClassifierV2 adapter call failed: %s: %s", type(exc).__name__, exc)
                return self._fallback_result(messages, started, cost_usd=cost_usd)

        if not parsed_response:
            return self._fallback_result(messages, started, cost_usd=cost_usd)

        # Có câu trả lời hợp lệ rồi thì KHÔNG kiểm deadline nữa: latency đã trả, tiền đã
        # trả. Vứt đi để chạy v1.5 chỉ làm chậm thêm chứ không cứu được gì.
        kind = parsed_response.get("kind")
        level = parsed_response.get("level")
        why = parsed_response.get("why", "")
        intent = parsed_response.get("intent")  # đã validate enum ở _parse_llm_json; None nếu vắng/lạ

        # Branch: kind == "other" (§7.2, §9) -> score from the LLM's own level (doc 14 §3.1)
        if kind == "other":
            if self._elapsed_ms(started) > self.router_timeout_ms:
                return self._fallback_result(messages, started, cost_usd=cost_usd)
            try:
                # doc 14 §3.1: chấm điểm THẲNG từ `level` của LLM, đối xứng với nhánh
                # coding (:329). Trước đây nhánh này vứt `level` đi rồi gọi heuristic
                # v1.5 đếm regex — prompt khó không có từ khoá bị chấm 0 → T1, đó là
                # phần còn lại của issue #194.
                #
                # KHÔNG dùng heuristic làm sàn (`max(llm, heuristic)`): sàn chỉ nâng
                # chứ không hạ, nên nó tước quyền của LLM khi LLM chấm một prompt là
                # rẻ — trái mục tiêu tiết kiệm. An toàn lo bằng guard level dưới đây.
                if level not in _LEVEL_ANCHORS:
                    return self._fallback_result(messages, started, cost_usd=cost_usd)

                score = _LEVEL_ANCHORS[level]
                if context_tokens > LONG_CONTEXT_TOKENS:
                    score += 6
                # Kẹp theo ceiling của chính level: modifier bối cảnh không được đẩy
                # prompt vượt tier, đúng luật "modifier không đổi tier" (doc 09 §6.1).
                score = max(0, min(_LEVEL_CEILINGS[level], score))

                signals = [
                    Signal(f"v2_level_{level}", _LEVEL_ANCHORS[level]),
                    Signal("v2_kind_other", 0),
                    Signal(f"v2_prompt_{PROMPT_REVISION}", 0),
                ]
                if context_tokens > LONG_CONTEXT_TOKENS:
                    signals.append(Signal("long_context", 6))
                self._log_why(why, kind, level)
                tier = self._to_tier(score)
                return ClassificationResult(
                    score=score,
                    tier=tier,
                    signals=signals,
                    classifier_version=CLASSIFIER_VERSION,
                    latency_ms=self._elapsed_ms(started),
                    cost_usd=cost_usd,
                    intent=intent,
                )
            except Exception:  # noqa: BLE001
                return self._fallback_result(messages, started, cost_usd=cost_usd)

        # Branch: kind == "coding"
        if level not in _LEVEL_ANCHORS:
            return self._fallback_result(messages, started, cost_usd=cost_usd)

        anchor = _LEVEL_ANCHORS[level]
        ceiling = _LEVEL_CEILINGS[level]

        # Compute CPU modifiers (§5.2)
        signals: list[Signal] = [
            Signal(f"v2_level_{level}", anchor),
            Signal(f"v2_prompt_{PROMPT_REVISION}", 0),
        ]
        self._log_why(why, kind, level)

        mod_total = 0
        for name, points in self._coding_modifiers(instruction, artifact, context_tokens, level):
            signals.append(Signal(name, points))
            mod_total += points

        # Score formula (§5.2)
        score = min(anchor + mod_total, ceiling)
        score = max(0, min(100, score))
        tier = self._to_tier(score)

        return ClassificationResult(
            score=score,
            tier=tier,
            signals=signals,
            classifier_version=CLASSIFIER_VERSION,
            latency_ms=self._elapsed_ms(started),
            cost_usd=cost_usd,
            intent=intent,
        )

    def _coding_modifiers(self, instruction: str, artifact: str, context_tokens: int, level: str):
        """CPU volume modifiers (§5.2) — capped at level ceiling."""
        if _ERROR_ARTIFACT_RE.search(artifact):
            yield "error_artifact", 8

        artifact_tokens = _estimate_tokens(artifact)
        if artifact_tokens > 150:
            yield "artifact_large", 6

        if _MULTI_FILE_RE.search(instruction) or len(_FILE_MENTION_RE.findall(instruction)) >= 2:
            yield "multi_file", 6

        if _OUTPUT_CONSTRAINT_RE.search(instruction):
            yield "output_constraint", 6

        # multi_step modifier for L1..L4 (§4.4 mapping to C1/C2)
        if level in ("L1", "L2", "L3", "L4"):
            if self.fallback_classifier._multi_step_points_v15(instruction, as_modifier=True):
                yield "multi_step", 6

        if context_tokens > LONG_CONTEXT_TOKENS:
            yield "long_context", 6

    def _parse_llm_json(self, raw_content: str) -> dict[str, Any] | None:
        """Extract and parse JSON object from LLM response."""
        if not raw_content:
            return None
        text = raw_content.strip()
        # Extract first {...} — handles markdown fences, preamble text, trailing prose.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
            if not isinstance(data, dict):
                return None
            kind = data.get("kind")
            level = data.get("level")
            if kind not in ("coding", "other"):
                return None
            if kind == "coding" and level not in _LEVEL_ANCHORS:
                return None
            # intent phụ: nhãn lạ/thiếu → bỏ về None, để regex fallback ở SessionRouter lo.
            if data.get("intent") not in _INTENTS:
                data["intent"] = None
            return data
        except Exception:
            return None

    def _cache_key(
        self,
        instruction: str,
        artifact_present: bool,
        artifact_tokens: int,
        has_error_artifact: bool,
        previous_user_turn: str,
    ) -> str:
        # intent phụ thuộc lượt trước (doc 13 §6) → phải vào khoá, nếu không cùng instruction
        # khác ngữ cảnh trước sẽ trả intent cache sai.
        payload = (
            f"{PROMPT_REVISION}:{instruction.strip()}:{artifact_present}:{artifact_tokens}"
            f":{has_error_artifact}:{previous_user_turn.strip()}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _log_why(self, why: str, kind: str | None, level: str | None) -> None:
        """`why` KHÔNG vào Signal.name.

        `name` là khoá phân loại — /healthz so bằng `==`, /admin/requests gom nhóm theo nó.
        Nhét text tự do của LLM vào đó là mỗi request một tên mới, cardinality vô hạn.
        Muốn hiện `why` trên dashboard thì phải thêm ô vào contract B.2, không phải mượn
        ô `name`.
        """
        if why:
            logger.info("ClassifierV2 kind=%s level=%s why=%r", kind, level, str(why)[:120])

    def _estimate_cost(self, usage) -> Decimal:
        """Giá từ pricing.yaml (§8.4) — đổi CLASSIFIER_V2_MODEL là router_cost_usd đi theo."""
        price = self.model_pricing
        prompt_cost = (Decimal(str(usage.prompt_tokens)) / Decimal("1000000")) * Decimal(
            str(price.input_per_1m_usd)
        )
        completion_cost = (Decimal(str(usage.completion_tokens)) / Decimal("1000000")) * Decimal(
            str(price.output_per_1m_usd)
        )
        return prompt_cost + completion_cost

    def _to_tier(self, score: int) -> Tier:
        if score < self.t1_max:
            return Tier.T1
        if score < self.t2_max:
            return Tier.T2
        return Tier.T3

    def _prompt_text(self, messages: list[Message]) -> str:
        for message in reversed(messages or []):
            if message.role == "user" and message.content:
                return message.content
        return ""

    def _prev_user_text(self, messages: list[Message]) -> str:
        """Lượt user áp chót (bỏ qua lượt cuối). '' nếu chỉ có một lượt user."""
        seen_last = False
        for message in reversed(messages or []):
            if message.role == "user" and message.content:
                if not seen_last:
                    seen_last = True
                    continue
                return message.content
        return ""

    def _elapsed_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)

    def _fallback_result(
        self, messages: list[Message], started: float, cost_usd: Decimal = Decimal("0")
    ) -> ClassificationResult:
        """Fallback to v1.5 heuristic (§9) with Signal('v2_fallback', 0)."""
        try:
            # Đồng hồ MỚI, không phải `started` của v2. v1.5._score tự gọi _check_deadline;
            # mà lý do ta rơi vào đây thường chính là v2 đã hết giờ — truyền đồng hồ cũ vào
            # là ép v1.5 raise ngay, rồi trả (45, T2, classifier_error). Doc 12 §9: v2 hỏng
            # phải cho ra ĐIỂM HEURISTIC v1.5, và không bao giờ phát classifier_error.
            v15_res = self.fallback_classifier._score(messages, time.perf_counter())
            score, v15_signals = v15_res
            tier = self._to_tier(score)
            signals = list(v15_signals) + [Signal("v2_fallback", 0)]
        except Exception:  # noqa: BLE001
            score = 45
            tier = Tier.T2
            signals = [Signal("classifier_error", 0), Signal("v2_fallback", 0)]

        return ClassificationResult(
            score=score,
            tier=tier,
            signals=signals,
            classifier_version=CLASSIFIER_VERSION,
            latency_ms=self._elapsed_ms(started),
            cost_usd=cost_usd,
        )
