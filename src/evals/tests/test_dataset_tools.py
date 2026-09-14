import subprocess
import sys
from pathlib import Path

import pytest

from src.evals import build_mixed_200
from src.evals.build_hypothesis_report import (
    INTERVIEW_HEADERS,
    load_interviews,
    render_issue_52_section,
    replace_managed_section,
    valid_consented_interviews,
)
from src.evals.build_mixed_200 import (
    candidate_from_row,
    collect_candidate_pools,
    contains_obvious_pii,
    normalize_prompt,
    sample_candidates,
)
from src.evals.validate_dataset import validate_records


def _row(language: str, content: str, *, toxic: bool = False, record_id: str = "a" * 32) -> dict:
    return {
        "language": language,
        "toxic": toxic,
        "conversation_hash": record_id,
        "conversation": [
            {"role": "user", "content": content, "turn_identifier": f"turn-{record_id}"},
            {"role": "assistant", "content": "response", "turn_identifier": "assistant-turn"},
        ],
    }


def test_normalize_prompt_unicode_and_whitespace():
    assert normalize_prompt("  Xin   chào\n bạn  ") == "Xin chào bạn"


def test_obvious_pii_and_secret_patterns():
    assert contains_obvious_pii("email me at user@example.com")
    assert contains_obvious_pii("key sk-abcdefghijklmnopqrstuvwxyz123456")
    assert contains_obvious_pii("server 192.168.10.20")
    assert not contains_obvious_pii("Giải bài toán 123 + 456")


def test_obvious_pii_includes_github_and_aws_credentials():
    assert contains_obvious_pii(f"GitHub token ghp_{'a' * 36}")
    assert contains_obvious_pii("AWS access key AKIAIOSFODNN7EXAMPLE")


def test_obvious_pii_includes_named_generic_api_keys():
    assert contains_obvious_pii('"api_key": "' + "a" * 64 + '"')


def test_candidate_uses_first_user_turn_and_normalizes_language():
    candidate = candidate_from_row(_row("Vietnamese", "  Xin   chào "))
    assert candidate == {
        "prompt": "Xin chào",
        "language": "vi",
        "source_record_id": f"{'a' * 32}:turn-{'a' * 32}",
    }


def test_candidate_rejects_toxic_pii_empty_and_missing_media():
    assert candidate_from_row(_row("English", "hello", toxic=True)) is None
    assert candidate_from_row(_row("English", "contact user@example.com")) is None
    assert candidate_from_row(_row("English", "   ")) is None
    assert candidate_from_row(_row("English", "What is in this attached image?")) is None


def test_candidate_rejects_alternate_missing_media_phrases():
    assert candidate_from_row(_row("English", "I attached an image")) is None
    assert candidate_from_row(_row("English", "Please see the photo attached")) is None


def test_candidate_accepts_media_generation_requests_without_missing_input():
    assert candidate_from_row(_row("Vietnamese", "tạo ảnh kích thước 1000x600px")) is not None
    assert candidate_from_row(_row("English", "Explain how to create an image with Pillow")) is not None


def test_candidate_distinguishes_youtube_dependency_from_benign_url_reference():
    assert candidate_from_row(_row("English", "What does https://youtube.com/watch?v=abc say?")) is None
    benign_reference = _row("English", "Explain YouTube URL syntax using https://youtube.com/watch?v=abc")
    assert candidate_from_row(benign_reference) is not None


def test_candidate_rejects_structured_media_content():
    assert candidate_from_row(_row("English", {"type": "image", "url": "https://example.com/image.png"})) is None


def test_candidate_rejects_malformed_conversation_entries_and_metadata():
    for entry in ("not a message", None, []):
        malformed_entry = _row("English", "hello")
        malformed_entry["conversation"] = [entry]
        assert candidate_from_row(malformed_entry) is None

    malformed_hash = _row("English", "hello")
    malformed_hash["conversation_hash"] = ["hash"]
    assert candidate_from_row(malformed_hash) is None

    malformed_turn_identifier = _row("English", "hello")
    malformed_turn_identifier["conversation"][0]["turn_identifier"] = {"id": "turn"}
    assert candidate_from_row(malformed_turn_identifier) is None


def test_candidate_accepts_integer_turn_identifier_but_rejects_bool_and_float():
    integer_identifier = _row("English", "hello")
    integer_identifier["conversation"][0]["turn_identifier"] = 42
    assert candidate_from_row(integer_identifier) == {
        "prompt": "hello",
        "language": "en",
        "source_record_id": f"{'a' * 32}:42",
    }

    for invalid_identifier in (True, 42.0):
        malformed = _row("English", "hello")
        malformed["conversation"][0]["turn_identifier"] = invalid_identifier
        assert candidate_from_row(malformed) is None


def test_candidate_rejects_prompt_over_token_boundary():
    assert candidate_from_row(_row("English", "x" * 64_003)) is not None
    assert candidate_from_row(_row("English", "x" * 64_004)) is None


def test_collect_candidate_pools_deduplicates_prompts_across_languages():
    pools = collect_candidate_pools(
        [
            _row("Vietnamese", "Same prompt", record_id="a" * 32),
            _row("English", "same prompt", record_id="b" * 32),
            _row("English", "Different prompt", record_id="c" * 32),
        ],
        pool_size=1,
    )
    assert [candidate["prompt"] for candidate in pools["vi"]] == ["Same prompt"]
    assert [candidate["prompt"] for candidate in pools["en"]] == ["Different prompt"]


def test_collect_candidate_pools_skips_explicit_pool_compatibility_exclusions():
    pools = collect_candidate_pools(
        [
            _row("Vietnamese", "Excluded vi", record_id="a" * 32),
            _row("Vietnamese", "Kept vi", record_id="b" * 32),
            _row("English", "Excluded en", record_id="c" * 32),
            _row("English", "Kept en", record_id="d" * 32),
        ],
        pool_size=1,
        excluded_source_record_ids={
            f"{'a' * 32}:turn-{'a' * 32}",
            f"{'c' * 32}:turn-{'c' * 32}",
        },
    )

    assert [candidate["prompt"] for candidate in pools["vi"]] == ["Kept vi"]
    assert [candidate["prompt"] for candidate in pools["en"]] == ["Kept en"]


def test_sampling_is_deterministic_and_balanced():
    pools = {
        "vi": [{"prompt": f"vi {i}", "language": "vi", "source_record_id": f"vi:{i}"} for i in range(5)],
        "en": [
            {"prompt": f"en {i}", "language": "en", "source_record_id": f"en:{i}"} for i in range(5)
        ],
    }
    first = sample_candidates(pools, per_language=3, seed=52)
    assert first == sample_candidates(pools, per_language=3, seed=52)
    assert [row["language"] for row in first].count("vi") == 3
    assert [row["language"] for row in first].count("en") == 3
    assert [row["id"] for row in first] == [
        "wc-vi-001",
        "wc-vi-002",
        "wc-vi-003",
        "wc-en-001",
        "wc-en-002",
        "wc-en-003",
    ]


def test_sampling_defaults_to_one_hundred_per_language():
    pools = {
        language: [
            {
                "prompt": f"{language} {index}",
                "language": language,
                "source_record_id": f"{language}:{index}",
            }
            for index in range(100)
        ]
        for language in ("vi", "en")
    }
    records = sample_candidates(pools)
    assert len(records) == 200
    assert [record["language"] for record in records].count("vi") == 100
    assert [record["language"] for record in records].count("en") == 100


def test_sampling_replaces_only_excluded_selection_from_unused_same_language_pool():
    pools = {
        language: [
            {
                "prompt": f"{language} {index}",
                "language": language,
                "source_record_id": f"{language}:{index}",
            }
            for index in range(5)
        ]
        for language in ("vi", "en")
    }

    replaced = sample_candidates(pools, per_language=3, seed=52, excluded_source_record_ids={"vi:2"})

    assert [row["source_record_id"] for row in replaced] == [
        "vi:0",
        "vi:1",
        "vi:4",
        "en:1",
        "en:3",
        "en:4",
    ]


def test_sampling_fails_when_exclusions_exhaust_unused_same_language_pool():
    pools = {
        language: [
            {
                "prompt": f"{language} {index}",
                "language": language,
                "source_record_id": f"{language}:{index}",
            }
            for index in range(3)
        ]
        for language in ("vi", "en")
    }

    try:
        sample_candidates(pools, per_language=3, seed=52, excluded_source_record_ids={"vi:0"})
    except ValueError as error:
        assert str(error) == "not enough unused vi candidates to replace 1 exclusions"
    else:
        raise AssertionError("expected replacement exhaustion to fail")


def test_canonical_cli_defaults_to_committed_inputs_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    args = build_mixed_200.parse_args([])
    dataset_dir = Path(build_mixed_200.__file__).resolve().parent / "datasets"

    assert args.output == dataset_dir / "mixed_200.jsonl"
    assert args.exclude_pool_source_ids == dataset_dir / "mixed_200_pool_exclusions.txt"
    assert args.exclude_source_ids == dataset_dir / "mixed_200_exclusions.txt"
    assert args.preserve_annotations_from == dataset_dir / "mixed_200.jsonl"


@pytest.mark.parametrize("flag", ["--exclude-pool-source-ids", "--exclude-source-ids"])
def test_cli_requires_exclusion_overrides_as_a_pair(flag, tmp_path):
    with pytest.raises(SystemExit):
        build_mixed_200.parse_args([flag, str(tmp_path / "custom.txt")])


def test_collect_candidate_pools_rejects_unmatched_pool_exclusions():
    missing_id = f"{'f' * 32}:missing"

    with pytest.raises(ValueError, match="pool exclusions not encountered"):
        collect_candidate_pools(
            [
                _row("Vietnamese", "Kept vi", record_id="a" * 32),
                _row("English", "Kept en", record_id="b" * 32),
            ],
            pool_size=1,
            excluded_source_record_ids={missing_id},
        )


def test_sampling_rejects_selection_exclusions_outside_candidate_pools():
    pools = {
        language: [
            {"prompt": f"{language} {index}", "language": language, "source_record_id": f"{language}:{index}"}
            for index in range(3)
        ]
        for language in ("vi", "en")
    }

    with pytest.raises(ValueError, match="selection exclusions not found in candidate pools"):
        sample_candidates(pools, per_language=2, seed=52, excluded_source_record_ids={"vi:missing"})


def test_sampling_allows_exclusion_of_an_unused_but_pooled_candidate():
    pools = {
        language: [
            {"prompt": f"{language} {index}", "language": language, "source_record_id": f"{language}:{index}"}
            for index in range(5)
        ]
        for language in ("vi", "en")
    }

    records = sample_candidates(
        pools,
        per_language=3,
        seed=52,
        excluded_source_record_ids={"vi:1", "vi:2"},
    )

    assert [row["source_record_id"] for row in records[:3]] == ["vi:0", "vi:3", "vi:4"]


def test_load_source_record_ids_reads_valid_unique_lines(tmp_path):
    path = tmp_path / "exclusions.txt"
    first = f"{'a' * 32}:1"
    second = f"{'b' * 32}:turn-2"
    path.write_text(f"{first}\n{second}\n", encoding="utf-8")

    assert build_mixed_200.load_source_record_ids(path) == {first, second}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (f"{'a' * 32}:1\n\n{'b' * 32}:2\n", "blank line"),
        (f"{'a' * 32}:1\n{'a' * 32}:1\n", "duplicate source record ID"),
        ("not-a-source-id\n", "malformed source record ID"),
    ],
)
def test_load_source_record_ids_rejects_invalid_file_content(tmp_path, payload, message):
    path = tmp_path / "exclusions.txt"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        build_mixed_200.load_source_record_ids(path)


def test_merge_existing_annotations_preserves_only_review_fields():
    fresh = [
        {
            "source_record_id": "x",
            "prompt": "new",
            "category": "other",
            "difficulty": "medium",
            "expected_tier": "T2",
            "annotation_status": "ai_assisted_pending_human_review",
            "annotator": "codex-draft",
            "annotation_notes": "",
            "pii_review_status": "pending_human_review",
        }
    ]
    existing = [
        {
            "source_record_id": "x",
            "prompt": "old",
            "category": "coding",
            "difficulty": "hard",
            "expected_tier": "T3",
            "annotation_status": "ai_assisted_pending_human_review",
            "annotator": "codex-draft",
            "annotation_notes": "multi-step debugging",
            "pii_review_status": "pending_human_review",
        }
    ]

    merged = build_mixed_200.merge_existing_annotations(fresh, existing)

    assert merged[0]["prompt"] == "new"
    assert merged[0]["category"] == "coding"
    assert merged[0]["difficulty"] == "hard"
    assert merged[0]["expected_tier"] == "T3"


def _valid_record(index: int, language: str) -> dict:
    return {
        "id": f"wc-{language}-{index:03d}",
        "prompt": f"prompt {language} {index}",
        "language": language,
        "category": "factual_qa",
        "difficulty": "easy",
        "expected_tier": "T1",
        "source_dataset": "allenai/WildChat-1M",
        "source_revision": "7d6490e462285cf85d91eabea0f9a954fbddcd1f",
        "source_record_id": f"{'a' * 32 if language == 'vi' else 'b' * 32}:{index}",
        "source_url": "https://huggingface.co/datasets/allenai/WildChat-1M",
        "license": "ODC-BY-1.0",
        "pii_review_status": "pending_human_review",
        "annotation_status": "ai_assisted_pending_human_review",
        "annotator": "codex-draft",
        "annotation_notes": "",
    }


def _valid_200() -> list[dict]:
    return [_valid_record(i, language) for language in ("vi", "en") for i in range(1, 101)]


def _write_interviews_csv(path: Path, headers: list[str] | tuple[str, ...], rows: list[list[str]]) -> None:
    payload = [",".join(headers), *(",".join(row) for row in rows)]
    path.write_text("\n".join(payload) + "\n", encoding="utf-8")


def _interview_values(**overrides: str) -> list[str]:
    values = {
        "participant_id": "DEV-01",
        "interview_date": "2026-08-14",
        "role_band": "engineer",
        "experience_band": "3-5",
        "llm_integration_frequency": "weekly",
        "current_e2e_latency_band": "100-300",
        "acceptable_router_overhead_band": "100-300",
        "latency_sensitive_cases": "interactive_chat;voice_realtime",
        "cost_quality_preference": "balanced",
        "desired_log_fields": "tier;latency",
        "privacy_debugging_concerns": "personal_data;retention",
        "consent_to_aggregate": "yes",
    }
    values.update(overrides)
    return [values[header] for header in INTERVIEW_HEADERS]


def test_regular_validation_accepts_draft_and_reports_pending():
    result = validate_records(_valid_200())

    assert result.errors == []
    assert result.stats["pending_annotation_review"] == 200
    assert result.stats["language"] == {"vi": 100, "en": 100}


def test_strict_gold_validation_rejects_pending_review():
    result = validate_records(_valid_200(), require_gold=True)

    assert "200 records still need annotation review" in result.errors
    assert "200 records still need PII review" in result.errors


def test_validator_rejects_duplicate_normalized_prompt_id_source_and_tier_mismatch():
    rows = _valid_200()
    rows[1]["prompt"] = f"  {rows[0]['prompt'].upper()}  "
    rows[2]["id"] = rows[0]["id"]
    rows[3]["source_record_id"] = rows[0]["source_record_id"]
    rows[4]["expected_tier"] = "T3"

    result = validate_records(rows)

    assert any("duplicate prompt" in error for error in result.errors)
    assert any("duplicate id" in error for error in result.errors)
    assert any("duplicate source record ID" in error for error in result.errors)
    assert any("difficulty-tier mismatch" in error for error in result.errors)


def test_validator_enforces_source_record_id_provenance_pattern():
    rows = _valid_200()
    rows[0]["source_record_id"] = "x" * 34
    rows[1]["source_record_id"] = f"{'z' * 32}:abc"
    rows[2]["source_record_id"] = f"{'a' * 32}:123"

    errors = validate_records(rows).errors

    assert sum("invalid source_record_id" in error for error in errors) >= 2


def test_validator_rejects_missing_and_additional_schema_fields():
    rows = _valid_200()
    del rows[0]["license"]
    rows[1]["unexpected"] = "value"

    result = validate_records(rows)

    assert any("missing required fields" in error for error in result.errors)
    assert any("unexpected fields" in error for error in result.errors)


def test_validator_rejects_invalid_enums_provenance_annotator_and_notes():
    rows = _valid_200()
    rows[0]["category"] = "invalid"
    rows[1]["annotation_status"] = "draft"
    rows[2]["pii_review_status"] = "unchecked"
    rows[3]["source_revision"] = "main"
    rows[4]["annotator"] = ""
    rows[5]["annotation_notes"] = None

    errors = validate_records(rows).errors

    assert any("invalid category" in error for error in errors)
    assert any("invalid annotation_status" in error for error in errors)
    assert any("invalid pii_review_status" in error for error in errors)
    assert any("source_revision must be" in error for error in errors)
    assert any("annotator must be a non-empty string" in error for error in errors)
    assert any("annotation_notes must be a string" in error for error in errors)


def test_validator_reports_unhashable_enum_values_as_invalid():
    rows = _valid_200()
    rows[0]["language"] = []
    rows[1]["category"] = []
    rows[2]["difficulty"] = []
    rows[3]["expected_tier"] = "T4"
    rows[4]["annotation_status"] = []
    rows[5]["pii_review_status"] = []

    errors = validate_records(rows).errors

    assert any("invalid language" in error for error in errors)
    assert any("invalid category" in error for error in errors)
    assert any("invalid difficulty" in error for error in errors)
    assert any("invalid expected_tier" in error for error in errors)
    assert any("invalid annotation_status" in error for error in errors)
    assert any("invalid pii_review_status" in error for error in errors)


def test_validator_rejects_pii_and_missing_media_prompts():
    rows = _valid_200()
    rows[0]["prompt"] = "contact user@example.com"
    rows[1]["prompt"] = "Please describe this attached image"

    errors = validate_records(rows).errors

    assert any("contains obvious PII" in error for error in errors)
    assert any("depends on unavailable media" in error for error in errors)


def test_validator_requires_notes_for_human_revised_annotations():
    rows = _valid_200()
    rows[0]["annotation_status"] = "human_revised"
    rows[0]["annotation_notes"] = "  "

    assert any("human_revised annotation requires notes" in error for error in validate_records(rows).errors)


def test_strict_gold_requires_human_annotator_status_and_pii_review():
    rows = _valid_200()
    for row in rows:
        row["pii_review_status"] = "human_verified"
        row["annotation_status"] = "human_verified"
        row["annotator"] = "reviewer-01"
    rows[0]["annotator"] = "codex-draft"
    rows[1]["annotation_status"] = "ai_assisted_pending_human_review"
    rows[2]["pii_review_status"] = "pending_human_review"

    errors = validate_records(rows, require_gold=True).errors

    assert any("codex-draft" in error for error in errors)
    assert "1 records still need annotation review" in errors
    assert "1 records still need PII review" in errors


def test_strict_gold_rejects_whitespace_and_case_codex_draft_alias():
    rows = _valid_200()
    for row in rows:
        row["pii_review_status"] = "human_verified"
        row["annotation_status"] = "human_verified"
        row["annotator"] = "reviewer-01"
    rows[0]["annotator"] = "  CoDeX-Draft  "

    assert "1 records still use codex-draft annotator" in validate_records(rows, require_gold=True).errors


def test_validator_reports_invalid_expected_tier_when_difficulty_is_invalid():
    rows = _valid_200()
    rows[0]["difficulty"] = "invalid"
    rows[0]["expected_tier"] = "T4"

    errors = validate_records(rows).errors

    assert any("invalid difficulty" in error for error in errors)
    assert any("invalid expected_tier" in error for error in errors)


def test_strict_gold_passes_after_human_review():
    rows = _valid_200()
    for row in rows:
        row["pii_review_status"] = "human_verified"
        row["annotation_status"] = "human_verified"
        row["annotator"] = "reviewer-01"

    assert validate_records(rows, require_gold=True).errors == []


def test_report_is_preliminary_and_h3_not_tested_without_humans():
    section = render_issue_52_section(_valid_200(), [])

    assert "H1: PRELIMINARY" in section
    assert "Easy + Medium: 100.0%" in section
    assert "H3: NOT TESTED" in section
    assert "0/3" in section


def test_report_summarizes_three_consented_interviews():
    interviews = [
        {
            "participant_id": "DEV-01",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "100-300",
            "desired_log_fields": "tier;signals;latency;tier",
        },
        {
            "participant_id": "DEV-02",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "100-300",
            "desired_log_fields": "tier; cost ;latency;",
        },
        {
            "participant_id": "DEV-03",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "301-500",
            "desired_log_fields": "signals;fallback_chain;error",
        },
    ]

    section = render_issue_52_section(_valid_200(), interviews)

    assert "H3: TESTED" in section
    assert "3/3" in section
    assert "2/3" in section
    assert "Median band: 100-300 ms" in section
    assert "Mode band: 100-300 ms" in section
    assert "- latency: 2/3" in section
    assert "- tier: 2/3" in section


def test_h1_is_supported_only_after_review_and_within_target_range():
    rows = _valid_200()
    for index, row in enumerate(rows):
        row["pii_review_status"] = "human_verified"
        row["annotation_status"] = "human_verified"
        row["annotator"] = "reviewer-01"
        if index >= 130:
            row["difficulty"] = "hard"
            row["expected_tier"] = "T3"

    section = render_issue_52_section(rows, [])

    assert "H1: SUPPORTED" in section
    assert "65.0%" in section
    assert "remains preliminary" not in section
    assert "reviews are complete" in section


def test_h1_is_not_supported_after_review_outside_target_without_preliminary_prose():
    rows = _valid_200()
    for row in rows:
        row["pii_review_status"] = "human_verified"
        row["annotation_status"] = "human_verified"
        row["annotator"] = "reviewer-01"

    section = render_issue_52_section(rows, [])

    assert "H1: NOT SUPPORTED" in section
    assert "reviews are complete" in section
    assert "remains preliminary" not in section


def test_valid_consented_interviews_filters_only_missing_id_or_consent():
    rows = [
        {"participant_id": "DEV-01", "consent_to_aggregate": " YES ", "acceptable_router_overhead_band": "<100"},
        {"participant_id": "DEV-02", "consent_to_aggregate": "no", "acceptable_router_overhead_band": "100-300"},
        {"participant_id": "", "consent_to_aggregate": "yes", "acceptable_router_overhead_band": "100-300"},
        {"participant_id": "DEV-04", "consent_to_aggregate": "yes", "acceptable_router_overhead_band": "unknown"},
    ]

    assert valid_consented_interviews(rows) == [rows[0], rows[3]]


def test_render_rejects_invalid_overhead_band_from_a_consented_participant():
    interviews = [
        {
            "participant_id": "DEV-04",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "unknown",
            "desired_log_fields": "tier",
        }
    ]

    with pytest.raises(ValueError, match="DEV-04.*acceptable_router_overhead_band"):
        render_issue_52_section(_valid_200(), interviews)


def test_report_uses_lower_median_and_hides_tied_mode():
    interviews = [
        {
            "participant_id": f"DEV-0{index}",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": band,
            "desired_log_fields": "tier",
        }
        for index, band in enumerate(("<100", "100-300", "301-500", "501-1000"), start=1)
    ]

    section = render_issue_52_section(_valid_200(), interviews)

    assert "Median band: 100-300 ms" in section
    assert "Mode band: no unique mode" in section


def test_load_interviews_rejects_missing_required_headers(tmp_path):
    path = tmp_path / "responses.csv"
    path.write_text("participant_id,consent_to_aggregate\nDEV-01,yes\n", encoding="utf-8")

    with pytest.raises(ValueError, match="headers must exactly match"):
        load_interviews(path)


@pytest.mark.parametrize(
    "headers",
    [
        INTERVIEW_HEADERS[:-1],
        (*INTERVIEW_HEADERS, "company"),
        (*INTERVIEW_HEADERS, "participant_id"),
        (INTERVIEW_HEADERS[1], INTERVIEW_HEADERS[0], *INTERVIEW_HEADERS[2:]),
    ],
)
def test_load_interviews_requires_exact_unique_ordered_headers(tmp_path, headers):
    path = tmp_path / "responses.csv"
    _write_interviews_csv(path, headers, [])

    with pytest.raises(ValueError, match="headers must exactly match"):
        load_interviews(path)


@pytest.mark.parametrize("unsafe_value", ["user@example.com", "sk-abcdefghijklmnopqrstuvwxyz123456"])
def test_load_interviews_rejects_ragged_rows_and_personal_data(tmp_path, unsafe_value):
    path = tmp_path / "responses.csv"
    _write_interviews_csv(path, INTERVIEW_HEADERS, [["DEV-01"] * (len(INTERVIEW_HEADERS) + 1)])

    with pytest.raises(ValueError, match="ragged row"):
        load_interviews(path)

    _write_interviews_csv(
        path,
        INTERVIEW_HEADERS,
        [["DEV-01", "", "", "", "", "", "100-300", "", "", "tier", unsafe_value, "yes"]],
    )

    with pytest.raises(ValueError, match="obvious PII"):
        load_interviews(path)


def test_load_interviews_requires_anonymous_participant_ids(tmp_path):
    path = tmp_path / "responses.csv"
    _write_interviews_csv(
        path,
        INTERVIEW_HEADERS,
        [["Alice", "", "", "", "", "", "100-300", "", "", "tier", "", "yes"]],
    )

    with pytest.raises(ValueError, match="participant_id"):
        load_interviews(path)


@pytest.mark.parametrize("duplicate_id", [" DEV-01 ", "dev-01"])
def test_load_interviews_rejects_normalized_duplicate_participant_ids(tmp_path, duplicate_id):
    path = tmp_path / "responses.csv"
    _write_interviews_csv(
        path,
        INTERVIEW_HEADERS,
        [_interview_values(), _interview_values(participant_id=duplicate_id)],
    )

    with pytest.raises(ValueError, match="duplicate participant_id"):
        load_interviews(path)


def test_render_rejects_duplicate_participant_ids_before_h3_count():
    interviews = [
        {
            "participant_id": "DEV-01",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "100-300",
            "desired_log_fields": "tier",
        },
        {
            "participant_id": " dev-01 ",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "100-300",
            "desired_log_fields": "tier",
        },
    ]

    with pytest.raises(ValueError, match="duplicate participant_id"):
        render_issue_52_section(_valid_200(), interviews)


def test_load_interviews_normalizes_documented_structured_tags(tmp_path):
    path = tmp_path / "responses.csv"
    _write_interviews_csv(
        path,
        INTERVIEW_HEADERS,
        [
            _interview_values(
                latency_sensitive_cases=" Voice_Realtime ; interactive_chat ; interactive_chat ",
                privacy_debugging_concerns=" RETENTION ; personal_data ",
            )
        ],
    )

    row = load_interviews(path)[0]

    assert row["latency_sensitive_cases"] == "interactive_chat;voice_realtime"
    assert row["privacy_debugging_concerns"] == "personal_data;retention"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("latency_sensitive_cases", "Acme Company transcript quote", "unknown latency_sensitive_cases"),
        ("cost_quality_preference", "always use the best model", "unknown cost_quality_preference"),
        ("privacy_debugging_concerns", "customer names", "unknown privacy_debugging_concerns"),
        ("interview_date", "14/08/2026", "invalid interview_date"),
        ("role_band", "architect", "invalid role_band"),
        ("consent_to_aggregate", "maybe", "invalid consent_to_aggregate"),
    ],
)
def test_load_interviews_rejects_prose_or_invalid_structured_values(tmp_path, field, value, message):
    path = tmp_path / "responses.csv"
    _write_interviews_csv(path, INTERVIEW_HEADERS, [_interview_values(**{field: value})])

    with pytest.raises(ValueError, match=message):
        load_interviews(path)


@pytest.mark.parametrize("band", ["<100", "100-300", "301-500", "501-1000", ">1000"])
def test_load_interviews_accepts_each_documented_overhead_band(tmp_path, band):
    path = tmp_path / "responses.csv"
    _write_interviews_csv(
        path,
        INTERVIEW_HEADERS,
        [["DEV-01", "", "", "", "", "", band, "", "", "tier", "", "yes"]],
    )

    assert load_interviews(path)[0]["acceptable_router_overhead_band"] == band


def test_report_normalizes_allowlisted_log_fields_and_rejects_unsafe_values():
    interviews = [
        {
            "participant_id": f"DEV-0{index}",
            "consent_to_aggregate": "yes",
            "acceptable_router_overhead_band": "100-300",
            "desired_log_fields": " TIER ; Latency ; tier ",
        }
        for index in range(1, 4)
    ]

    section = render_issue_52_section(_valid_200(), interviews)

    assert "- tier: 3/3" in section
    assert "- latency: 3/3" in section
    assert "TIER" not in section

    interviews[0]["desired_log_fields"] = "tier;<!-- issue-52:end -->"
    with pytest.raises(ValueError, match="unsafe desired_log_fields"):
        render_issue_52_section(_valid_200(), interviews)

    interviews[0]["desired_log_fields"] = "tier;unknown_field"
    with pytest.raises(ValueError, match="unknown desired_log_fields"):
        render_issue_52_section(_valid_200(), interviews)


def test_render_rejects_structurally_invalid_dataset():
    rows = _valid_200()
    rows[0]["id"] = "invalid"

    with pytest.raises(ValueError, match="dataset validation failed"):
        render_issue_52_section(rows, [])


def test_replace_managed_section_is_idempotent_and_preserves_surrounding_report():
    report = "# Report\n\nexisting\n\n<!-- issue-52:start -->\nold\n<!-- issue-52:end -->\n\nfooter\n"

    updated = replace_managed_section(report, "new")

    assert replace_managed_section(updated, "new") == updated
    assert "old" not in updated
    assert "# Report\n\nexisting" in updated
    assert "footer" in updated


def test_replace_managed_section_appends_markers_once_when_missing():
    report = "# Report  \n\n"
    updated = replace_managed_section(report, "new")

    assert updated.startswith(report)
    assert updated.count("<!-- issue-52:start -->") == 1
    assert updated.count("<!-- issue-52:end -->") == 1


@pytest.mark.parametrize(
    "report",
    [
        "<!-- issue-52:start -->\n",
        "<!-- issue-52:end -->\n",
        "<!-- issue-52:start --><!-- issue-52:start --><!-- issue-52:end -->",
    ],
)
def test_replace_managed_section_rejects_malformed_or_duplicate_markers(report):
    with pytest.raises(ValueError, match="managed markers"):
        replace_managed_section(report, "new")


def test_report_generator_runs_as_the_documented_script():
    result = subprocess.run(
        [sys.executable, "src/evals/build_hypothesis_report.py", "--help"],
        cwd=Path(__file__).resolve().parents[3],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_report_generator_rewrites_temp_report_idempotently(tmp_path):
    dataset = Path(__file__).resolve().parents[1] / "datasets" / "mixed_200.jsonl"
    interviews = tmp_path / "responses.csv"
    report = tmp_path / "report.md"
    _write_interviews_csv(interviews, INTERVIEW_HEADERS, [])
    report.write_text("# Existing report  \n\n", encoding="utf-8")
    command = [
        sys.executable,
        "src/evals/build_hypothesis_report.py",
        "--dataset",
        str(dataset),
        "--interviews",
        str(interviews),
        "--report",
        str(report),
    ]
    root = Path(__file__).resolve().parents[3]

    first = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True)
    first_contents = report.read_text(encoding="utf-8")
    second = subprocess.run(command, cwd=root, check=False, capture_output=True, text=True)

    assert first.returncode == second.returncode == 0, first.stderr or second.stderr
    assert report.read_text(encoding="utf-8") == first_contents
    assert first_contents.startswith("# Existing report  \n\n")
    assert "H1: PRELIMINARY" in first_contents
    assert "H3: NOT TESTED (0/3" in first_contents
