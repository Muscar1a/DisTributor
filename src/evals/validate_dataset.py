"""Validate the committed mixed_200 dataset before it is used for evaluation."""

import argparse
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED_FIELDS = {
    "id",
    "prompt",
    "language",
    "category",
    "difficulty",
    "expected_tier",
    "source_dataset",
    "source_revision",
    "source_record_id",
    "source_url",
    "license",
    "pii_review_status",
    "annotation_status",
    "annotator",
    "annotation_notes",
}
CATEGORIES = {
    "chitchat",
    "factual_qa",
    "explanation",
    "translation",
    "summarization",
    "information_extraction",
    "writing",
    "coding",
    "math_reasoning",
    "analysis_planning",
    "other",
}
TIER_BY_DIFFICULTY = {"easy": "T1", "medium": "T2", "hard": "T3"}
ANNOTATION_STATUSES = {"ai_assisted_pending_human_review", "human_verified", "human_revised"}
PII_REVIEW_STATUSES = {"pending_human_review", "human_verified"}
SOURCE_DATASET = "allenai/WildChat-1M"
SOURCE_REVISION = "7d6490e462285cf85d91eabea0f9a954fbddcd1f"
SOURCE_URL = "https://huggingface.co/datasets/allenai/WildChat-1M"
SOURCE_LICENSE = "ODC-BY-1.0"
_ID = re.compile(r"^wc-(vi|en)-[0-9]{3}$")
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


def _normalize_prompt(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split()).casefold()


def _contains_obvious_pii(prompt: str) -> bool:
    return any(pattern.search(prompt) for pattern in _PII_PATTERNS)


def _depends_on_missing_media(prompt: str) -> bool:
    return bool(_MISSING_MEDIA.search(prompt)) or bool(
        _YOUTUBE_URL.search(prompt) and _YOUTUBE_DEPENDENCY.search(_YOUTUBE_URL.sub("", prompt))
    )


def validate_records(records: list[dict[str, Any]], require_gold: bool = False) -> ValidationResult:
    """Return structural and optional human-review validation results for records."""
    errors: list[str] = []
    warnings: list[str] = []
    languages = Counter(
        row["language"] for row in records if isinstance(row, dict) and isinstance(row.get("language"), str)
    )
    difficulties = Counter(
        row["difficulty"] for row in records if isinstance(row, dict) and isinstance(row.get("difficulty"), str)
    )
    categories = Counter(
        row["category"] for row in records if isinstance(row, dict) and isinstance(row.get("category"), str)
    )
    pending_annotation = sum(
        1
        for row in records
        if not isinstance(row, dict)
        or not isinstance(row.get("annotation_status"), str)
        or row["annotation_status"] not in {"human_verified", "human_revised"}
    )
    pending_pii = sum(
        1
        for row in records
        if not isinstance(row, dict)
        or not isinstance(row.get("pii_review_status"), str)
        or row["pii_review_status"] != "human_verified"
    )
    stats = {
        "records": len(records),
        "language": dict(languages),
        "difficulty": dict(difficulties),
        "category": dict(categories),
        "pending_annotation_review": pending_annotation,
        "pending_pii_review": pending_pii,
    }

    if len(records) != 200:
        errors.append(f"expected 200 records, found {len(records)}")
    for language in ("vi", "en"):
        if languages[language] != 100:
            errors.append(f"expected 100 {language} records, found {languages[language]}")

    seen_ids: set[str] = set()
    seen_prompts: set[str] = set()
    seen_source_ids: set[str] = set()
    for line_number, row in enumerate(records, start=1):
        prefix = f"record {line_number}"
        if not isinstance(row, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        missing = sorted(REQUIRED_FIELDS - row.keys())
        additional = sorted(row.keys() - REQUIRED_FIELDS)
        if missing:
            errors.append(f"{prefix}: missing required fields: {', '.join(missing)}")
        if additional:
            errors.append(f"{prefix}: unexpected fields: {', '.join(additional)}")

        record_id = row.get("id")
        if not isinstance(record_id, str) or not _ID.fullmatch(record_id):
            errors.append(f"{prefix}: invalid id")
        elif record_id in seen_ids:
            errors.append(f"{prefix}: duplicate id {record_id}")
        else:
            seen_ids.add(record_id)

        prompt = row.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            errors.append(f"{prefix}: prompt must be a non-empty string")
        else:
            normalized_prompt = _normalize_prompt(prompt)
            if normalized_prompt in seen_prompts:
                errors.append(f"{prefix}: duplicate prompt")
            else:
                seen_prompts.add(normalized_prompt)
            if _contains_obvious_pii(prompt):
                errors.append(f"{prefix}: prompt contains obvious PII")
            if _depends_on_missing_media(prompt):
                errors.append(f"{prefix}: prompt depends on unavailable media")

        language = row.get("language")
        if not isinstance(language, str) or language not in {"vi", "en"}:
            errors.append(f"{prefix}: invalid language")
        category = row.get("category")
        if not isinstance(category, str) or category not in CATEGORIES:
            errors.append(f"{prefix}: invalid category")
        difficulty = row.get("difficulty")
        expected_tier = row.get("expected_tier")
        valid_difficulty = isinstance(difficulty, str) and difficulty in TIER_BY_DIFFICULTY
        valid_expected_tier = isinstance(expected_tier, str) and expected_tier in TIER_BY_DIFFICULTY.values()
        if not valid_difficulty:
            errors.append(f"{prefix}: invalid difficulty")
        if not valid_expected_tier:
            errors.append(f"{prefix}: invalid expected_tier")
        if valid_difficulty and valid_expected_tier and expected_tier != TIER_BY_DIFFICULTY[difficulty]:
            errors.append(f"{prefix}: difficulty-tier mismatch")

        for field, expected in (
            ("source_dataset", SOURCE_DATASET),
            ("source_revision", SOURCE_REVISION),
            ("source_url", SOURCE_URL),
            ("license", SOURCE_LICENSE),
        ):
            if row.get(field) != expected:
                errors.append(f"{prefix}: {field} must be {expected}")
        source_record_id = row.get("source_record_id")
        if not isinstance(source_record_id, str) or not re.fullmatch(r"[a-f0-9]{32}:[0-9]+", source_record_id):
            errors.append(f"{prefix}: invalid source_record_id")
        elif source_record_id in seen_source_ids:
            errors.append(f"{prefix}: duplicate source record ID {source_record_id}")
        else:
            seen_source_ids.add(source_record_id)

        pii_status = row.get("pii_review_status")
        if not isinstance(pii_status, str) or pii_status not in PII_REVIEW_STATUSES:
            errors.append(f"{prefix}: invalid pii_review_status")
        annotation_status = row.get("annotation_status")
        if not isinstance(annotation_status, str) or annotation_status not in ANNOTATION_STATUSES:
            errors.append(f"{prefix}: invalid annotation_status")
        annotator = row.get("annotator")
        if not isinstance(annotator, str) or not annotator.strip():
            errors.append(f"{prefix}: annotator must be a non-empty string")
        notes = row.get("annotation_notes")
        if not isinstance(notes, str):
            errors.append(f"{prefix}: annotation_notes must be a string")
        elif annotation_status == "human_revised" and not notes.strip():
            errors.append(f"{prefix}: human_revised annotation requires notes")

    if require_gold:
        draft_annotators = sum(
            1
            for row in records
            if isinstance(row, dict)
            and isinstance(row.get("annotator"), str)
            and re.sub(r"[\s_-]+", "-", row["annotator"].strip().casefold()) == "codex-draft"
        )
        if draft_annotators:
            errors.append(f"{draft_annotators} records still use codex-draft annotator")
        if pending_annotation:
            errors.append(f"{pending_annotation} records still need annotation review")
        if pending_pii:
            errors.append(f"{pending_pii} records still need PII review")
    else:
        if pending_annotation:
            warnings.append(f"{pending_annotation} records still need annotation review")
        if pending_pii:
            warnings.append(f"{pending_pii} records still need PII review")

    return ValidationResult(errors=errors, warnings=warnings, stats=stats)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate a SmartRoute gold dataset JSONL file.")
    parser.add_argument("dataset", type=Path, nargs="?", default=Path("src/evals/datasets/mixed_200.jsonl"))
    parser.add_argument("--require-gold", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = validate_records(load_jsonl(args.dataset), require_gold=args.require_gold)
    payload = {"errors": result.errors, "warnings": result.warnings, "stats": result.stats}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return int(bool(result.errors))


if __name__ == "__main__":
    raise SystemExit(main())
