"""Bất biến độ dài cho issue #194 — doc 14 §7.

Bộ `length_bias_pairs.jsonl` gồm các cặp prompt **cùng nội dung, khác độ dài**.
Định nghĩa "sửa xong" của #194 là: với mọi cặp, bản viết gọn và bản viết dài
phải ra cùng một tier, và đúng tier kỳ vọng.

Chạy trên classifier v2 với LLM giả lập nên không cần API key.
"""

import asyncio
import json
from collections import defaultdict
from pathlib import Path

import pytest

from src.gateway.app.core.classifier_v2 import ClassifierV2AI
from src.gateway.app.core.interfaces import Message, Tier

DATASET = Path(__file__).resolve().parents[1] / "datasets" / "length_bias_pairs.jsonl"

REQUIRED_FIELDS = {"pair_id", "form", "prompt", "language", "category", "expected_tier"}

# Level mà LLM được kỳ vọng chấm cho từng tier — dùng để giả lập.
# Đây KHÔNG phải khẳng định LLM thật sẽ chấm đúng như vậy; độ chuẩn của LLM đo
# bằng benchmark riêng (#209). Test này chỉ chốt: khi LLM đã chấm một mức, thì
# độ dài văn bản không được làm đổi tier.
_LEVEL_FOR_TIER = {"T1": "L1", "T2": "L3", "T3": "L5"}


def load_rows() -> list[dict]:
    with DATASET.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def classify_with_level(prompt: str, level: str):
    from src.gateway.tests.test_classifier_v2 import FakeLLMAdapter

    adapter = FakeLLMAdapter(
        response_text=f'{{"kind": "other", "level": "{level}", "intent": "new_task", "why": "t"}}'
    )
    clf = ClassifierV2AI(adapter=adapter)
    return asyncio.run(clf.classify([Message(role="user", content=prompt)]))


def test_dataset_shape():
    """Mỗi cặp phải có đúng một bản gọn và một bản dài, đủ trường."""
    rows = load_rows()
    assert rows, "dataset rỗng"

    by_pair = defaultdict(list)
    for index, row in enumerate(rows, start=1):
        missing = REQUIRED_FIELDS - row.keys()
        assert not missing, f"dòng {index}: thiếu trường {sorted(missing)}"
        assert row["form"] in {"concise", "padded"}, f"dòng {index}: form lạ {row['form']!r}"
        assert row["expected_tier"] in {"T1", "T2", "T3"}, f"dòng {index}: tier lạ"
        by_pair[row["pair_id"]].append(row)

    for pair_id, group in by_pair.items():
        forms = sorted(item["form"] for item in group)
        assert forms == ["concise", "padded"], f"{pair_id}: cần đúng 2 bản, nhận {forms}"
        tiers = {item["expected_tier"] for item in group}
        assert len(tiers) == 1, f"{pair_id}: hai bản khai tier khác nhau {tiers}"


def test_padded_thuc_su_dai_hon():
    """Bản 'padded' phải dài hơn hẳn — nếu không thì cặp này không kiểm được gì."""
    by_pair = defaultdict(dict)
    for row in load_rows():
        by_pair[row["pair_id"]][row["form"]] = row["prompt"]

    for pair_id, forms in by_pair.items():
        concise, padded = len(forms["concise"]), len(forms["padded"])
        assert padded > concise * 2, (
            f"{pair_id}: bản dài chỉ {padded} ký tự so với {concise} — chưa đủ chênh để lộ length bias"
        )


@pytest.mark.parametrize("pair_id", sorted({row["pair_id"] for row in load_rows()}))
def test_ngan_va_dai_cung_tier(pair_id):
    """Bất biến chính của #194: cùng nội dung, khác độ dài, cùng tier."""
    group = {row["form"]: row for row in load_rows() if row["pair_id"] == pair_id}
    expected = group["concise"]["expected_tier"]
    level = _LEVEL_FOR_TIER[expected]

    res_concise = classify_with_level(group["concise"]["prompt"], level)
    res_padded = classify_with_level(group["padded"]["prompt"], level)

    assert res_concise.tier is res_padded.tier, (
        f"{pair_id}: gọn={res_concise.tier.value} dài={res_padded.tier.value}"
    )
    assert res_concise.tier is Tier(expected), (
        f"{pair_id}: kỳ vọng {expected}, nhận {res_concise.tier.value}"
    )
