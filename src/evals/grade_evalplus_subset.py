"""Grade HumanEval+ outputs; run this script inside the official EvalPlus Docker image."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from evalplus.data import get_human_eval_plus, get_human_eval_plus_hash
from evalplus.evaluate import PASS, check_correctness, get_groundtruth

from src.evals.benchmarks.objective import extract_python_code


def _solution(problem: dict[str, Any], response: str) -> str:
    code = extract_python_code(response)
    full_source = re.search(
        r"^\s*(?:from\s+\S+\s+import|import\s+\S+|def\s+\w+|class\s+\w+|@\w+)",
        code,
        re.MULTILINE,
    )
    return code if full_source else problem["prompt"] + code


def grade(
    outcomes_path: Path,
    output_path: Path,
    expected_dataset_hash: str | None = None,
) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in outcomes_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    recorded_revisions = {row.get("source_revision") for row in rows if row.get("source_revision")}
    if len(recorded_revisions) > 1:
        raise ValueError(f"Outcomes contain multiple dataset revisions: {sorted(recorded_revisions)}")
    recorded_hash = next(iter(recorded_revisions), None)
    required_hash = expected_dataset_hash or recorded_hash
    installed_hash = get_human_eval_plus_hash()
    if required_hash is None:
        raise ValueError(
            "Dataset hash is absent from outcomes; pass --dataset-hash for legacy result files"
        )
    if required_hash != installed_hash:
        raise ValueError(
            f"Dataset hash mismatch: outcomes require {required_hash}, grader has {installed_hash}"
        )
    all_problems = get_human_eval_plus()
    task_ids = [str(row["id"]) for row in rows]
    problems = {task_id: all_problems[task_id] for task_id in task_ids}
    subset_suffix = hashlib.sha256("\n".join(task_ids).encode()).hexdigest()[:12]
    expected = get_groundtruth(problems, f"{installed_hash}-subset-{subset_suffix}", [])

    graded_rows = []
    for row in rows:
        task_id = str(row["id"])
        problem = problems[task_id]
        graded_runs = {}
        for mode in ("smart", "strong"):
            run = row[mode]
            if run.get("error") or not run.get("content"):
                graded_runs[mode] = {"correct": None, "error": run.get("error") or "missing_content"}
                continue
            result = check_correctness(
                "humaneval",
                0,
                problem,
                _solution(problem, str(run["content"])),
                expected[task_id],
                identifier=f"{task_id}:{mode}",
            )
            graded_runs[mode] = {
                "correct": result["base"][0] == PASS and result["plus"][0] == PASS,
                "base_status": result["base"][0],
                "plus_status": result["plus"][0],
                "error": None,
            }
        graded_rows.append({"id": task_id, **graded_runs})

    valid_smart = [row["smart"]["correct"] for row in graded_rows if row["smart"]["correct"] is not None]
    valid_strong = [row["strong"]["correct"] for row in graded_rows if row["strong"]["correct"] is not None]
    smart_pass = sum(valid_smart) / len(valid_smart) if valid_smart else None
    strong_pass = sum(valid_strong) / len(valid_strong) if valid_strong else None
    summary = {
        "benchmark": "HumanEval+",
        "dataset_hash": installed_hash,
        "n": len(rows),
        "smart_valid": len(valid_smart),
        "strong_valid": len(valid_strong),
        "smart_pass_at_1": smart_pass,
        "strong_pass_at_1": strong_pass,
        "quality_retention": smart_pass / strong_pass if smart_pass is not None and strong_pass else None,
        "results": graded_rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-hash")
    args = parser.parse_args()
    summary = grade(args.outcomes, args.output, args.dataset_hash)
    print(
        f"HumanEval+ subset N={summary['n']}: smart={summary['smart_pass_at_1']}, "
        f"strong={summary['strong_pass_at_1']}, QR={summary['quality_retention']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
