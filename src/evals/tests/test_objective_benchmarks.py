import json
from pathlib import Path

import pytest

from src.evals.benchmarks.objective import (
    extract_boxed,
    extract_python_code,
    grade_response,
    normalize_math500,
    normalize_mmlu_pro,
    verify_math_answer,
)
from src.evals.grade_math_three_arm import grade_three_arm
from src.evals.prepare_standard_benchmark import select_stratified
from src.evals.run_answer_quality_eval import (
    RequestPacer,
    build_parser,
    completed_ids,
    load_normalized_records,
)


def test_math500_normalization_and_nested_box_grading():
    row = {
        "problem": "Compute it",
        "solution": "Thus \\boxed{\\frac{1}{2}}",
        "subject": "Algebra",
        "level": 5,
        "unique_id": "x",
    }
    normalized = normalize_math500(row, 0)
    assert normalized["reference_answer"] == "\\frac{1}{2}"
    assert normalized["expected_tier"] == "T3"
    assert normalized["grader"] == "math_verify_v1"
    assert extract_boxed("work \\boxed{\\frac{1}{2}}") == "\\frac{1}{2}"
    assert grade_response("math_normalized_exact_v1", "$\\boxed{\\dfrac{1}{2}}$", "\\frac{1}{2}")


def test_math_verify_accepts_equivalent_boxed_answers():
    assert verify_math_answer("work \\boxed{x=2}", "2")
    assert verify_math_answer("work \\boxed{120^\\circ}", "120")
    assert verify_math_answer("work \\boxed{\\frac{2240}{78125}}", "\\frac{448}{15625}")
    assert verify_math_answer("work \\boxed{\\$78}", "78")
    assert not verify_math_answer("work \\boxed{9999}", "9901")


def test_math_three_arm_regrade_uses_symbolic_equivalence(tmp_path: Path):
    dataset = tmp_path / "dataset.jsonl"
    paired = tmp_path / "paired.jsonl"
    nano = tmp_path / "nano.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "math-1",
                "reference_answer": "2",
                "metadata": {"level": 1, "subject": "Algebra"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    paired.write_text(
        json.dumps(
            {
                "id": "math-1",
                "smart": {"content": "\\boxed{x=2}", "error": None},
                "strong": {"content": "\\boxed{2}", "error": None},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    nano.write_text(
        json.dumps({"id": "math-1", "strong": {"content": "\\boxed{3}", "error": None}}) + "\n",
        encoding="utf-8",
    )

    summary = grade_three_arm(dataset, paired, nano)

    assert summary["correct"] == {"all_nano": 0, "classifier_v1_5": 1, "all_strong": 1}
    custom = grade_three_arm(
        dataset,
        paired,
        nano,
        "all_gpt_4o_mini",
        "classifier_v2",
        "all_gpt_4o",
    )
    assert custom["correct"] == {
        "all_gpt_4o_mini": 0,
        "classifier_v2": 1,
        "all_gpt_4o": 1,
    }


def test_mmlu_pro_formats_choices_and_grades_verbose_answer():
    normalized = normalize_mmlu_pro(
        {"question_id": 7, "question": "Pick", "options": ["x", "y", "z"], "answer_index": 1},
        0,
    )
    assert "A. x" in normalized["prompt"]
    assert normalized["reference_answer"] == "B"
    assert grade_response("multiple_choice_v1", "The answer is B.", "B")


def test_stratified_selection_is_balanced_stable_and_annotated():
    records = [
        {"id": f"{category}-{index}", "category": category} for category in ("biology", "math") for index in range(5)
    ]

    first = select_stratified(records, per_category=2, seed="fixed")
    second = select_stratified(list(reversed(records)), per_category=2, seed="fixed")

    assert first == second
    assert [record["category"] for record in first].count("biology") == 2
    assert [record["category"] for record in first].count("math") == 2
    assert all(
        record["sample_selection"]
        == {
            "method": "sha256_rank_per_category",
            "seed": "fixed",
            "per_category": 2,
        }
        for record in first
    )
    assert all("sample_selection" not in record for record in records)


def test_stratified_selection_rejects_undersized_category():
    with pytest.raises(ValueError, match="need 2"):
        select_stratified([{"id": "only", "category": "math"}], 2, "fixed")


def test_resume_and_normalized_validation(tmp_path):
    output = tmp_path / "outcomes.jsonl"
    output.write_text(
        "\n".join(
            [
                json.dumps({"id": "legacy-done"}),
                json.dumps(
                    {
                        "id": "failed",
                        "smart": {"content": None, "error": "rate limited"},
                        "strong": {"content": "B", "error": None},
                    }
                ),
                json.dumps(
                    {
                        "id": "done",
                        "smart": {"content": "A", "error": None},
                        "strong": {"content": "B", "error": None},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    assert completed_ids(output) == {"legacy-done", "done"}

    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(json.dumps({"id": "broken"}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing fields"):
        load_normalized_records(dataset)

    missing_reference = {
        "id": "objective",
        "prompt": "Pick one",
        "grader": "multiple_choice_v1",
        "quality_type": "objective",
        "expected_tier": "T1",
    }
    dataset.write_text(json.dumps(missing_reference) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="reference_answer"):
        load_normalized_records(dataset)

    missing_reference["grader"] = "evalplus_humaneval_v0.3.1"
    dataset.write_text(json.dumps(missing_reference) + "\n", encoding="utf-8")
    assert load_normalized_records(dataset) == [missing_reference]


def test_request_pacer_rejects_non_positive_rate():
    with pytest.raises(ValueError, match="greater than zero"):
        RequestPacer(0).wait()


def test_answer_quality_runner_accepts_classifier_v2():
    args = build_parser().parse_args(
        ["--dataset", "dataset.jsonl", "--output", "outcomes.jsonl", "--classifier-version", "v2"]
    )
    assert args.classifier_version == "v2"


def test_extract_python_code_removes_markdown_fence():
    assert extract_python_code("Here:\n```python\ndef add(a, b):\n    return a + b\n```") == (
        "def add(a, b):\n    return a + b"
    )
