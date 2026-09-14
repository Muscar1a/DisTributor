import argparse
import json
import random
import re
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

SOURCE_DATASET = "allenai/WildChat-1M"
SOURCE_REVISION = "7d6490e462285cf85d91eabea0f9a954fbddcd1f"
SOURCE_URL = "https://huggingface.co/datasets/allenai/WildChat-1M"
SOURCE_LICENSE = "ODC-BY-1.0"
LANGUAGE_MAP = {"Vietnamese": "vi", "English": "en"}
LANGUAGE_ORDER = ("vi", "en")
TIER_BY_DIFFICULTY = {"easy": "T1", "medium": "T2", "hard": "T3"}
ANNOTATION_FIELDS = (
    "category",
    "difficulty",
    "expected_tier",
    "annotation_status",
    "annotator",
    "annotation_notes",
    "pii_review_status",
)
DATASET_DIR = Path(__file__).resolve().parent / "datasets"
DEFAULT_DATASET_PATH = DATASET_DIR / "mixed_200.jsonl"
DEFAULT_POOL_EXCLUSIONS_PATH = DATASET_DIR / "mixed_200_pool_exclusions.txt"
DEFAULT_SELECTION_EXCLUSIONS_PATH = DATASET_DIR / "mixed_200_exclusions.txt"

_PII_PATTERNS = (
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bapi[_ -]?key[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_-]{20,}", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{8,}\d)(?!\d)"),
)
_MISSING_MEDIA = re.compile(
    r"\b(this|the|attached|uploaded)\s+(image|photo|audio|file|document)\b|"
    r"\b(?:i\s+)?attached\s+(?:an?\s+)?(?:image|photo|audio|file|document)\b|"
    r"\b(?:see|view)\s+(?:the\s+)?(?:image|photo|audio|file|document)\s+attached\b|"
    r"\b(hình|ảnh|tệp|file)\s+(này|đính kèm|đã tải lên)\b",
    re.IGNORECASE,
)
_YOUTUBE_URL = re.compile(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S*", re.IGNORECASE)
_YOUTUBE_DEPENDENCY = re.compile(r"\bwhat\s+does\b|\b(?:summarize|transcribe|watch|analy[sz]e)\b", re.IGNORECASE)
_SOURCE_RECORD_ID = re.compile(r"^[0-9a-f]{32}:[^\s:]+$")


def normalize_prompt(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def estimate_tokens(text: str) -> int:
    return max(int(len(text.split()) * 1.3), len(text) // 4)


def contains_obvious_pii(text: str) -> bool:
    return any(pattern.search(text) for pattern in _PII_PATTERNS)


def depends_on_missing_media(text: str) -> bool:
    return bool(_MISSING_MEDIA.search(text)) or bool(
        _YOUTUBE_URL.search(text) and _YOUTUBE_DEPENDENCY.search(_YOUTUBE_URL.sub("", text))
    )


def candidate_from_row(row: dict[str, Any]) -> dict[str, str] | None:
    if not isinstance(row, Mapping):
        return None
    language = LANGUAGE_MAP.get(str(row.get("language")))
    if language is None or row.get("toxic") is not False:
        return None
    messages = row.get("conversation")
    if not isinstance(messages, list) or not all(isinstance(message, Mapping) for message in messages):
        return None
    user = next((message for message in messages if message.get("role") == "user"), None)
    if not user:
        return None
    content = user.get("content")
    if not isinstance(content, str):
        return None
    prompt = normalize_prompt(content)
    if not prompt or estimate_tokens(prompt) > 16_000:
        return None
    if contains_obvious_pii(prompt) or depends_on_missing_media(prompt):
        return None
    conversation_hash = row.get("conversation_hash")
    turn_identifier = user.get("turn_identifier")
    valid_turn_identifier = (isinstance(turn_identifier, str) and bool(turn_identifier)) or (
        isinstance(turn_identifier, int) and not isinstance(turn_identifier, bool)
    )
    if (
        not isinstance(conversation_hash, str)
        or not conversation_hash
        or not valid_turn_identifier
    ):
        return None
    return {
        "prompt": prompt,
        "language": language,
        "source_record_id": f"{conversation_hash}:{str(turn_identifier)}",
    }


def collect_candidate_pools(
    rows: Iterable[dict[str, Any]],
    pool_size: int = 200,
    excluded_source_record_ids: set[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    pools = {language: [] for language in LANGUAGE_ORDER}
    excluded = excluded_source_record_ids or set()
    unmatched_exclusions = set(excluded)
    seen: set[str] = set()
    for row in rows:
        candidate = candidate_from_row(row)
        if candidate is None:
            continue
        if candidate["source_record_id"] in excluded:
            unmatched_exclusions.discard(candidate["source_record_id"])
            continue
        key = candidate["prompt"].casefold()
        if key in seen:
            continue
        seen.add(key)
        language = candidate["language"]
        if len(pools[language]) < pool_size:
            pools[language].append(candidate)
        if all(len(pool) >= pool_size for pool in pools.values()):
            if unmatched_exclusions:
                raise ValueError(f"pool exclusions not encountered: {sorted(unmatched_exclusions)}")
            return pools
    if unmatched_exclusions:
        raise ValueError(f"pool exclusions not encountered: {sorted(unmatched_exclusions)}")
    missing = {language: pool_size - len(pool) for language, pool in pools.items() if len(pool) < pool_size}
    raise ValueError(f"stream ended before candidate pools were full: {missing}")


def sample_candidates(
    pools: dict[str, list[dict[str, str]]],
    per_language: int = 100,
    seed: int = 52,
    excluded_source_record_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    rng = random.Random(seed)
    excluded = excluded_source_record_ids or set()
    pool_ids = {row["source_record_id"] for pool in pools.values() for row in pool}
    unmatched_exclusions = excluded - pool_ids
    if unmatched_exclusions:
        raise ValueError(f"selection exclusions not found in candidate pools: {sorted(unmatched_exclusions)}")
    records: list[dict[str, object]] = []
    for language in LANGUAGE_ORDER:
        selected = rng.sample(pools[language], per_language)
        selected_ids = {row["source_record_id"] for row in selected}
        kept = [row for row in selected if row["source_record_id"] not in excluded]
        needed = per_language - len(kept)
        unused = [
            row
            for row in pools[language]
            if row["source_record_id"] not in selected_ids and row["source_record_id"] not in excluded
        ]
        if len(unused) < needed:
            raise ValueError(f"not enough unused {language} candidates to replace {needed} exclusions")
        selected = kept + unused[:needed]
        selected.sort(key=lambda row: row["source_record_id"])
        for index, candidate in enumerate(selected, start=1):
            records.append(
                {
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
                }
            )
    return records


def load_source_record_ids(path: Path) -> set[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"exclusion file is empty: {path}")
    source_record_ids: set[str] = set()
    for line_number, line in enumerate(lines, start=1):
        source_record_id = line.strip()
        if not source_record_id:
            raise ValueError(f"blank line in exclusion file {path}:{line_number}")
        if not _SOURCE_RECORD_ID.fullmatch(source_record_id):
            raise ValueError(f"malformed source record ID in {path}:{line_number}: {source_record_id!r}")
        if source_record_id in source_record_ids:
            raise ValueError(f"duplicate source record ID in {path}:{line_number}: {source_record_id}")
        source_record_ids.add(source_record_id)
    return source_record_ids


def merge_existing_annotations(
    fresh: list[dict[str, object]], existing: list[dict[str, object]]
) -> list[dict[str, object]]:
    annotations = {row.get("source_record_id"): row for row in existing}
    merged = []
    for row in fresh:
        result = row.copy()
        previous = annotations.get(row.get("source_record_id"))
        if previous is not None:
            result.update({field: previous[field] for field in ANNOTATION_FIELDS if field in previous})
        merged.append(result)
    return merged


def write_jsonl(records: list[dict[str, object]], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n"
    output.write_text(payload, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_DATASET_PATH)
    parser.add_argument("--pool-size", type=int, default=200)
    parser.add_argument("--per-language", type=int, default=100)
    parser.add_argument("--seed", type=int, default=52)
    parser.add_argument("--exclude-pool-source-ids", type=Path)
    parser.add_argument("--exclude-source-ids", type=Path)
    parser.add_argument("--preserve-annotations-from", type=Path, default=DEFAULT_DATASET_PATH)
    args = parser.parse_args(argv)
    if (args.exclude_pool_source_ids is None) != (args.exclude_source_ids is None):
        parser.error("--exclude-pool-source-ids and --exclude-source-ids must be provided together")
    if args.exclude_pool_source_ids is None:
        args.exclude_pool_source_ids = DEFAULT_POOL_EXCLUSIONS_PATH
        args.exclude_source_ids = DEFAULT_SELECTION_EXCLUSIONS_PATH
    return args


def main(argv: list[str] | None = None) -> None:
    from datasets import load_dataset

    args = parse_args(argv)
    existing = (
        [
            json.loads(line)
            for line in args.preserve_annotations_from.read_text(encoding="utf-8").splitlines()
            if line
        ]
        if args.preserve_annotations_from
        else None
    )

    rows = load_dataset(SOURCE_DATASET, split="train", revision=SOURCE_REVISION, streaming=True)
    pool_excluded = load_source_record_ids(args.exclude_pool_source_ids)
    pools = collect_candidate_pools(
        rows,
        pool_size=args.pool_size,
        excluded_source_record_ids=pool_excluded,
    )
    excluded = load_source_record_ids(args.exclude_source_ids)
    records = sample_candidates(
        pools,
        per_language=args.per_language,
        seed=args.seed,
        excluded_source_record_ids=excluded,
    )
    if existing is not None:
        records = merge_existing_annotations(records, existing)
    write_jsonl(records, args.output)
    print(f"wrote {len(records)} records to {args.output}")


if __name__ == "__main__":
    main()
