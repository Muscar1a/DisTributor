"""Regrade cached three-arm MATH outcomes with symbolic answer equivalence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.evals.benchmarks.objective import verify_math_answer


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def successful_run(row: dict[str, Any], arm: str) -> dict[str, Any]:
    run = row.get(arm)
    if not isinstance(run, dict) or run.get("error") or not run.get("content"):
        raise ValueError(f"{row.get('id')}: missing successful {arm} response")
    return run


def grade_three_arm(
    dataset_path: Path,
    paired_path: Path,
    nano_path: Path,
    low_label: str = "all_nano",
    classifier_label: str = "classifier_v1_5",
    high_label: str = "all_strong",
) -> dict[str, Any]:
    dataset_rows = load_jsonl(dataset_path)
    paired_rows = load_jsonl(paired_path)
    nano_rows = load_jsonl(nano_path)
    records = {str(row["id"]): row for row in dataset_rows}
    paired = {str(row["id"]): row for row in paired_rows}
    nano = {str(row["id"]): row for row in nano_rows}
    expected_ids = set(records)
    if len(records) != len(dataset_rows):
        raise ValueError("dataset contains duplicate IDs")
    if len(paired) != len(paired_rows) or len(nano) != len(nano_rows):
        raise ValueError("outcome cache contains duplicate IDs")
    if set(paired) != expected_ids or set(nano) != expected_ids:
        raise ValueError("dataset, paired outcomes, and nano outcomes must contain identical IDs")

    results = []
    labels = (low_label, classifier_label, high_label)
    if len(set(labels)) != len(labels):
        raise ValueError("arm labels must be unique")
    correct = dict.fromkeys(labels, 0)
    for record_id in sorted(expected_ids):
        record = records[record_id]
        paired_row = paired[record_id]
        nano_row = nano[record_id]
        runs = {
            low_label: successful_run(nano_row, "strong"),
            classifier_label: successful_run(paired_row, "smart"),
            high_label: successful_run(paired_row, "strong"),
        }
        graded = {
            arm: verify_math_answer(str(run["content"]), str(record["reference_answer"])) for arm, run in runs.items()
        }
        for arm, passed in graded.items():
            correct[arm] += int(passed)
        results.append(
            {
                "id": record_id,
                "level": record.get("metadata", {}).get("level"),
                "subject": record.get("metadata", {}).get("subject"),
                **graded,
            }
        )
    n = len(results)
    return {
        "benchmark": "MATH-500",
        "grader": "math-verify==0.9.0",
        "n": n,
        "correct": correct,
        "accuracy": {arm: count / n for arm, count in correct.items()},
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--paired", type=Path, required=True)
    parser.add_argument("--nano", type=Path, required=True)
    parser.add_argument("--low-label", default="all_nano")
    parser.add_argument("--classifier-label", default="classifier_v1_5")
    parser.add_argument("--high-label", default="all_strong")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = grade_three_arm(
        args.dataset,
        args.paired,
        args.nano,
        args.low_label,
        args.classifier_label,
        args.high_label,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"MATH-500 N={summary['n']}: "
        + ", ".join(f"{arm}={accuracy:.2%}" for arm, accuracy in summary["accuracy"].items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
