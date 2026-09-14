"""Download and normalize a pinned slice of MATH-500 or MMLU-Pro."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.evals.benchmarks.objective import normalize_math500, normalize_mmlu_pro

SPECS = {
    "math500": {
        "dataset": "HuggingFaceH4/MATH-500",
        "split": "test",
        "license": "not-declared-in-dataset-card",
        "normalizer": normalize_math500,
    },
    "mmlu-pro": {
        "dataset": "TIGER-Lab/MMLU-Pro",
        "split": "test",
        "license": "mit",
        "normalizer": normalize_mmlu_pro,
    },
}


def select_stratified(records: list[dict[str, Any]], per_category: int, seed: str) -> list[dict[str, Any]]:
    """Select a stable, balanced sample by hashing ``seed`` with each record ID."""
    if per_category < 1:
        raise ValueError("per_category must be positive")
    if not seed:
        raise ValueError("seed must not be empty")

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[str(record["category"])].append(record)
    if not groups:
        raise ValueError("cannot stratify an empty dataset")

    selected: list[dict[str, Any]] = []
    for category, candidates in sorted(groups.items()):
        if len(candidates) < per_category:
            raise ValueError(f"category {category!r} has {len(candidates)} records; need {per_category}")
        ranked = sorted(
            candidates,
            key=lambda record: hashlib.sha256(f"{seed}|{record['id']}".encode()).hexdigest(),
        )
        for record in ranked[:per_category]:
            sampled = dict(record)
            sampled["sample_selection"] = {
                "method": "sha256_rank_per_category",
                "seed": seed,
                "per_category": per_category,
            }
            selected.append(sampled)
    return sorted(selected, key=lambda record: (str(record["category"]), str(record["id"])))


def prepare(
    name: str,
    output: Path,
    revision: str,
    limit: int | None,
    per_category: int | None = None,
    seed: str = "mmlu-pro-stratified-v1",
) -> int:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError("Install src/evals/requirements.txt before downloading benchmarks") from exc

    spec = SPECS[name]
    dataset = load_dataset(spec["dataset"], split=spec["split"], revision=revision)
    rows = dataset if limit is None or per_category is not None else dataset.select(range(min(limit, len(dataset))))
    normalized_rows = []
    for index, row in enumerate(rows):
        normalized = spec["normalizer"](dict(row), index)
        normalized["source_dataset"] = spec["dataset"]
        normalized["source_revision"] = revision
        normalized["source_split"] = spec["split"]
        normalized["source_license"] = spec["license"]
        normalized_rows.append(normalized)
    if per_category is not None:
        if name != "mmlu-pro":
            raise ValueError("per-category sampling is only supported for mmlu-pro")
        normalized_rows = select_stratified(normalized_rows, per_category, seed)

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for normalized in normalized_rows:
            handle.write(json.dumps(normalized, ensure_ascii=False) + "\n")
    return len(normalized_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", choices=sorted(SPECS))
    parser.add_argument("--revision", required=True, help="Pinned Hugging Face commit SHA")
    parser.add_argument("--output", type=Path, required=True)
    sample_group = parser.add_mutually_exclusive_group()
    sample_group.add_argument("--limit", type=int)
    sample_group.add_argument(
        "--per-category",
        type=int,
        help="Select this many records per category using deterministic hash ranking",
    )
    parser.add_argument(
        "--seed",
        default="mmlu-pro-stratified-v1",
        help="Sampling seed used with --per-category",
    )
    args = parser.parse_args()
    count = prepare(
        args.benchmark,
        args.output,
        args.revision,
        args.limit,
        args.per_category,
        args.seed,
    )
    print(f"Wrote {args.output} ({count} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
