import asyncio
import json
from dataclasses import dataclass

import pytest

from src.evals.run_benchmark_eval import (
    BenchmarkRecord,
    Prediction,
    dataset_revisions,
    evaluate_routing,
    git_commit_sha,
    load_dataset,
    mcnemar_exact_p,
    quality_summary,
    read_router_timeout_ms,
    release_gate,
    render_report,
    routing_slices,
    routing_summary,
    wilson_interval,
)


@dataclass
class FakeTier:
    value: str


@dataclass
class FakeSignal:
    name: str


@dataclass
class FakeResult:
    tier: FakeTier
    score: int
    latency_ms: int
    signals: list[FakeSignal]


class FakeClassifier:
    async def classify(self, messages):
        tier = {"easy": "T1", "medium": "T2", "hard": "T1"}[messages[0].content]
        return FakeResult(FakeTier(tier), 20, 3, [FakeSignal("fake")])


def test_load_dataset_accepts_project_schema_and_rejects_duplicates(tmp_path):
    dataset = tmp_path / "data.jsonl"
    row = {"id": "one", "prompt": "hello", "expected_tier": "T1", "source_dataset": "gold"}
    dataset.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert load_dataset(dataset)[0].benchmark == "gold"

    dataset.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate id"):
        load_dataset(dataset)


def test_routing_metrics_include_macro_f1_and_hard_underroute():
    records = [
        BenchmarkRecord("a", "easy", "T1", "gold"),
        BenchmarkRecord("b", "medium", "T2", "gold"),
        BenchmarkRecord("c", "hard", "T3", "gold"),
    ]
    predictions = asyncio.run(evaluate_routing(records, FakeClassifier()))
    summary = routing_summary(predictions)
    assert summary["accuracy"] == pytest.approx(2 / 3)
    assert summary["hard_to_t1_rate"] == 1.0
    assert summary["hard_n"] == 1
    assert summary["confusion"]["T3"]["T1"] == 1
    assert summary["latency_p95_ms"] == 3
    slices = routing_slices(predictions, records, "category")
    assert slices["unknown"]["hard_to_t1"] == 1


def test_hard_to_t1_rate_is_none_not_zero_with_no_t3_prompts():
    """#216 review: a dataset with zero T3-labelled prompts has NOT demonstrated safe
    hard-prompt routing — it must not silently read as 0% severe under-routing."""
    records = [BenchmarkRecord("a", "easy", "T1", "gold")]
    predictions = asyncio.run(evaluate_routing(records, FakeClassifier()))

    summary = routing_summary(predictions)

    assert summary["hard_n"] == 0
    assert summary["hard_to_t1_rate"] is None


def test_routing_summary_counts_v2_fallback_signal():
    predictions = [
        Prediction("a", "T1", "T2", 45, 1, ("v2_fallback",)),
        Prediction("b", "T1", "T1", 20, 1, ("v2_kind_other",)),
    ]
    summary = routing_summary(predictions)
    assert summary["fallback_rate"] == 0.5


def test_wilson_interval_shrinks_toward_true_rate_as_n_grows():
    small = wilson_interval(5, 10)
    large = wilson_interval(500, 1000)
    assert small is not None and large is not None
    assert (large[1] - large[0]) < (small[1] - small[0])
    assert small[0] <= 0.5 <= small[1]


def test_wilson_interval_none_for_zero_samples():
    assert wilson_interval(0, 0) is None


def test_mcnemar_exact_p_no_discordance_is_not_applicable():
    assert mcnemar_exact_p(0, 0) is None


def test_mcnemar_exact_p_symmetric_and_significant_when_lopsided():
    # 20 prompts where only smart is right, 0 where only strong is right: a real
    # difference, not noise — p must be small (two-sided exact test on n=20).
    assert mcnemar_exact_p(20, 0) < 0.01
    # Discordant counts swapped should give the same two-sided p-value.
    assert mcnemar_exact_p(3, 7) == pytest.approx(mcnemar_exact_p(7, 3))


def test_quality_summary_reports_ci_and_mcnemar_p_value():
    predictions = [
        Prediction("p1", "T1", "T1", 10, 1, ()),
        Prediction("p2", "T1", "T1", 10, 1, ()),
    ]
    smart = {"model_id": "m", "prompt_tokens": 10, "completion_tokens": 10}
    strong = {"model_id": "s", "prompt_tokens": 10, "completion_tokens": 10}
    outcomes = [
        {"id": "p1", "quality_type": "objective", "smart": {**smart, "correct": True}, "strong": {**strong, "correct": False}},
        {"id": "p2", "quality_type": "objective", "smart": {**smart, "correct": False}, "strong": {**strong, "correct": True}},
    ]
    prices = {"m": {"input_per_1m_usd": 1, "output_per_1m_usd": 1}, "s": {"input_per_1m_usd": 1, "output_per_1m_usd": 1}}

    summary = quality_summary(outcomes, predictions, prices, "s")

    assert summary["smart_accuracy_ci95"] is not None
    assert summary["strong_accuracy_ci95"] is not None
    # One discordant pair each way (b=1, c=1): perfectly balanced, nothing significant.
    assert summary["mcnemar_p_value"] == 1.0


def test_release_gate_fails_on_first_bad_metric_and_passes_when_clean():
    good_routing = {"hard_to_t1_rate": 0.0, "fallback_rate": 0.0, "latency_p95_ms": 500.0}
    good_quality = {"quality_retention": 0.95, "cost_savings_pct": 0.70, "n": 100, "failed_n": 0}
    gate = release_gate(good_routing, good_quality)
    assert gate["overall"] == "PASS"
    assert all(row["verdict"] == "PASS" for row in gate["rows"])

    bad_routing = {**good_routing, "fallback_rate": 0.10}  # over the 1% cap
    gate = release_gate(bad_routing, good_quality)
    assert gate["overall"] == "FAIL"
    fallback_row = next(row for row in gate["rows"] if row["metric"] == "classifier_fallback_rate")
    assert fallback_row["verdict"] == "FAIL"


def test_release_gate_fails_on_low_outcome_completeness_even_with_good_metrics():
    """#216 review: a quality_retention computed from a handful of survivors after
    most outcome pairs errored must not read as trustworthy just because that tiny
    sample happened to look good."""
    routing = {"hard_to_t1_rate": 0.0, "fallback_rate": 0.0, "latency_p95_ms": 500.0}
    quality = {"quality_retention": 1.0, "cost_savings_pct": 0.70, "n": 500, "failed_n": 499}

    gate = release_gate(routing, quality)

    assert gate["overall"] == "FAIL"
    completeness_row = next(row for row in gate["rows"] if row["metric"] == "outcome_completeness")
    assert completeness_row["verdict"] == "FAIL"


def test_release_gate_severe_underroute_not_measured_with_zero_hard_prompts():
    """#216 review: routing_summary now returns None (not 0.0) for hard_to_t1_rate
    when there are no T3-labelled prompts — the gate must not default that to PASS."""
    routing = {"hard_to_t1_rate": None, "fallback_rate": 0.0, "latency_p95_ms": 500.0}

    gate = release_gate(routing, None)

    row = next(r for r in gate["rows"] if r["metric"] == "severe_underroute_t3_to_t1")
    assert row["verdict"] == "NOT_MEASURED"
    assert gate["overall"] == "INCOMPLETE"


def test_release_gate_is_incomplete_without_outcomes():
    routing = {"hard_to_t1_rate": 0.0, "fallback_rate": 0.0, "latency_p95_ms": 500.0}
    gate = release_gate(routing, None)
    assert gate["overall"] == "INCOMPLETE"
    assert all(row["verdict"] != "FAIL" for row in gate["rows"])


def test_report_includes_gate_table_when_supplied():
    routing = routing_summary([Prediction("a", "T1", "T1", 0, 1, ())])
    gate = release_gate(routing, None)
    report = render_report("gold.jsonl", "v2", routing, None, "gemini-pro", gate=gate)
    assert "Release gate (Issue #211)" in report
    assert f"Overall: {gate['overall']}" in report


def test_quality_and_cost_follow_paired_protocol():
    predictions = [
        Prediction("objective", "T3", "T1", 10, 1, ()),
        Prediction("open", "T2", "T2", 40, 1, ()),
    ]
    run = {"model_id": "smart-model", "prompt_tokens": 100, "completion_tokens": 50}
    baseline = {"model_id": "strong-model", "prompt_tokens": 100, "completion_tokens": 50}
    outcomes = [
        {
            "id": "objective",
            "quality_type": "objective",
            "smart": {**run, "correct": False},
            "strong": {**baseline, "correct": True},
        },
        {
            "id": "open",
            "quality_type": "pairwise",
            "smart": run,
            "strong": baseline,
            "pairwise": {"forward": "smart", "reverse": "strong"},
        },
    ]
    prices = {
        "smart-model": {"input_per_1m_usd": 1, "output_per_1m_usd": 1},
        "strong-model": {"input_per_1m_usd": 2, "output_per_1m_usd": 2},
    }
    summary = quality_summary(outcomes, predictions, prices, "strong-model")
    assert summary["qr_objective"] == 0
    assert summary["qr_pairwise"] == 0.5
    assert summary["quality_retention"] == 0.25
    assert summary["critical_fail_rate"] == 1.0
    assert summary["cost_savings_pct"] == pytest.approx(0.5)


def test_classifier_cost_is_folded_into_totals_and_reported_separately():
    """#211: cost savings must not overstate by ignoring classifier spend, and the
    classifier's share must still be visible as its own number in the summary."""
    predictions = [Prediction("p1", "T3", "T3", 10, 1, ())]
    smart = {
        "model_id": "smart-model",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "correct": True,
        "router_cost_usd": 0.00002,
    }
    strong = {
        "model_id": "strong-model",
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "correct": True,
        "router_cost_usd": 0.0,
    }
    outcomes = [{"id": "p1", "quality_type": "objective", "smart": smart, "strong": strong}]
    prices = {
        "smart-model": {"input_per_1m_usd": 1, "output_per_1m_usd": 1},
        "strong-model": {"input_per_1m_usd": 1, "output_per_1m_usd": 1},
    }

    summary = quality_summary(outcomes, predictions, prices, "strong-model")

    response_cost = (100 + 50) / 1_000_000
    assert summary["smart_cost_usd"] == pytest.approx(response_cost + 0.00002)
    assert summary["strong_cost_usd"] == pytest.approx(response_cost)
    assert summary["smart_classifier_cost_usd"] == pytest.approx(0.00002)
    assert summary["strong_classifier_cost_usd"] == 0.0
    # Same response cost on both sides: without folding in classifier spend this
    # would read as 0% savings and hide that smart routing is actually pricier here.
    assert summary["cost_savings_pct"] < 0


def test_missing_router_cost_usd_defaults_to_zero_not_error():
    """Outcome files recorded before router_cost_usd existed must still load."""
    predictions = [Prediction("p1", "T1", "T1", 10, 1, ())]
    run = {"model_id": "m", "prompt_tokens": 10, "completion_tokens": 10, "correct": True}
    outcomes = [{"id": "p1", "quality_type": "objective", "smart": run, "strong": {**run, "model_id": "strong"}}]
    prices = {
        "m": {"input_per_1m_usd": 1, "output_per_1m_usd": 1},
        "strong": {"input_per_1m_usd": 1, "output_per_1m_usd": 1},
    }

    summary = quality_summary(outcomes, predictions, prices, "strong")

    assert summary["smart_classifier_cost_usd"] == 0.0
    assert summary["strong_classifier_cost_usd"] == 0.0


def test_failed_provider_pairs_are_reported_not_scored():
    predictions = [Prediction("failed", "T3", "T3", 70, 1, ())]
    outcomes = [
        {
            "id": "failed",
            "quality_type": "objective",
            "smart": {"error": "timeout"},
            "strong": {"error": None},
        }
    ]
    summary = quality_summary(outcomes, predictions, {}, "strong-model")
    assert summary["valid_n"] == 0
    assert summary["failed_n"] == 1
    assert summary["quality_retention"] is None


def test_report_does_not_invent_quality_without_outcomes():
    routing = routing_summary([Prediction("a", "T1", "T1", 0, 1, ())])
    report = render_report("gold.jsonl", "heuristic-v1.5", routing, None, "gemini-pro")
    assert "Not measured in this run" in report
    assert "not response quality" in report


def test_dataset_revisions_collects_distinct_source_revisions(tmp_path):
    dataset = tmp_path / "data.jsonl"
    rows = [
        {"id": "a", "prompt": "x", "expected_tier": "T1", "source_revision": "rev1"},
        {"id": "b", "prompt": "y", "expected_tier": "T1", "source_revision": "rev1"},
        {"id": "c", "prompt": "z", "expected_tier": "T1", "source_revision": "rev2"},
    ]
    dataset.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    assert dataset_revisions(dataset) == ["rev1", "rev2"]


def test_dataset_revisions_empty_when_field_absent(tmp_path):
    dataset = tmp_path / "data.jsonl"
    dataset.write_text(json.dumps({"id": "a", "prompt": "x", "expected_tier": "T1"}), encoding="utf-8")
    assert dataset_revisions(dataset) == []


def test_git_commit_sha_none_outside_a_git_checkout(tmp_path):
    # tmp_path is never a git checkout, so this always exercises the "unavailable" path
    # without depending on this test suite's own repo state.
    assert git_commit_sha(tmp_path) is None


def test_read_router_timeout_ms_missing_file_returns_none(tmp_path):
    assert read_router_timeout_ms(tmp_path / "does-not-exist.yaml") is None


def test_read_router_timeout_ms_reads_routing_key(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text("routing:\n  router_timeout_ms: 4000\n", encoding="utf-8")
    assert read_router_timeout_ms(config) == 4000


@pytest.mark.parametrize(
    "content",
    [
        "routing: [not, a, mapping]\n",  # AttributeError: list has no .get
        "routing:\n  router_timeout_ms: \"not-a-number\"\n",  # ValueError: int()
        "routing: [unterminated\n",  # yaml.YAMLError: parse failure
    ],
    ids=["non_mapping_routing", "non_numeric_value", "invalid_yaml_syntax"],
)
def test_read_router_timeout_ms_never_raises_on_malformed_config(tmp_path, content):
    """#218 review: only OSError was caught — a malformed config.yaml (bad structure,
    bad value, or invalid syntax) used to crash the whole benchmark run over one
    optional metadata field. Confirmed via manual repro before this test was written."""
    config = tmp_path / "config.yaml"
    config.write_text(content, encoding="utf-8")
    assert read_router_timeout_ms(config) is None


def test_report_shows_run_metadata_when_supplied():
    routing = routing_summary([Prediction("a", "T1", "T1", 0, 1, ())])
    run_metadata = {
        "git_commit_sha": "abc1234",
        "classifier_router_timeout_ms": 4000,
        "configured_router_timeout_ms": 4000,
        "classifier_prompt_revision": "r5",
        "dataset_revisions": ["rev1"],
    }
    report = render_report(
        "gold.jsonl", "llm-v2", routing, None, "gemini-pro", run_metadata=run_metadata
    )
    assert "`abc1234`" in report
    assert "4000 ms" in report
    assert "`r5`" in report
    assert "`rev1`" in report


def test_report_warns_when_classifier_timeout_disagrees_with_config():
    """#218 review: the classifier is constructed with no arguments (load_classifier),
    so it runs on its own constructor default unless something wires config.yaml
    through — reporting the config value as if it were what ran would be misleading."""
    routing = routing_summary([Prediction("a", "T1", "T1", 0, 1, ())])
    run_metadata = {"classifier_router_timeout_ms": 2500, "configured_router_timeout_ms": 4000}

    report = render_report("gold.jsonl", "llm-v2", routing, None, "gemini-pro", run_metadata=run_metadata)

    assert "2500 ms" in report
    assert "config.yaml declares 4000 ms" in report
    assert "NOT using the configured value" in report


def test_report_router_timeout_falls_back_to_config_only_value():
    routing = routing_summary([Prediction("a", "T1", "T1", 0, 1, ())])
    run_metadata = {"classifier_router_timeout_ms": None, "configured_router_timeout_ms": 4000}

    report = render_report("gold.jsonl", "llm-v2", routing, None, "gemini-pro", run_metadata=run_metadata)

    assert "config.yaml declares 4000 ms (unconfirmed)" in report


def test_report_shows_not_recorded_when_metadata_missing():
    routing = routing_summary([Prediction("a", "T1", "T1", 0, 1, ())])
    report = render_report("gold.jsonl", "heuristic-v1.5", routing, None, "gemini-pro")
    assert "not recorded" in report
    assert "not applicable" in report


def test_report_shows_classifier_cost_as_its_own_line():
    routing = routing_summary([Prediction("a", "T1", "T1", 0, 1, ())])
    quality = {
        "n": 1,
        "valid_n": 1,
        "failed_n": 0,
        "objective_n": 1,
        "smart_accuracy": 1.0,
        "strong_accuracy": 1.0,
        "smart_accuracy_ci95": (0.21, 1.0),
        "strong_accuracy_ci95": (0.21, 1.0),
        "mcnemar_p_value": None,
        "qr_objective": 1.0,
        "qr_pairwise": None,
        "quality_retention": 1.0,
        "quality_retention_hard": None,
        "critical_fail_rate": None,
        "smart_cost_usd": 0.00015,
        "strong_cost_usd": 0.00030,
        "smart_classifier_cost_usd": 0.00002,
        "strong_classifier_cost_usd": 0.0,
        "cost_savings_pct": 0.5,
    }
    report = render_report("gold.jsonl", "v2", routing, quality, "gemini-pro")
    assert "of which classifier: $0.000020" in report
    assert "of which classifier: $0.000000" in report
