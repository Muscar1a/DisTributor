"""Adversarial MCQ dataset for #211: false-positive structural exam detection.

#211 asks for negative cases where prompts LOOK like a multiple-choice exam
(lettered A) B) C) D) options in sequence) but are not one, specifically in
code, documents, lists, and casual chat. This file only validates the dataset
itself; `test_mcq_regex_matches_expected_labels_when_available` also checks it
against classifier v1.5's real detection regex (`_MCQ_RE`, from #210) once
that code exists on the checkout being tested.

That behavioral test is intentionally `xfail(strict=True)`, not a plain pass/fail
assertion — reviewer feedback (PR #217) on the reasoning: it calls the PRIVATE
`_MCQ_RE` pattern directly, so if #210 is later fixed by adding a filtering step
AFTER the regex (e.g. zoning/context checks on the classifier's public behavior)
rather than by changing the regex itself, this test would keep failing on an
implementation detail even though the classifier's real output became correct.
Scope call for this PR: ship the dataset + this documented gap now, keep the
actual detector fix as separate work stacked on top. `strict=True` means an
unexpected PASS here also fails the build — a reminder to remove the xfail
marker once #210 (or a follow-up) actually closes the gap, not a scenario where
progress on #210 slips past silently.
"""

import json
from pathlib import Path

import pytest

DATASET = Path(__file__).resolve().parents[1] / "datasets" / "mcq_false_positives.jsonl"

REQUIRED_FIELDS = {"id", "category", "language", "prompt", "expected_genre_mcq", "note"}
KNOWN_CATEGORIES = {"code", "danh_sach", "hoi_thoai", "tai_lieu", "control"}
# The four false-positive risk categories #211 names explicitly.
ISSUE_211_NEGATIVE_CATEGORIES = {"code", "tai_lieu", "danh_sach", "hoi_thoai"}


def _load_rows() -> list[dict]:
    return [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_dataset_has_enough_cases():
    rows = _load_rows()
    assert len(rows) >= 10


def test_every_row_has_required_fields_and_known_category():
    for row in _load_rows():
        missing = REQUIRED_FIELDS - row.keys()
        assert not missing, f"{row.get('id')}: missing {sorted(missing)}"
        assert row["category"] in KNOWN_CATEGORIES, f"{row['id']}: unknown category {row['category']!r}"
        assert isinstance(row["expected_genre_mcq"], bool), f"{row['id']}: expected_genre_mcq must be bool"
        assert row["prompt"].strip(), f"{row['id']}: prompt must not be empty"


def test_ids_are_unique():
    ids = [row["id"] for row in _load_rows()]
    assert len(ids) == len(set(ids))


def test_at_least_one_true_positive_control_exists():
    """A dataset of only negatives can't tell a broken detector from a disabled one."""
    rows = _load_rows()
    assert any(row["expected_genre_mcq"] is True for row in rows)


def test_all_four_issue_211_risk_categories_are_covered():
    rows = _load_rows()
    negative_categories = {row["category"] for row in rows if row["expected_genre_mcq"] is False}
    assert ISSUE_211_NEGATIVE_CATEGORIES <= negative_categories


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known gap in #210's _MCQ_RE (issue #211, PR #217): the regex fires on all 9 "
        "false-positive negatives in this dataset (code/tai_lieu/danh_sach/hoi_thoai), "
        "not just the 2 true-positive controls — #210's own commit only measured false "
        "positives against HumanEval+ (0/164), not these four categories. Verified via a "
        "throwaway git worktree on fix/issue-194-reasoning-genre before this dataset was "
        "committed. Remove this xfail once #210 (or a follow-up) actually filters these."
    ),
)
def test_mcq_regex_matches_expected_labels_when_available():
    """Once #210's structural MCQ detection lands, this starts exercising real behavior.

    Skipped (not xfail) when #210 isn't on the checkout at all — pytest reports a
    skip-inside-an-xfail-test as skipped, not xfail, so this stays a no-op until
    _MCQ_RE actually exists to test against.
    """
    try:
        from src.gateway.app.core.classifier_v1_5 import _MCQ_RE
    except ImportError:
        pytest.skip("Classifier v1.5 structural MCQ detection (#210) not present on this checkout")
    for row in _load_rows():
        matched = bool(_MCQ_RE.search(row["prompt"]))
        assert matched == row["expected_genre_mcq"], (
            f"{row['id']} ({row['category']}): regex matched={matched}, expected={row['expected_genre_mcq']}"
        )
