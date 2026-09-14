"""Build the managed issue-52 hypothesis section of the evaluation report."""

import argparse
import csv
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

if __package__:
    from .validate_dataset import _contains_obvious_pii, load_jsonl, validate_records
else:
    from validate_dataset import _contains_obvious_pii, load_jsonl, validate_records


START = "<!-- issue-52:start -->"
END = "<!-- issue-52:end -->"
OVERHEAD_BANDS = ("<100", "100-300", "301-500", "501-1000", ">1000")
INTERVIEW_HEADERS = (
    "participant_id",
    "interview_date",
    "role_band",
    "experience_band",
    "llm_integration_frequency",
    "current_e2e_latency_band",
    "acceptable_router_overhead_band",
    "latency_sensitive_cases",
    "cost_quality_preference",
    "desired_log_fields",
    "privacy_debugging_concerns",
    "consent_to_aggregate",
)
LOG_FIELDS = frozenset(
    {
        "request_id",
        "timestamp",
        "tier",
        "score",
        "signals",
        "reason",
        "policy",
        "model",
        "provider",
        "fallback_chain",
        "latency",
        "tokens",
        "cost",
        "error",
        "content_redaction",
    }
)
TAG_FIELDS = {
    "latency_sensitive_cases": frozenset(
        {"interactive_chat", "autocomplete", "voice_realtime", "agent_loop", "batch", "other"}
    ),
    "cost_quality_preference": frozenset({"cost_first", "balanced", "quality_first", "context_dependent"}),
    "privacy_debugging_concerns": frozenset(
        {
            "prompt_content",
            "response_content",
            "personal_data",
            "secrets",
            "retention",
            "access_control",
            "redaction",
            "traceability",
            "other",
        }
    ),
}
ENUM_FIELDS = {
    "role_band": frozenset({"engineer", "engineering_leader", "product", "data_ml", "other"}),
    "experience_band": frozenset({"0-2", "3-5", "6-10", "10+"}),
    "llm_integration_frequency": frozenset({"never", "evaluating", "monthly", "weekly", "daily"}),
    "current_e2e_latency_band": frozenset(OVERHEAD_BANDS),
    "acceptable_router_overhead_band": frozenset(OVERHEAD_BANDS),
    "consent_to_aggregate": frozenset({"yes", "no", "skipped"}),
}
_PARTICIPANT_ID = re.compile(r"DEV-[0-9]{2}")
_UNSAFE_STORED_TEXT = ("\r", "\n", "<!--", "-->", "```")
_UNSAFE_LOG_TEXT = (*_UNSAFE_STORED_TEXT, "#", "`", "<", ">")


def load_interviews(path: Path) -> list[dict[str, str]]:
    """Load interview rows only when their anonymized schema is complete."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != INTERVIEW_HEADERS:
            raise ValueError("interview headers must exactly match the required ordered schema")
        rows = []
        participant_ids: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"ragged row at line {line_number}")
            clean_row = {key: value for key, value in row.items() if key is not None}
            participant_key = _value(clean_row, "participant_id").casefold()
            if participant_key in participant_ids:
                raise ValueError(f"line {line_number}: duplicate participant_id")
            participant_ids.add(participant_key)
            _validate_stored_interview(clean_row, line_number)
            rows.append(clean_row)
        return rows


def _value(row: dict[str, str], field: str) -> str:
    value = row.get(field, "")
    return value.strip() if isinstance(value, str) else ""


def _validate_stored_interview(row: dict[str, str], line_number: int) -> None:
    participant_id = _value(row, "participant_id")
    if not _PARTICIPANT_ID.fullmatch(participant_id):
        raise ValueError(f"line {line_number}: invalid participant_id; use DEV-NN")
    for field, value in row.items():
        if any(marker in value for marker in _UNSAFE_STORED_TEXT):
            raise ValueError(f"line {line_number}: unsafe {field}")
        if field != "interview_date" and _contains_obvious_pii(value):
            raise ValueError(f"line {line_number}: obvious PII or secret in {field}")
    row["participant_id"] = participant_id
    row["interview_date"] = _normalize_date(_value(row, "interview_date"))
    for field, allowed in ENUM_FIELDS.items():
        row[field] = _normalize_enum(_value(row, field), field, allowed)
    for field, allowed in TAG_FIELDS.items():
        row[field] = _normalize_tags(_value(row, field), field, allowed)
    row["desired_log_fields"] = ";".join(sorted(_parse_log_fields(_value(row, "desired_log_fields"), participant_id)))


def _normalize_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError("invalid interview_date; use ISO YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ValueError("invalid interview_date; use ISO YYYY-MM-DD")
    return value


def _normalize_enum(value: str, field: str, allowed: frozenset[str]) -> str:
    normalized = value.casefold()
    if not normalized:
        return ""
    if normalized not in allowed:
        raise ValueError(f"invalid {field}")
    return normalized


def _normalize_tags(value: str, field: str, allowed: frozenset[str]) -> str:
    if any(marker in value for marker in _UNSAFE_LOG_TEXT):
        raise ValueError(f"unsafe {field}")
    tags = {tag.strip().casefold() for tag in value.split(";") if tag.strip()}
    unknown = sorted(tags - allowed)
    if unknown:
        raise ValueError(f"unknown {field}: {', '.join(unknown)}")
    return ";".join(sorted(tags))


def _parse_log_fields(value: str, participant_id: str) -> set[str]:
    if any(marker in value for marker in _UNSAFE_LOG_TEXT):
        raise ValueError(f"participant {participant_id}: unsafe desired_log_fields")
    fields = {field.strip().casefold() for field in value.split(";") if field.strip()}
    unknown = sorted(fields - LOG_FIELDS)
    if unknown:
        raise ValueError(f"participant {participant_id}: unknown desired_log_fields: {', '.join(unknown)}")
    return fields


def valid_consented_interviews(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return only rows with a nonempty ID and explicit aggregate consent."""
    return [
        row
        for row in rows
        if _value(row, "participant_id")
        and _value(row, "consent_to_aggregate").lower() == "yes"
    ]


def _validate_unique_participant_ids(rows: list[dict[str, str]]) -> None:
    participant_ids: set[str] = set()
    for row in rows:
        participant_id = _value(row, "participant_id")
        if not participant_id:
            continue
        participant_key = participant_id.casefold()
        if participant_key in participant_ids:
            raise ValueError(f"duplicate participant_id: {participant_id}")
        participant_ids.add(participant_key)


def _validate_consented_interviews(rows: list[dict[str, str]]) -> None:
    for row in rows:
        participant_id = _value(row, "participant_id")
        if not _PARTICIPANT_ID.fullmatch(participant_id):
            raise ValueError(f"invalid participant_id for consented participant {participant_id!r}; use DEV-NN")
        band = _value(row, "acceptable_router_overhead_band")
        if band not in OVERHEAD_BANDS:
            raise ValueError(
                f"participant {participant_id}: invalid acceptable_router_overhead_band {band!r}"
            )
        if "interview_date" in row:
            _normalize_date(_value(row, "interview_date"))
        for field, allowed in ENUM_FIELDS.items():
            if field in row:
                _normalize_enum(_value(row, field), field, allowed)
        for field, allowed in TAG_FIELDS.items():
            if field in row:
                _normalize_tags(_value(row, field), field, allowed)
        _parse_log_fields(_value(row, "desired_log_fields"), participant_id)


def _counts(values: list[dict[str, Any]], field: str, names: tuple[str, ...] | None = None) -> str:
    counted = Counter(str(row.get(field, "")) for row in values)
    if names is None:
        names = tuple(sorted(counted))
    return ", ".join(f"{name} {counted[name]}" for name in names)


def _interview_summary(consented: list[dict[str, str]]) -> list[str]:
    count = len(consented)
    if count < 3:
        return [
            f"- H3: NOT TESTED ({count}/3 valid consented interviews)",
            "- No interview conclusion is reported until at least three valid consented rows are available.",
        ]

    bands = sorted((_value(row, "acceptable_router_overhead_band") for row in consented), key=OVERHEAD_BANDS.index)
    median = bands[(count - 1) // 2]
    band_counts = Counter(bands)
    greatest = max(band_counts.values())
    modes = [band for band in OVERHEAD_BANDS if band_counts[band] == greatest]
    mode = modes[0] if len(modes) == 1 else "no unique mode"
    under_300 = sum(band in {"<100", "100-300"} for band in bands)
    log_counts: Counter[str] = Counter()
    for row in consented:
        log_counts.update(_parse_log_fields(_value(row, "desired_log_fields"), _value(row, "participant_id")))

    lines = [
        f"- H3: TESTED ({count}/3 valid consented interviews)",
        f"- Median band: {median} ms",
        f"- Mode band: {mode}{'' if mode == 'no unique mode' else ' ms'}",
        f"- Acceptable overhead at or below 300 ms: {under_300}/{count}",
        "- Desired routing-log fields (participants mentioning each):",
    ]
    lines.extend(f"  - {field}: {log_counts[field]}/{count}" for field in sorted(log_counts))
    lines.append("- Small-sample descriptive result only; do not generalize beyond these participants.")
    return lines


def render_issue_52_section(records: list[dict[str, Any]], interviews: list[dict[str, str]]) -> str:
    """Render evidence, review gates, and interview status for issue 52."""
    validation = validate_records(records)
    if validation.errors:
        raise ValueError(f"dataset validation failed: {'; '.join(validation.errors)}")

    stats = validation.stats
    total = stats["records"]
    easy_medium = sum(row["difficulty"] in {"easy", "medium"} for row in records)
    easy_medium_pct = 100 * easy_medium / total
    reviewed = stats["pending_annotation_review"] == 0 and stats["pending_pii_review"] == 0
    h1_status = "PRELIMINARY"
    if reviewed:
        h1_status = "SUPPORTED" if 60 <= easy_medium_pct <= 70 else "NOT SUPPORTED"
    h1_review_note = (
        "- Annotation and PII reviews are complete; H1 is evaluated against the observed ratio."
        if reviewed
        else "- H1 remains preliminary until annotation and PII reviews are both complete."
    )
    _validate_unique_participant_ids(interviews)
    consented = valid_consented_interviews(interviews)
    _validate_consented_interviews(consented)

    lines = [
        "## Issue 52: Gold-dataset and interview evidence",
        "",
        "### Dataset composition and H1",
        f"- Prompts: {total}; language: {_counts(records, 'language', ('vi', 'en'))}.",
        f"- Difficulty: {_counts(records, 'difficulty', ('easy', 'medium', 'hard'))}.",
        f"- Categories: {_counts(records, 'category')}.",
        f"- Easy + Medium: {easy_medium_pct:.1f}% ({easy_medium}/{total}); H1 target is 60–70% inclusive.",
        f"- H1: {h1_status}.",
        "- The sample is deliberately stratified at 100 Vietnamese and 100 English prompts; it does not represent a natural WildChat or production-language distribution.",
        h1_review_note,
        "",
        "### Developer interviews and H3",
        *_interview_summary(consented),
    ]
    return "\n".join(lines)


def replace_managed_section(report: str, section: str) -> str:
    """Replace the sole managed section, or append it to an existing report."""
    managed = f"{START}\n{section}\n{END}"
    start_count = report.count(START)
    end_count = report.count(END)
    if start_count == end_count == 0:
        return f"{report}\n\n{managed}\n"
    if start_count != 1 or end_count != 1:
        raise ValueError("malformed managed markers")
    if report.index(START) > report.index(END):
        raise ValueError("malformed managed markers")
    if start_count == end_count == 1:
        before, remainder = report.split(START, 1)
        _, after = remainder.split(END, 1)
        return f"{before}{managed}{after}"
    raise AssertionError("unreachable")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the issue-52 evaluation report section.")
    parser.add_argument("--dataset", type=Path, default=Path("src/evals/datasets/mixed_200.jsonl"))
    parser.add_argument("--interviews", type=Path, default=Path("src/evals/interviews/responses.csv"))
    parser.add_argument("--report", type=Path, default=Path("src/evals/report.md"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    section = render_issue_52_section(load_jsonl(args.dataset), load_interviews(args.interviews))
    args.report.write_text(replace_managed_section(args.report.read_text(encoding="utf-8"), section), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
