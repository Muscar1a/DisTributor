# Issue 52 Gold Dataset and Developer Interviews Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tạo bản nháp có provenance của 200 prompt thực Việt–Anh, công cụ kiểm tra/rebuild, bộ phỏng vấn ẩn danh và báo cáo H1/H3 trung thực cho issue #52.

**Architecture:** WildChat được đọc streaming ở revision cố định, lọc thành hai candidate pool rồi lấy mẫu deterministic 100 prompt mỗi ngôn ngữ. Dataset JSONL giữ schema phẳng tương thích issue #49; validator phân biệt bản nháp AI-assisted với Gold Dataset đã được người thật duyệt. Interview responses là dữ liệu nhập riêng, còn report được sinh từ dataset/responses để không thể kết luận H1/H3 khi thiếu bằng chứng.

**Tech Stack:** Python 3.11 standard library, `datasets>=4.8,<5`, JSON Schema Draft 2020-12, JSONL, CSV, Markdown, pytest.

## Global Constraints

- Nguồn duy nhất cho mẫu H1 là `allenai/WildChat-1M` revision `7d6490e462285cf85d91eabea0f9a954fbddcd1f`.
- Giấy phép derivative dataset là `ODC-BY-1.0`; phải giữ attribution và URL license.
- Dataset có đúng 200 record: 100 `vi` và 100 `en`.
- Chỉ lấy user turn đầu tiên, `toxic == false`, prompt text-only, không rỗng, không trùng và không vượt 16.000 token ước lượng.
- Nhãn Codex giữ trạng thái `ai_assisted_pending_human_review`; không tự chuyển thành `human_verified` hoặc `human_revised`.
- Interview CSV không chứa dòng giả, tên, email, công ty hoặc raw transcript.
- H1 chỉ là preliminary khi còn nhãn chưa human-review; H3 là `NOT TESTED` khi có dưới ba phản hồi consented.
- Không sửa classifier, adapter, gateway runtime, pricing, `mixed_50.jsonl` hoặc `run_eval.py`.
- Không đóng issue #52 cho đến khi strict gold validation pass, có ít nhất ba interview thật và Member 1 đã nhận schema handoff.

---

### Task 1: Khóa schema, provenance và gửi đề xuất đồng bộ cho Member 1

**Files:**
- Create: `src/evals/datasets/schema.json`
- Create: `src/evals/datasets/sources.md`

**Interfaces:**
- Consumes: Design spec `docs/superpowers/specs/2026-08-13-issue-52-gold-dataset-interviews-design.md`.
- Produces: JSON Schema Draft 2020-12 với 15 field bắt buộc; provenance/attribution dùng bởi dataset, validator và Member 1.

- [ ] **Step 1: Chạy kiểm tra trước thay đổi**

```powershell
@'
import json
from pathlib import Path

schema_path = Path("src/evals/datasets/schema.json")
assert schema_path.exists(), schema_path
schema = json.loads(schema_path.read_text(encoding="utf-8"))
assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
assert {"prompt", "expected_tier", "category"} <= set(schema["required"])
'@ | python -
```

Expected: FAIL vì `schema.json` chưa tồn tại.

- [ ] **Step 2: Tạo JSON Schema chính xác**

Tạo `src/evals/datasets/schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/AI20K-Build-Phase-Cohort-3/P-156/blob/TrungHieu/src/evals/datasets/schema.json",
  "title": "SmartRoute mixed_200 record",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "id", "prompt", "language", "category", "difficulty", "expected_tier",
    "source_dataset", "source_revision", "source_record_id", "source_url", "license",
    "pii_review_status", "annotation_status", "annotator", "annotation_notes"
  ],
  "properties": {
    "id": {"type": "string", "pattern": "^wc-(vi|en)-[0-9]{3}$"},
    "prompt": {"type": "string", "minLength": 1},
    "language": {"enum": ["vi", "en"]},
    "category": {"enum": ["chitchat", "factual_qa", "explanation", "translation", "summarization", "information_extraction", "writing", "coding", "math_reasoning", "analysis_planning", "other"]},
    "difficulty": {"enum": ["easy", "medium", "hard"]},
    "expected_tier": {"enum": ["T1", "T2", "T3"]},
    "source_dataset": {"const": "allenai/WildChat-1M"},
    "source_revision": {"const": "7d6490e462285cf85d91eabea0f9a954fbddcd1f"},
    "source_record_id": {"type": "string", "minLength": 34},
    "source_url": {"const": "https://huggingface.co/datasets/allenai/WildChat-1M"},
    "license": {"const": "ODC-BY-1.0"},
    "pii_review_status": {"enum": ["pending_human_review", "human_verified"]},
    "annotation_status": {"enum": ["ai_assisted_pending_human_review", "human_verified", "human_revised"]},
    "annotator": {"type": "string", "minLength": 1},
    "annotation_notes": {"type": "string"}
  }
}
```

- [ ] **Step 3: Tạo tài liệu provenance và license notice**

Tạo `src/evals/datasets/sources.md` với nội dung bắt buộc:

```markdown
# Dataset sources and provenance

## Selected source

- Dataset: [allenai/WildChat-1M](https://huggingface.co/datasets/allenai/WildChat-1M)
- Revision: `7d6490e462285cf85d91eabea0f9a954fbddcd1f`
- License: [ODC Attribution 1.0](https://opendatacommons.org/licenses/by/1-0/)
- Accessed: `2026-08-13`

Contains information from WildChat-1M, made available under the ODC Attribution License.
```

Sau notice, ghi quota 100 vi/100 en, first-user-turn, non-toxic/text-only/dedup/PII filters, human-review gate, giới hạn suy rộng H1 và danh sách nguồn đã loại: LMSYS/Kaggle Chatbot Arena, Dolly 15K, Natural Questions, UIT-ViQuAD 2.0, GSM8K, MBPP.

- [ ] **Step 4: Kiểm tra schema và provenance**

```powershell
@'
import json
from pathlib import Path

schema = json.loads(Path("src/evals/datasets/schema.json").read_text(encoding="utf-8"))
assert schema["additionalProperties"] is False
assert len(schema["required"]) == 15
assert schema["properties"]["source_revision"]["const"] == "7d6490e462285cf85d91eabea0f9a954fbddcd1f"

sources = Path("src/evals/datasets/sources.md").read_text(encoding="utf-8")
for expected in ("WildChat-1M", "ODC Attribution", "2026-08-13", "Kaggle", "Natural Questions", "UIT-ViQuAD", "GSM8K", "MBPP"):
    assert expected in sources, expected
'@ | python -
```

Expected: PASS, không có output.

- [ ] **Step 5: Gửi schema proposal lên issue #49**

```powershell
$body = @'
@hungtranvg62 Mình đề xuất schema dùng chung cho handoff #52 -> #49.

Core fields mà mini-eval có thể đọc trực tiếp: `id`, `prompt`, `expected_tier`, `category`.
Metadata bổ sung: `language`, `difficulty`, provenance/license và trạng thái human review.
Enum difficulty-tier cố định: easy/T1, medium/T2, hard/T3.
`mixed_50.jsonl` nên là subset theo `id` từ `mixed_200.jsonl`, không rewrite prompt.

Design spec: `docs/superpowers/specs/2026-08-13-issue-52-gold-dataset-interviews-design.md`
Schema: `src/evals/datasets/schema.json`

Nhờ bạn xác nhận schema này hoặc nêu breaking change cần điều chỉnh trước khi trích mini-eval.
'@
gh issue comment 49 --repo AI20K-Build-Phase-Cohort-3/P-156 --body $body
```

Expected: GitHub trả URL bình luận mới. Ghi URL để bàn giao; không tuyên bố Member 1 đã đồng ý cho đến khi có phản hồi.

- [ ] **Step 6: Commit schema và provenance**

```powershell
git add src/evals/datasets/schema.json src/evals/datasets/sources.md
git commit -m "docs(eval): define issue 52 dataset schema"
```

### Task 2: Xây dựng sampling pipeline deterministic bằng TDD

**Files:**
- Create: `src/evals/requirements.txt`
- Create: `src/evals/build_mixed_200.py`
- Create: `src/evals/tests/test_dataset_tools.py`

**Interfaces:**
- Consumes: WildChat rows có `language`, `toxic`, `conversation_hash`, `conversation`.
- Produces:
  - `normalize_prompt(text: str) -> str`
  - `contains_obvious_pii(text: str) -> bool`
  - `candidate_from_row(row: dict[str, object]) -> dict[str, str] | None`
  - `collect_candidate_pools(rows, pool_size=200) -> dict[str, list[dict[str, str]]]`
  - `sample_candidates(pools, per_language=100, seed=52) -> list[dict[str, object]]`
  - CLI ghi `src/evals/datasets/mixed_200.jsonl`.

- [ ] **Step 1: Viết failing tests cho normalize, privacy filter và sampling**

Tạo `src/evals/tests/test_dataset_tools.py`:

```python
from src.evals.build_mixed_200 import (
    candidate_from_row,
    contains_obvious_pii,
    normalize_prompt,
    sample_candidates,
)


def _row(language: str, content: str, *, toxic: bool = False, record_id: str = "a" * 32) -> dict:
    return {
        "language": language,
        "toxic": toxic,
        "conversation_hash": record_id,
        "conversation": [
            {"role": "user", "content": content, "turn_identifier": f"turn-{record_id}"},
            {"role": "assistant", "content": "response", "turn_identifier": "assistant-turn"},
        ],
    }


def test_normalize_prompt_unicode_and_whitespace():
    assert normalize_prompt("  Xin   chào\n bạn  ") == "Xin chào bạn"


def test_obvious_pii_and_secret_patterns():
    assert contains_obvious_pii("email me at user@example.com")
    assert contains_obvious_pii("key sk-abcdefghijklmnopqrstuvwxyz123456")
    assert contains_obvious_pii("server 192.168.10.20")
    assert not contains_obvious_pii("Giải bài toán 123 + 456")


def test_candidate_uses_first_user_turn_and_normalizes_language():
    candidate = candidate_from_row(_row("Vietnamese", "  Xin   chào "))
    assert candidate == {
        "prompt": "Xin chào",
        "language": "vi",
        "source_record_id": f"{'a' * 32}:turn-{'a' * 32}",
    }


def test_candidate_rejects_toxic_pii_empty_and_missing_media():
    assert candidate_from_row(_row("English", "hello", toxic=True)) is None
    assert candidate_from_row(_row("English", "contact user@example.com")) is None
    assert candidate_from_row(_row("English", "   ")) is None
    assert candidate_from_row(_row("English", "What is in this attached image?")) is None


def test_sampling_is_deterministic_and_balanced():
    pools = {
        "vi": [{"prompt": f"vi {i}", "language": "vi", "source_record_id": f"vi:{i}"} for i in range(5)],
        "en": [{"prompt": f"en {i}", "language": "en", "source_record_id": f"en:{i}"} for i in range(5)],
    }
    first = sample_candidates(pools, per_language=3, seed=52)
    assert first == sample_candidates(pools, per_language=3, seed=52)
    assert [row["language"] for row in first].count("vi") == 3
    assert [row["language"] for row in first].count("en") == 3
    assert [row["id"] for row in first] == ["wc-vi-001", "wc-vi-002", "wc-vi-003", "wc-en-001", "wc-en-002", "wc-en-003"]
```

- [ ] **Step 2: Chạy tests để xác nhận fail**

```powershell
python -m pytest src/evals/tests/test_dataset_tools.py -v
```

Expected: FAIL khi import `src.evals.build_mixed_200`.

- [ ] **Step 3: Khai báo dependency riêng cho eval build**

Tạo `src/evals/requirements.txt`:

```text
datasets>=4.8,<5
```

Không thêm `datasets` vào gateway runtime requirements.

- [ ] **Step 4: Implement sampling core tối thiểu**

Tạo `src/evals/build_mixed_200.py` với các import standard library ở module scope; import `datasets.load_dataset` bên trong `main()` để unit tests không buộc phải tải dependency/network:

```python
import argparse
import json
import random
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any
```

Khai báo các constants:

```python
SOURCE_DATASET = "allenai/WildChat-1M"
SOURCE_REVISION = "7d6490e462285cf85d91eabea0f9a954fbddcd1f"
SOURCE_URL = "https://huggingface.co/datasets/allenai/WildChat-1M"
SOURCE_LICENSE = "ODC-BY-1.0"
LANGUAGE_MAP = {"Vietnamese": "vi", "English": "en"}
LANGUAGE_ORDER = ("vi", "en")
TIER_BY_DIFFICULTY = {"easy": "T1", "medium": "T2", "hard": "T3"}
```

Implement normalize/filter:

```python
_PII_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{8,}\d)(?!\d)"),
)
_MISSING_MEDIA = re.compile(
    r"\b(this|the|attached|uploaded)\s+(image|photo|audio|file|document)\b|"
    r"\b(hình|ảnh|tệp|file)\s+(này|đính kèm|đã tải lên)\b",
    re.IGNORECASE,
)


def normalize_prompt(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def estimate_tokens(text: str) -> int:
    return max(int(len(text.split()) * 1.3), len(text) // 4)


def contains_obvious_pii(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PII_PATTERNS)


def candidate_from_row(row: dict[str, Any]) -> dict[str, str] | None:
    language = LANGUAGE_MAP.get(str(row.get("language")))
    if language is None or row.get("toxic") is not False:
        return None
    messages = row.get("conversation") or []
    user = next((message for message in messages if message.get("role") == "user"), None)
    if not user:
        return None
    prompt = normalize_prompt(str(user.get("content") or ""))
    if not prompt or estimate_tokens(prompt) > 16_000:
        return None
    if contains_obvious_pii(prompt) or _MISSING_MEDIA.search(prompt):
        return None
    conversation_hash = str(row.get("conversation_hash") or "")
    turn_identifier = str(user.get("turn_identifier") or "")
    if not conversation_hash or not turn_identifier:
        return None
    return {"prompt": prompt, "language": language, "source_record_id": f"{conversation_hash}:{turn_identifier}"}
```

Implement pool và sampling:

```python
def collect_candidate_pools(rows: Iterable[dict[str, Any]], pool_size: int = 200) -> dict[str, list[dict[str, str]]]:
    pools = {language: [] for language in LANGUAGE_ORDER}
    seen: set[str] = set()
    for row in rows:
        candidate = candidate_from_row(row)
        if candidate is None:
            continue
        key = candidate["prompt"].casefold()
        if key in seen:
            continue
        seen.add(key)
        language = candidate["language"]
        if len(pools[language]) < pool_size:
            pools[language].append(candidate)
        if all(len(pool) >= pool_size for pool in pools.values()):
            return pools
    missing = {language: pool_size - len(pool) for language, pool in pools.items() if len(pool) < pool_size}
    raise ValueError(f"stream ended before candidate pools were full: {missing}")


def sample_candidates(pools: dict[str, list[dict[str, str]]], per_language: int = 100, seed: int = 52) -> list[dict[str, object]]:
    rng = random.Random(seed)
    records: list[dict[str, object]] = []
    for language in LANGUAGE_ORDER:
        selected = rng.sample(pools[language], per_language)
        selected.sort(key=lambda row: row["source_record_id"])
        for index, candidate in enumerate(selected, start=1):
            records.append({
                "id": f"wc-{language}-{index:03d}",
                "prompt": candidate["prompt"],
                "language": language,
                "category": "other",
                "difficulty": "medium",
                "expected_tier": "T2",
                "source_dataset": SOURCE_DATASET,
                "source_revision": SOURCE_REVISION,
                "source_record_id": candidate["source_record_id"],
                "source_url": SOURCE_URL,
                "license": SOURCE_LICENSE,
                "pii_review_status": "pending_human_review",
                "annotation_status": "ai_assisted_pending_human_review",
                "annotator": "codex-draft",
                "annotation_notes": "",
            })
    return records
```

CLI phải gọi:

```python
def write_jsonl(records: list[dict[str, object]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
    output.write_text(payload, encoding="utf-8")


def main() -> None:
    from datasets import load_dataset

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("src/evals/datasets/mixed_200.jsonl"))
    parser.add_argument("--pool-size", type=int, default=200)
    parser.add_argument("--per-language", type=int, default=100)
    parser.add_argument("--seed", type=int, default=52)
    args = parser.parse_args()

    rows = load_dataset(SOURCE_DATASET, split="train", revision=SOURCE_REVISION, streaming=True)
    pools = collect_candidate_pools(rows, pool_size=args.pool_size)
    records = sample_candidates(pools, per_language=args.per_language, seed=args.seed)
    write_jsonl(records, args.output)
    print(f"wrote {len(records)} records to {args.output}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Chạy unit tests**

```powershell
python -m pytest src/evals/tests/test_dataset_tools.py -v
```

Expected: 5 tests PASS.

- [ ] **Step 6: Commit sampling pipeline**

```powershell
git add src/evals/requirements.txt src/evals/build_mixed_200.py src/evals/tests/test_dataset_tools.py
git commit -m "feat(eval): add reproducible WildChat sampler"
```

### Task 3: Tạo 200 prompt thật và gán nhãn AI-assisted theo rubric

**Files:**
- Replace: `src/evals/datasets/mixed_200.jsonl`
- Modify: `src/evals/build_mixed_200.py`
- Modify: `src/evals/tests/test_dataset_tools.py`

**Interfaces:**
- Consumes: Sampling CLI từ Task 2 và rubric trong design spec.
- Produces: 200 record thực có draft category/difficulty, giữ nguyên hai status chờ human review.

- [ ] **Step 1: Cài dependency eval nếu môi trường chưa có**

```powershell
python -m pip install -r src/evals/requirements.txt
```

Expected: `datasets>=4.8,<5` khả dụng; không thay gateway dependencies.

- [ ] **Step 2: Chạy build từ revision đã ghim**

```powershell
python src/evals/build_mixed_200.py --output src/evals/datasets/mixed_200.jsonl --pool-size 200 --per-language 100 --seed 52
```

Expected: `wrote 200 records`; không tải/commit toàn bộ WildChat.

- [ ] **Step 3: Kiểm tra nhanh output trước annotation**

```powershell
@'
import json
from collections import Counter
from pathlib import Path

rows = [json.loads(line) for line in Path("src/evals/datasets/mixed_200.jsonl").read_text(encoding="utf-8").splitlines()]
assert len(rows) == 200
assert Counter(row["language"] for row in rows) == {"vi": 100, "en": 100}
assert len({row["id"] for row in rows}) == 200
assert len({row["source_record_id"] for row in rows}) == 200
assert all(row["annotation_status"] == "ai_assisted_pending_human_review" for row in rows)
assert all(row["pii_review_status"] == "pending_human_review" for row in rows)
'@ | python -
```

Expected: PASS.

- [ ] **Step 4: Thêm cơ chế preserve annotation khi rebuild**

Viết test:

```python
from src.evals.build_mixed_200 import merge_existing_annotations


def test_merge_existing_annotations_preserves_only_review_fields():
    fresh = [{"source_record_id": "x", "prompt": "new", "category": "other", "difficulty": "medium", "expected_tier": "T2", "annotation_status": "ai_assisted_pending_human_review", "annotator": "codex-draft", "annotation_notes": "", "pii_review_status": "pending_human_review"}]
    existing = [{"source_record_id": "x", "prompt": "old", "category": "coding", "difficulty": "hard", "expected_tier": "T3", "annotation_status": "ai_assisted_pending_human_review", "annotator": "codex-draft", "annotation_notes": "multi-step debugging", "pii_review_status": "pending_human_review"}]
    merged = merge_existing_annotations(fresh, existing)
    assert merged[0]["prompt"] == "new"
    assert merged[0]["category"] == "coding"
    assert merged[0]["difficulty"] == "hard"
    assert merged[0]["expected_tier"] == "T3"
```

Implement `merge_existing_annotations()` chỉ copy `category`, `difficulty`, `expected_tier`, `annotation_status`, `annotator`, `annotation_notes`, `pii_review_status` theo `source_record_id`. Thêm CLI flag `--preserve-annotations-from PATH`; không preserve prompt/provenance.

- [ ] **Step 5: Review AI-assisted theo bốn batch 50 record**

Với từng batch `wc-vi-001..050`, `wc-vi-051..100`, `wc-en-001..050`, `wc-en-051..100`:

1. Đọc prompt.
2. Chọn đúng một category trong schema.
3. Áp rubric Easy/Medium/Hard độc lập với classifier runtime.
4. Đặt tier theo mapping cố định.
5. Ghi `annotation_notes` khi case khó phân loại hoặc có rủi ro context.
6. Loại và thay candidate nếu thấy PII/secret hoặc phụ thuộc media còn sót.
7. Giữ `annotation_status=ai_assisted_pending_human_review`, `pii_review_status=pending_human_review` và `annotator=codex-draft`.

Sau mỗi batch chạy:

```powershell
@'
import json
from pathlib import Path

rows = [json.loads(line) for line in Path("src/evals/datasets/mixed_200.jsonl").read_text(encoding="utf-8").splitlines()]
mapping = {"easy": "T1", "medium": "T2", "hard": "T3"}
assert all(mapping[row["difficulty"]] == row["expected_tier"] for row in rows)
assert all(row["annotation_status"] == "ai_assisted_pending_human_review" for row in rows)
'@ | python -
```

- [ ] **Step 6: Chạy sampling tests và commit dataset draft**

```powershell
python -m pytest src/evals/tests/test_dataset_tools.py -v
git add src/evals/build_mixed_200.py src/evals/tests/test_dataset_tools.py src/evals/datasets/mixed_200.jsonl
git commit -m "feat(eval): add 200 bilingual WildChat prompts"
```

### Task 4: Tạo validator và human annotation review gate bằng TDD

**Files:**
- Create: `src/evals/validate_dataset.py`
- Create: `src/evals/datasets/annotation_review.md`
- Modify: `src/evals/tests/test_dataset_tools.py`

**Interfaces:**
- Consumes: JSONL record schema của Task 1 và dataset của Task 3.
- Produces `load_jsonl(path)`, `validate_records(records, require_gold=False) -> ValidationResult` và CLI exit 0/1.

- [ ] **Step 1: Viết failing tests cho validator**

Nối vào test file:

```python
from src.evals.validate_dataset import validate_records


def _valid_record(index: int, language: str) -> dict:
    return {
        "id": f"wc-{language}-{index:03d}",
        "prompt": f"prompt {language} {index}",
        "language": language,
        "category": "factual_qa",
        "difficulty": "easy",
        "expected_tier": "T1",
        "source_dataset": "allenai/WildChat-1M",
        "source_revision": "7d6490e462285cf85d91eabea0f9a954fbddcd1f",
        "source_record_id": f"{'a' * 32}:{language}-{index}",
        "source_url": "https://huggingface.co/datasets/allenai/WildChat-1M",
        "license": "ODC-BY-1.0",
        "pii_review_status": "pending_human_review",
        "annotation_status": "ai_assisted_pending_human_review",
        "annotator": "codex-draft",
        "annotation_notes": "",
    }


def _valid_200() -> list[dict]:
    return [_valid_record(i, language) for language in ("vi", "en") for i in range(1, 101)]


def test_regular_validation_accepts_draft_and_reports_pending():
    result = validate_records(_valid_200())
    assert result.errors == []
    assert result.stats["pending_annotation_review"] == 200
    assert result.stats["language"] == {"vi": 100, "en": 100}


def test_strict_gold_validation_rejects_pending_review():
    result = validate_records(_valid_200(), require_gold=True)
    assert "200 records still need annotation review" in result.errors
    assert "200 records still need PII review" in result.errors


def test_validator_rejects_duplicate_prompt_and_tier_mismatch():
    rows = _valid_200()
    rows[1]["prompt"] = rows[0]["prompt"]
    rows[2]["expected_tier"] = "T3"
    result = validate_records(rows)
    assert any("duplicate prompt" in error for error in result.errors)
    assert any("difficulty-tier mismatch" in error for error in result.errors)


def test_strict_gold_passes_after_human_review():
    rows = _valid_200()
    for row in rows:
        row["pii_review_status"] = "human_verified"
        row["annotation_status"] = "human_verified"
        row["annotator"] = "reviewer-01"
    assert validate_records(rows, require_gold=True).errors == []
```

- [ ] **Step 2: Chạy test để xác nhận fail**

```powershell
python -m pytest src/evals/tests/test_dataset_tools.py -v
```

Expected: FAIL khi import `src.evals.validate_dataset`.

- [ ] **Step 3: Implement validator bằng standard library**

Tạo `src/evals/validate_dataset.py` với:

```python
@dataclass
class ValidationResult:
    errors: list[str]
    warnings: list[str]
    stats: dict[str, Any]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: {exc.msg}") from exc
    return rows
```

`validate_records()` phải kiểm tra exact required fields, 200 record, quota ngôn ngữ, unique ID/source/prompt, PII pattern, enums, difficulty-tier mapping, pinned provenance, và `human_revised` phải có notes. Trong strict mode, `annotator` không được còn là `codex-draft`. Thống kê:

```python
stats = {
    "records": len(records),
    "language": dict(Counter(row["language"] for row in records)),
    "difficulty": dict(Counter(row["difficulty"] for row in records)),
    "category": dict(Counter(row["category"] for row in records)),
    "pending_annotation_review": pending_annotation,
    "pending_pii_review": pending_pii,
}
```

Trong regular mode, pending review đi vào `warnings`; với `require_gold=True`, thêm exact errors:

```python
errors.append(f"{pending_annotation} records still need annotation review")
errors.append(f"{pending_pii} records still need PII review")
```

CLI:

```python
parser.add_argument("dataset", type=Path, nargs="?", default=Path("src/evals/datasets/mixed_200.jsonl"))
parser.add_argument("--require-gold", action="store_true")
parser.add_argument("--json", action="store_true", dest="as_json")
```

In `{errors, warnings, stats}` và exit 1 khi `errors` không rỗng.

- [ ] **Step 4: Tạo human review guide**

Tạo `src/evals/datasets/annotation_review.md` gồm rubric, enum, bốn batch ID, hướng dẫn sửa đồng bộ difficulty-tier, không thay provenance, không lưu PII và hai lệnh:

```powershell
python src/evals/validate_dataset.py
python src/evals/validate_dataset.py --require-gold
```

Giải thích lệnh thứ hai phải fail trước khi người thật review đủ 200 dòng.

- [ ] **Step 5: Chạy tests và validator thực**

```powershell
python -m pytest src/evals/tests/test_dataset_tools.py -v
python src/evals/validate_dataset.py --json
python src/evals/validate_dataset.py --require-gold
```

Expected: tests PASS; validator thường exit 0 với `records=200`, `vi=100`, `en=100`; strict validator exit 1 với đúng 200 pending annotation và PII review.

- [ ] **Step 6: Commit validator và review workflow**

```powershell
git add src/evals/validate_dataset.py src/evals/datasets/annotation_review.md src/evals/tests/test_dataset_tools.py
git commit -m "test(eval): add gold dataset validation gates"
```

### Task 5: Tạo interview kit và sinh phần báo cáo issue #52 bằng TDD

**Files:**

- Create: `src/evals/interviews/developer_interview_guide.md`
- Create: `src/evals/interviews/responses.csv`
- Create: `src/evals/build_hypothesis_report.py`
- Modify: `src/evals/report.md`
- Modify: `src/evals/tests/test_dataset_tools.py`

- [ ] **Step 1: Viết test fail cho trạng thái H1/H3 và managed report section**

Thêm vào `src/evals/tests/test_dataset_tools.py`:

```python
from src.evals.build_hypothesis_report import render_issue_52_section, replace_managed_section


def test_report_is_preliminary_and_h3_not_tested_without_humans():
    section = render_issue_52_section(_valid_200(), [])
    assert "H1: PRELIMINARY" in section
    assert "H3: NOT TESTED" in section
    assert "0/3" in section


def test_report_summarizes_three_consented_interviews():
    interviews = [
        {
            "participant_id": "DEV-01",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "100-300",
            "desired_log_fields": "tier;signals;latency",
        },
        {
            "participant_id": "DEV-02",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "100-300",
            "desired_log_fields": "tier;cost;latency",
        },
        {
            "participant_id": "DEV-03",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "301-500",
            "desired_log_fields": "signals;fallback_chain;error",
        },
    ]
    section = render_issue_52_section(_valid_200(), interviews)
    assert "H3: TESTED" in section
    assert "3/3" in section
    assert "2/3" in section
    assert "Mode band: 100-300 ms" in section


def test_h1_is_supported_only_after_review_and_within_target_range():
    rows = _valid_200()
    for index, row in enumerate(rows):
        row["pii_review_status"] = "human_verified"
        row["annotation_status"] = "human_verified"
        row["annotator"] = "reviewer-01"
        if index >= 130:
            row["difficulty"] = "hard"
            row["expected_tier"] = "T3"
    section = render_issue_52_section(rows, [])
    assert "H1: SUPPORTED" in section
    assert "65.0%" in section


def test_replace_managed_section_is_idempotent():
    report = "# Report\n\n<!-- issue-52:start -->\nold\n<!-- issue-52:end -->\n"
    updated = replace_managed_section(report, "new")
    assert replace_managed_section(updated, "new") == updated
    assert "old" not in updated
    assert "new" in updated
```

- [ ] **Step 2: Chạy test để xác nhận fail**

```powershell
python -m pytest src/evals/tests/test_dataset_tools.py -v
```

Expected: FAIL khi import `src.evals.build_hypothesis_report`.

- [ ] **Step 3: Tạo interview guide và CSV chỉ có header**

`src/evals/interviews/responses.csv` phải có đúng một dòng header, chưa có participant giả:

```csv
participant_id,interview_date,role_band,experience_band,llm_integration_frequency,current_e2e_latency_band,acceptable_router_overhead_band,latency_sensitive_cases,cost_quality_preference,desired_log_fields,privacy_debugging_concerns,consent_to_aggregate
```

`src/evals/interviews/developer_interview_guide.md` phải có:

1. Mục đích H3 và routing-log requirements.
2. Script xin phép ghi nhận câu trả lời dưới dạng tổng hợp, không lưu tên/email/công ty.
3. Câu sàng lọc role, experience và tần suất tích hợp LLM.
4. Mức latency hiện tại và acceptable router overhead với enum `<100`, `100-300`, `301-500`, `501-1000`, `>1000` ms.
5. Tình huống nhạy latency và trade-off cost/quality.
6. Các trường log mong muốn: request ID, timestamp, tier, score/signals/reason, policy, selected model/provider, fallback chain, latency, token, estimated cost, error và content redaction.
7. Lo ngại privacy/debugging.
8. Checklist sau phỏng vấn: gán ID `DEV-NN`, điền CSV, kiểm tra consent và không ghi PII.

- [ ] **Step 4: Implement report generator**

Tạo `src/evals/build_hypothesis_report.py` bằng standard library với các interface:

```python
START = "<!-- issue-52:start -->"
END = "<!-- issue-52:end -->"


def load_interviews(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def valid_consented_interviews(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row.get("participant_id", "").strip()
        and row.get("consent_to_aggregate", "").strip().lower() == "yes"
    ]
```

`render_issue_52_section(records, interviews)` phải:

- Gọi `validate_records(records)` và từ chối sinh report nếu dataset có structural errors.
- Thống kê tổng số prompt, `vi/en`, Easy/Medium/Hard, category và tỷ lệ Easy+Medium.
- Tính tỷ lệ Easy+Medium và so trực tiếp với khoảng H1 `60–70%` trong PRD.
- Gắn `H1: PRELIMINARY` khi annotation hoặc PII còn pending. Sau human review đầy đủ, gắn `H1: SUPPORTED` nếu tỷ lệ nằm trong khoảng 60–70% (inclusive), ngược lại `H1: NOT SUPPORTED`; luôn in tỷ lệ thực thay vì làm tròn để ép vào khoảng.
- Nêu rõ mẫu là stratified 100 vi + 100 en, không được diễn giải là phân phối tự nhiên của toàn bộ WildChat.
- Chỉ tính các interview có `consent_to_aggregate=yes` và participant ID không rỗng.
- Gắn `H3: TESTED` khi có ít nhất 3 interview hợp lệ; nếu chưa đủ thì `H3: NOT TESTED` và hiển thị `N/3`.
- Khi đã có tối thiểu 3 interview, ánh xạ các band theo thứ tự `<100`, `100-300`, `301-500`, `501-1000`, `>1000`; công bố median band, mode band (hoặc `no unique mode`), số người chấp nhận overhead dưới hoặc bằng 300 ms và tần suất từng `desired_log_fields`; không suy diễn vượt quá mẫu nhỏ 3–5 người.

Đoạn status cốt lõi:

```python
reviewed = (
    validation.stats["pending_annotation_review"] == 0
    and validation.stats["pending_pii_review"] == 0
)
easy_medium_pct = 100 * sum(
    row["difficulty"] in {"easy", "medium"} for row in records
) / len(records)
consented = valid_consented_interviews(interviews)
under_300 = sum(
    row["acceptable_router_overhead_band"] in {"<100", "100-300"}
    for row in consented
)
h1_status = "PRELIMINARY"
if reviewed:
    h1_status = "SUPPORTED" if 60 <= easy_medium_pct <= 70 else "NOT SUPPORTED"
h3_status = "TESTED" if len(consented) >= 3 else "NOT TESTED"
```

Median band dùng vị trí giữa phía dưới trong thứ tự enum khi số interview là chẵn; mode chỉ công bố khi có duy nhất một band có tần suất cao nhất, nếu hòa thì ghi `no unique mode`. Log fields được tách theo dấu `;`, trim whitespace rồi đếm theo participant.

`replace_managed_section(report, section)` phải thay nội dung giữa `START`/`END`; nếu marker chưa có thì append một lần ở cuối file. Chạy lại với cùng dữ liệu phải không tạo diff.

CLI mặc định:

```python
parser.add_argument("--dataset", type=Path, default=Path("src/evals/datasets/mixed_200.jsonl"))
parser.add_argument("--interviews", type=Path, default=Path("src/evals/interviews/responses.csv"))
parser.add_argument("--report", type=Path, default=Path("src/evals/report.md"))
```

- [ ] **Step 5: Chạy test và sinh report ở trạng thái trung thực hiện tại**

```powershell
python -m pytest src/evals/tests/test_dataset_tools.py -v
python src/evals/build_hypothesis_report.py
$before = (Get-FileHash 'src/evals/report.md' -Algorithm SHA256).Hash
python src/evals/build_hypothesis_report.py
$after = (Get-FileHash 'src/evals/report.md' -Algorithm SHA256).Hash
if ($before -ne $after) { throw 'report generator is not idempotent' }
```

Expected: tests PASS; lần chạy generator thứ hai không tạo thêm thay đổi. Report phải ghi `H1: PRELIMINARY`, `H3: NOT TESTED`, `0/3`, cùng số liệu dataset; không được chứa kết luận phỏng vấn giả.

- [ ] **Step 6: Kiểm tra interview kit và commit**

```powershell
$rows = Import-Csv 'src/evals/interviews/responses.csv'
if ($rows.Count -ne 0) { throw 'responses.csv must be empty before real interviews' }
rg -n "consent|<100|100-300|routing|privacy" src/evals/interviews/developer_interview_guide.md
git diff --check
git add src/evals/interviews src/evals/build_hypothesis_report.py src/evals/report.md src/evals/tests/test_dataset_tools.py
git commit -m "docs(eval): add issue 52 interview and report workflow"
```

### Task 6: Verification, GitHub progress update và handoff các human gate

**Files:**

- Verify: `src/evals/datasets/mixed_200.jsonl`
- Verify: `src/evals/interviews/responses.csv`
- Verify: `src/evals/report.md`

- [ ] **Step 1: Chạy toàn bộ kiểm tra tự động**

```powershell
python -m pytest src/evals/tests/test_dataset_tools.py -v
python src/evals/validate_dataset.py --json
python src/evals/build_hypothesis_report.py
git diff --check
git status --short
```

Expected: tests PASS; regular validator exit 0 và báo đúng 200 prompt, 100 vi, 100 en. Chỉ các file dự kiến mới được thay đổi.

- [ ] **Step 2: Chạy strict gold gate và ghi nhận trạng thái thật**

```powershell
python src/evals/validate_dataset.py --require-gold
```

Expected trước human review: exit 1, báo số dòng pending annotation/PII. Đây là expected gate, không sửa status sang `human_verified` chỉ để làm lệnh pass.

- [ ] **Step 3: Xác nhận chưa có phỏng vấn giả và report chưa kết luận H3**

```powershell
$rows = Import-Csv 'src/evals/interviews/responses.csv'
if ($rows.Count -ne 0) { throw 'Only real, consented interviews may be committed' }
rg -n "H3: NOT TESTED|0/3" src/evals/report.md
```

Expected ở lần bàn giao đầu: CSV rỗng và report có cả hai marker trên.

- [ ] **Step 4: Đăng progress comment lên issue #52, không đóng issue**

```powershell
$body = @'
Đã hoàn tất phần có thể tự động hóa theo design đã duyệt:

- Tạo 200 prompt từ WildChat revision đã pin, cân bằng 100 vi / 100 en và lưu provenance.
- Thêm schema, nguồn dữ liệu, annotation rubric và validator.
- Thêm interview guide, CSV chỉ có header và report generator.
- Đồng bộ schema/subset contract với issue #49 và @hungtranvg62.

Human gates còn lại trước khi đạt acceptance criteria:

1. Người thật review đủ 200 nhãn và PII status; strict validator phải pass.
2. Phỏng vấn thật ít nhất 3 developer có consent.
3. Chạy lại report generator để chuyển H1/H3 sang trạng thái dựa trên bằng chứng.

Không có interview hoặc trạng thái human_verified giả được thêm vào repository. Issue #52 vẫn cần để mở cho đến khi hoàn tất các gate trên.
'@
gh issue comment 52 --repo AI20K-Build-Phase-Cohort-3/P-156 --body $body
```

- [ ] **Step 5: Bàn giao quy trình hoàn tất acceptance criteria**

Người thực hiện human review/phỏng vấn dùng đúng các lệnh sau sau khi cập nhật dataset và CSV:

```powershell
python src/evals/validate_dataset.py --require-gold
python src/evals/build_hypothesis_report.py
python -m pytest src/evals/tests/test_dataset_tools.py -v
git diff --check
```

Chỉ khi strict validator pass, report có ít nhất `3/3` interview thật và review thấy không có PII thì mới commit phần evidence, yêu cầu Member 1 xác nhận `mixed_50.jsonl` là subset của revision mới, và đóng issue #52.
