"""Nạp corpus load test từ hai bộ dữ liệu gốc của team.

Không tự viết prompt nữa. Hai nguồn duy nhất:

  * `src/evals/datasets/mixed_200.jsonl`   — 200 prompt một lượt, đã gán nhãn
    difficulty easy/medium/hard và expected_tier. Phân bố THẬT là 46/65/89
    (≈23/33/45), không phải 40/35/25 như PRD §11 đặt ra làm mục tiêu — dùng
    `resample_to_prd_mix()` nếu muốn ép về đúng tỉ lệ tài liệu.
  * `src/evals/datasets/multiturn_30.jsonl` — 18 hội thoại 2–4 lượt, mỗi lượt có
    expected_intent và expected_tier. Tên file ghi 30 nhưng thực tế 18 dòng.

Cả hai bộ đang ở trạng thái `pending_human_review` (chưa qua cổng nghiệm thu
người của issue #122). Với load test thì không sao — ta cần HÌNH DẠNG của lưu
lượng, không cần nhãn đúng. Nhưng đừng lấy số ở đây làm bằng chứng chất lượng.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASET_DIR = _REPO_ROOT / "src" / "evals" / "datasets"
SINGLE_TURN_PATH = _DATASET_DIR / "mixed_200.jsonl"
MULTI_TURN_PATH = _DATASET_DIR / "multiturn_30.jsonl"

# Trần input của gateway là 8000 token (config.yaml), ước lượng ~4 ký tự/token.
# Chừa biên cho phần role + message assistant tích luỹ ở hội thoại nhiều lượt.
MAX_INPUT_TOKENS = 8000
_SINGLE_TURN_TOKEN_CAP = 7000
_CONVERSATION_TOKEN_CAP = 5000

# MockAdapter ném lỗi khi thấy các chuỗi này — lọt vào corpus là số liệu hỏng.
_ERROR_TRIGGERS = ("#force_429", "#force_500", "#force_timeout", "#force_filter", "#force_400")

# PRD §11 đặt mục tiêu phân bố cho bộ eval; giữ lại để ép tỉ lệ khi cần so sánh.
PRD_MIX = {"easy": 40, "medium": 35, "hard": 25}


def _estimate_tokens(text: str) -> int:
    """Cùng heuristic với `TokenEstimator` của gateway (~4 ký tự/token)."""
    return max(1, (len(text) + 3) // 4) if text else 0


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str
    difficulty: str
    expected_tier: str
    category: str
    language: str


@dataclass(frozen=True)
class Conversation:
    id: str
    scenario: str
    language: str
    turns: tuple[tuple[str, str], ...]  # (nội dung user, expected_tier)
    adversarial: bool


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"Không tìm thấy bộ dữ liệu {path}. Load test đọc dataset của repo, "
            f"không tự sinh prompt — chạy từ bản checkout đầy đủ."
        )
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_single_turn(path: Path | None = None) -> list[Prompt]:
    """Đọc mixed_200.jsonl, giữ nguyên phân bố gốc của bộ dữ liệu."""
    rows = _read_jsonl(path or SINGLE_TURN_PATH)
    out: list[Prompt] = []
    for row in rows:
        text = (row.get("prompt") or "").strip()
        if not text:
            continue
        if any(trigger in text for trigger in _ERROR_TRIGGERS):
            continue
        if _estimate_tokens(text) > _SINGLE_TURN_TOKEN_CAP:
            # Gateway trả 400 context_too_long trước khi vào router -> không đo được gì.
            continue
        out.append(
            Prompt(
                id=row.get("id", ""),
                text=text,
                difficulty=row.get("difficulty", "unknown"),
                expected_tier=row.get("expected_tier", ""),
                category=row.get("category", ""),
                language=row.get("language", ""),
            )
        )
    if not out:
        raise ValueError(f"{path or SINGLE_TURN_PATH} không còn prompt nào sau khi lọc.")
    return out


def resample_to_prd_mix(prompts: list[Prompt], mix: dict[str, int] | None = None) -> list[Prompt]:
    """Nhân bản theo tỉ lệ PRD 40/35/25 thay vì phân bố tự nhiên của bộ dữ liệu.

    Nhân bản (chứ không rút ngẫu nhiên) để mỗi lần chạy dùng đúng một phân phối,
    không lệch theo may rủi của seed.
    """
    mix = mix or PRD_MIX
    by_difficulty: dict[str, list[Prompt]] = {}
    for prompt in prompts:
        by_difficulty.setdefault(prompt.difficulty, []).append(prompt)

    out: list[Prompt] = []
    for difficulty, weight in mix.items():
        bucket = by_difficulty.get(difficulty)
        if not bucket:
            continue
        for i in range(weight):
            out.append(bucket[i % len(bucket)])
    return out or list(prompts)


def load_conversations(path: Path | None = None, include_adversarial: bool = True) -> list[Conversation]:
    """Đọc multiturn_30.jsonl thành các hội thoại nhiều lượt."""
    rows = _read_jsonl(path or MULTI_TURN_PATH)
    out: list[Conversation] = []
    for row in rows:
        turns_raw = row.get("turns") or []
        adversarial = row.get("adversarial_case") is not None
        if adversarial and not include_adversarial:
            continue

        turns: list[tuple[str, str]] = []
        skip = False
        total_tokens = 0
        for turn in turns_raw:
            text = (turn.get("user") or "").strip()
            if not text or any(trigger in text for trigger in _ERROR_TRIGGERS):
                skip = True
                break
            total_tokens += _estimate_tokens(text)
            turns.append((text, turn.get("expected_tier", "")))

        # Lượt sau mang theo toàn bộ lịch sử -> tổng cả hội thoại mới là input thật.
        if skip or len(turns) < 2 or total_tokens > _CONVERSATION_TOKEN_CAP:
            continue

        out.append(
            Conversation(
                id=row.get("id", ""),
                scenario=row.get("scenario", ""),
                language=row.get("language", ""),
                turns=tuple(turns),
                adversarial=adversarial,
            )
        )
    if not out:
        raise ValueError(f"{path or MULTI_TURN_PATH} không còn hội thoại nào sau khi lọc.")
    return out


def describe(prompts: list[Prompt], conversations: list[Conversation]) -> str:
    counts: dict[str, int] = {}
    for prompt in prompts:
        counts[prompt.difficulty] = counts.get(prompt.difficulty, 0) + 1
    mix = " / ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    turns = sum(len(c.turns) for c in conversations)
    return (
        f"{len(prompts)} prompt một lượt ({mix}); "
        f"{len(conversations)} hội thoại / {turns} lượt"
    )
