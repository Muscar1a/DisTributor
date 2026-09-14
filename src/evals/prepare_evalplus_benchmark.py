"""Prepare a pinned HumanEval+ subset for SmartRoute generation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def prepare(output: Path, limit: int) -> int:
    try:
        from evalplus.data import get_human_eval_plus, get_human_eval_plus_hash
    except ImportError as exc:
        raise RuntimeError("Install src/evals/requirements.txt before preparing EvalPlus") from exc

    problems = get_human_eval_plus()
    dataset_hash = get_human_eval_plus_hash()
    selected = list(problems.items())[:limit]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for task_id, problem in selected:
            prompt = (
                problem["prompt"]
                + "\nComplete the function above. Return only the complete Python source code, "
                "without Markdown fences or explanation."
            )
            row = {
                "id": task_id,
                "task_id": task_id,
                "benchmark": "HumanEval+",
                "prompt": prompt,
                "grader": "evalplus_humaneval_v0.3.1",
                "quality_type": "objective",
                "expected_tier": "T2",
                "category": "coding",
                "language": "en",
                "metadata": {
                    "entry_point": problem["entry_point"],
                    "tier_label_source": "provisional_default_not_used_for_pass_at_1",
                },
                "source_dataset": "evalplus/HumanEvalPlus",
                "source_revision": dataset_hash,
                "source_split": "test",
                "source_license": "mit",
            }
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(selected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    count = prepare(args.output, args.limit)
    print(f"Wrote {args.output} ({count} HumanEval+ records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
