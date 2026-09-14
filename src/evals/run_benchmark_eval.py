"""Reproducible routing and response-quality benchmark for SmartRoute classifiers.

The routing benchmark is offline: it only invokes the classifier. Response quality
and cost are computed from a separate JSONL of recorded, paired model outcomes so
that the report never presents guessed model quality as an experimental result.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import math
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

import yaml

TIERS = ("T1", "T2", "T3")


@dataclass(frozen=True)
class BenchmarkRecord:
    id: str
    prompt: str
    expected_tier: str
    benchmark: str
    category: str = "unknown"
    language: str = "unknown"


@dataclass(frozen=True)
class Prediction:
    id: str
    expected_tier: str
    predicted_tier: str
    score: int
    latency_ms: int
    signals: tuple[str, ...]


def _require_tier(value: Any, *, field: str, record_id: str) -> str:
    tier = str(value)
    if tier not in TIERS:
        raise ValueError(f"{record_id}: {field} must be one of {TIERS}, got {tier!r}")
    return tier


def load_dataset(path: Path) -> list[BenchmarkRecord]:
    """Load the project gold JSONL or the normalized standard-benchmark schema."""
    records: list[BenchmarkRecord] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            record_id = str(row.get("id") or f"{path.stem}-{line_number}")
            if record_id in seen:
                raise ValueError(f"{path}:{line_number}: duplicate id {record_id!r}")
            seen.add(record_id)
            prompt = row.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f"{path}:{line_number}: prompt must be a non-empty string")
            records.append(
                BenchmarkRecord(
                    id=record_id,
                    prompt=prompt,
                    expected_tier=_require_tier(
                        row.get("expected_tier"), field="expected_tier", record_id=record_id
                    ),
                    benchmark=str(row.get("benchmark") or row.get("source_dataset") or path.stem),
                    category=str(row.get("category") or "unknown"),
                    language=str(row.get("language") or "unknown"),
                )
            )
    if not records:
        raise ValueError(f"{path}: dataset is empty")
    return records


def dataset_revisions(path: Path) -> list[str]:
    """Distinct `source_revision` values in the raw dataset file, if any.

    Standard benchmarks written by `prepare_standard_benchmark.py` carry this;
    the project gold set (mixed_200.jsonl) and hand-authored sets do not, so an
    empty list here is expected and not an error.
    """
    revisions: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            revision = json.loads(line).get("source_revision")
            if revision:
                revisions.add(str(revision))
    return sorted(revisions)


def git_commit_sha(project_root: Path) -> str | None:
    """The gateway commit this benchmark ran against, for reproducibility (#211).

    Returns None (never raises) outside a git checkout or when git is unavailable —
    a missing commit SHA should degrade the report, not crash the run.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha or None


def read_router_timeout_ms(config_path: Path) -> int | None:
    """`router_timeout_ms` as declared in the gateway's own config.yaml.

    This is the CONFIGURED value, not necessarily what a classifier instance loaded
    by `load_classifier()` is actually using — that class is constructed with no
    arguments (see `load_classifier`), so it runs on its own constructor default
    unless something explicitly wires this config value through. Read
    `classifier_router_timeout_ms` in `main()` for the value that actually applied
    to this run's classification calls.

    Returns None (never raises) for any failure reading or parsing the file, or a
    `router_timeout_ms` value that isn't an int — a malformed/missing/differently
    laid out config must degrade this one metadata field, not crash the benchmark.
    """
    try:
        with config_path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        value = (data.get("routing") or {}).get("router_timeout_ms")
        return int(value) if value is not None else None
    except (OSError, yaml.YAMLError, AttributeError, TypeError, ValueError):
        return None


def load_classifier(project_root: Path, module_name: str, class_name: str) -> Any:
    root = str(project_root.resolve())
    if root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)
    try:
        module = importlib.import_module(module_name)
        classifier_type = getattr(module, class_name)
    except (ImportError, AttributeError) as exc:
        raise RuntimeError(
            f"Cannot load {class_name} from {module_name} under {root}. "
            "Run against a checkout that contains Classifier v1.5."
        ) from exc
    return classifier_type()


async def evaluate_routing(records: list[BenchmarkRecord], classifier: Any) -> list[Prediction]:
    from src.gateway.app.core.interfaces import Message

    predictions: list[Prediction] = []
    for record in records:
        result = await classifier.classify([Message(role="user", content=record.prompt)])
        predicted_tier = getattr(result.tier, "value", result.tier)
        predictions.append(
            Prediction(
                id=record.id,
                expected_tier=record.expected_tier,
                predicted_tier=_require_tier(
                    predicted_tier, field="predicted_tier", record_id=record.id
                ),
                score=int(result.score),
                latency_ms=int(result.latency_ms),
                signals=tuple(signal.name for signal in result.signals),
            )
        )
    return predictions


def percentile(values: list[int], quantile: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def routing_summary(predictions: list[Prediction]) -> dict[str, Any]:
    confusion = {expected: {predicted: 0 for predicted in TIERS} for expected in TIERS}
    for item in predictions:
        confusion[item.expected_tier][item.predicted_tier] += 1

    per_tier: dict[str, dict[str, float]] = {}
    f1_values: list[float] = []
    for tier in TIERS:
        true_positive = confusion[tier][tier]
        false_positive = sum(confusion[other][tier] for other in TIERS if other != tier)
        false_negative = sum(confusion[tier][other] for other in TIERS if other != tier)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_values.append(f1)
        per_tier[tier] = {"precision": precision, "recall": recall, "f1": f1}

    correct = sum(item.expected_tier == item.predicted_tier for item in predictions)
    hard = [item for item in predictions if item.expected_tier == "T3"]
    latencies = [item.latency_ms for item in predictions]
    fallbacks = sum("v2_fallback" in item.signals for item in predictions)
    return {
        "n": len(predictions),
        "accuracy": correct / len(predictions),
        "macro_f1": mean(f1_values),
        "per_tier": per_tier,
        "confusion": confusion,
        "predicted_distribution": dict(Counter(item.predicted_tier for item in predictions)),
        "hard_n": len(hard),
        # None (not 0.0) when there are no T3-labelled prompts to measure this on — a
        # dataset with zero hard prompts has NOT demonstrated safe hard-prompt routing,
        # and must not silently read as "0% severe under-routing" to the release gate.
        "hard_to_t1_rate": sum(item.predicted_tier == "T1" for item in hard) / len(hard) if hard else None,
        # "v2_fallback" is the marker Signal ClassifierV2 attaches when it degraded to the
        # v1.5 heuristic (timeout/error) — see src/gateway/app/core/classifier_v2.py:485.
        # Always 0 for classifiers that never fall back (v1, v1.5 heuristic).
        "fallback_rate": fallbacks / len(predictions),
        "latency_p50_ms": percentile(latencies, 0.50),
        "latency_p95_ms": percentile(latencies, 0.95),
    }


def routing_slices(
    predictions: list[Prediction], records: list[BenchmarkRecord], field: str
) -> dict[str, dict[str, Any]]:
    record_by_id = {record.id: record for record in records}
    groups: dict[str, list[Prediction]] = {}
    for prediction in predictions:
        value = str(getattr(record_by_id[prediction.id], field))
        groups.setdefault(value, []).append(prediction)
    return {
        value: {
            "n": len(items),
            "accuracy": sum(item.expected_tier == item.predicted_tier for item in items) / len(items),
            "hard_to_t1": sum(
                item.expected_tier == "T3" and item.predicted_tier == "T1" for item in items
            ),
        }
        for value, items in sorted(groups.items())
    }


def load_pricing(path: Path) -> tuple[str, dict[str, dict[str, Any]]]:
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return str(data["premium_baseline_model"]), dict(data["models"])


def _response_cost_usd(run: dict[str, Any], prices: dict[str, dict[str, Any]]) -> float:
    model_id = str(run["model_id"])
    if model_id not in prices:
        raise ValueError(f"No pricing entry for model {model_id!r}")
    price = prices[model_id]
    return (
        int(run["prompt_tokens"]) * float(price["input_per_1m_usd"])
        + int(run["completion_tokens"]) * float(price["output_per_1m_usd"])
    ) / 1_000_000


def _classifier_cost_usd(run: dict[str, Any]) -> float:
    """Classifier LLM spend for this run, reported by the gateway as `router_cost_usd`.

    Missing/zero for records from before this field existed, or for `strong` runs that
    force a model and skip the classifier — never fabricated from token counts here.
    """
    return float(run.get("router_cost_usd") or 0.0)


def _cost_usd(run: dict[str, Any], prices: dict[str, dict[str, Any]]) -> float:
    """Total spend for one run: model response cost plus classifier cost.

    #211 requires cost savings to reflect the true cost of SmartRoute, and the
    classifier itself is not free — folding its cost in here is what keeps
    `cost_savings_pct` from overstating savings.
    """
    return _response_cost_usd(run, prices) + _classifier_cost_usd(run)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for a binomial proportion (default z=1.96).

    Closed-form, no scipy dependency. Returns None for n=0 — an accuracy with no
    samples has no confidence interval to report, not a (0, 0) or (0, 1) guess.
    """
    if n == 0:
        return None
    phat = successes / n
    denom = 1 + z**2 / n
    center = (phat + z**2 / (2 * n)) / denom
    margin = (z * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n**2))) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def mcnemar_exact_p(discordant_smart_only: int, discordant_strong_only: int) -> float | None:
    """Exact two-sided McNemar test on paired binary outcomes (smart correct vs strong correct).

    Only the two discordant counts matter: prompts where the two arms agree
    (both correct or both wrong) carry no information about which arm is better.
    Returns None when there is no discordance to test (b = c = 0).
    """
    b, c = discordant_smart_only, discordant_strong_only
    total = b + c
    if total == 0:
        return None
    tail = min(b, c)
    lower_tail_prob = sum(math.comb(total, i) for i in range(tail + 1)) * (0.5**total)
    return min(1.0, 2 * lower_tail_prob)


def _pairwise_point(pairwise: dict[str, Any], record_id: str) -> float:
    allowed = {"smart", "strong", "tie"}
    forward = pairwise.get("forward")
    reverse = pairwise.get("reverse")
    if forward not in allowed or reverse not in allowed:
        raise ValueError(f"{record_id}: pairwise judgments must be smart, strong, or tie")
    if forward == reverse == "smart":
        return 1.0
    if forward == reverse == "strong":
        return 0.0
    return 0.5


def load_outcomes(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            record_id = str(row.get("id"))
            if record_id in seen:
                raise ValueError(f"{path}:{line_number}: duplicate outcome id {record_id!r}")
            seen.add(record_id)
            if row.get("quality_type") not in {"objective", "pairwise"}:
                raise ValueError(f"{path}:{line_number}: quality_type must be objective or pairwise")
            rows.append(row)
    return rows


def quality_summary(
    outcomes: list[dict[str, Any]],
    predictions: list[Prediction],
    prices: dict[str, dict[str, Any]],
    strong_model: str,
) -> dict[str, Any]:
    prediction_by_id = {item.id: item for item in predictions}
    objective: list[tuple[bool, bool]] = []
    pairwise_points: list[float] = []
    hard_objective: list[tuple[bool, bool]] = []
    hard_pairwise_points: list[float] = []
    critical_failures = 0
    hard_objective_count = 0
    smart_cost = 0.0
    strong_cost = 0.0
    smart_classifier_cost = 0.0
    strong_classifier_cost = 0.0
    failed_count = 0

    for row in outcomes:
        record_id = str(row["id"])
        if record_id not in prediction_by_id:
            raise ValueError(f"Outcome {record_id!r} has no matching benchmark record")
        smart = row["smart"]
        strong = row["strong"]
        if smart.get("error") or strong.get("error"):
            failed_count += 1
            continue
        if str(strong["model_id"]) != strong_model:
            raise ValueError(
                f"{record_id}: strong run used {strong['model_id']!r}, expected {strong_model!r}"
            )
        smart_cost += _cost_usd(smart, prices)
        strong_cost += _cost_usd(strong, prices)
        smart_classifier_cost += _classifier_cost_usd(smart)
        strong_classifier_cost += _classifier_cost_usd(strong)
        prediction = prediction_by_id[record_id]

        if row["quality_type"] == "objective":
            smart_correct = bool(smart["correct"])
            strong_correct = bool(strong["correct"])
            objective.append((smart_correct, strong_correct))
            point = 1.0 if smart_correct else 0.0
            if prediction.expected_tier == "T3":
                hard_objective_count += 1
                hard_objective.append((smart_correct, strong_correct))
                if prediction.predicted_tier == "T1" and not smart_correct:
                    critical_failures += 1
        else:
            point = _pairwise_point(row["pairwise"], record_id)
            pairwise_points.append(point)
            if prediction.expected_tier == "T3":
                hard_pairwise_points.append(point)

    smart_accuracy = mean(item[0] for item in objective) if objective else None
    strong_accuracy = mean(item[1] for item in objective) if objective else None
    smart_accuracy_ci = wilson_interval(sum(item[0] for item in objective), len(objective))
    strong_accuracy_ci = wilson_interval(sum(item[1] for item in objective), len(objective))
    # McNemar's test: only prompts where the two arms disagree carry signal on which is better.
    discordant_smart_only = sum(smart_ok and not strong_ok for smart_ok, strong_ok in objective)
    discordant_strong_only = sum(strong_ok and not smart_ok for smart_ok, strong_ok in objective)
    mcnemar_p_value = mcnemar_exact_p(discordant_smart_only, discordant_strong_only)
    qr_objective = (
        smart_accuracy / strong_accuracy
        if smart_accuracy is not None and strong_accuracy not in {None, 0.0}
        else None
    )
    qr_pairwise = mean(pairwise_points) if pairwise_points else None
    weighted_parts = []
    if qr_objective is not None:
        weighted_parts.append((len(objective), qr_objective))
    if qr_pairwise is not None:
        weighted_parts.append((len(pairwise_points), qr_pairwise))
    quality_retention = (
        sum(count * value for count, value in weighted_parts) / sum(count for count, _ in weighted_parts)
        if weighted_parts
        else None
    )
    hard_smart_accuracy = mean(item[0] for item in hard_objective) if hard_objective else None
    hard_strong_accuracy = mean(item[1] for item in hard_objective) if hard_objective else None
    hard_qr_objective = (
        hard_smart_accuracy / hard_strong_accuracy
        if hard_smart_accuracy is not None and hard_strong_accuracy not in {None, 0.0}
        else None
    )
    hard_weighted_parts = []
    if hard_qr_objective is not None:
        hard_weighted_parts.append((len(hard_objective), hard_qr_objective))
    if hard_pairwise_points:
        hard_weighted_parts.append((len(hard_pairwise_points), mean(hard_pairwise_points)))
    hard_quality_retention = (
        sum(count * value for count, value in hard_weighted_parts)
        / sum(count for count, _ in hard_weighted_parts)
        if hard_weighted_parts
        else None
    )
    return {
        "n": len(outcomes),
        "valid_n": len(outcomes) - failed_count,
        "failed_n": failed_count,
        "objective_n": len(objective),
        "pairwise_n": len(pairwise_points),
        "smart_accuracy": smart_accuracy,
        "strong_accuracy": strong_accuracy,
        "smart_accuracy_ci95": smart_accuracy_ci,
        "strong_accuracy_ci95": strong_accuracy_ci,
        "mcnemar_p_value": mcnemar_p_value,
        "qr_objective": qr_objective,
        "qr_pairwise": qr_pairwise,
        "quality_retention": quality_retention,
        "quality_retention_hard": hard_quality_retention,
        "critical_fail_rate": critical_failures / hard_objective_count if hard_objective_count else None,
        "smart_cost_usd": smart_cost,
        "strong_cost_usd": strong_cost,
        "smart_classifier_cost_usd": smart_classifier_cost,
        "strong_classifier_cost_usd": strong_classifier_cost,
        "cost_savings_pct": (strong_cost - smart_cost) / strong_cost if strong_cost else None,
    }


GATE_THRESHOLDS: dict[str, float] = {
    "quality_retention_min": 0.90,
    "cost_savings_min": 0.60,
    "cost_savings_max": 0.85,
    "severe_underroute_max": 0.05,
    "fallback_rate_max": 0.01,
    "router_latency_p95_ms_max": 1000.0,
    # A quality_retention/cost_savings computed from a tiny surviving sample (most
    # outcome pairs errored) must not read as trustworthy just because that sample
    # happened to look good. Provider/grader failures count against completeness.
    "outcome_failure_rate_max": 0.05,
}


def release_gate(routing: dict[str, Any], quality: dict[str, Any] | None) -> dict[str, Any]:
    """#211's product-release gate.

    Five of #211's six explicit thresholds are checked here; the sixth ("no prompt used
    in the classifier's own system prompt/few-shot examples") is a dataset-hygiene
    property of the input file, not a property of one run's output, so it belongs in
    dataset validation (see `mixed_200_exclusions.txt`) rather than this runtime gate.
    A sixth row here, `outcome_completeness`, is not one of #211's named thresholds —
    it exists because quality_retention/cost_savings alone cannot tell a trustworthy
    measurement from one computed on a handful of survivors after most outcome pairs
    errored; see PR #216 review.

    Each row is independently PASS/FAIL/NOT_MEASURED — NOT_MEASURED never counts as a
    pass, and a metric with no denominator to measure it on (e.g. zero T3-labelled
    prompts for severe under-routing) is NOT_MEASURED, never a default-clean PASS.
    `overall` is FAIL if any measured row fails, PASS only if every row was both
    measured and passed, INCOMPLETE otherwise (e.g. no `--outcomes` file supplied, or
    a dataset with no hard prompts at all).
    """
    rows: list[dict[str, Any]] = []

    def add_row(metric: str, value: float | None, threshold: str, passed: bool | None) -> None:
        verdict = "NOT_MEASURED" if passed is None else ("PASS" if passed else "FAIL")
        rows.append({"metric": metric, "value": value, "threshold": threshold, "verdict": verdict})

    hard_to_t1_rate = routing["hard_to_t1_rate"]
    add_row(
        "severe_underroute_t3_to_t1",
        hard_to_t1_rate,
        f"<= {GATE_THRESHOLDS['severe_underroute_max']:.0%}",
        None if hard_to_t1_rate is None else hard_to_t1_rate <= GATE_THRESHOLDS["severe_underroute_max"],
    )
    add_row(
        "classifier_fallback_rate",
        routing["fallback_rate"],
        f"<= {GATE_THRESHOLDS['fallback_rate_max']:.0%}",
        routing["fallback_rate"] <= GATE_THRESHOLDS["fallback_rate_max"],
    )
    add_row(
        "router_latency_p95_ms",
        routing["latency_p95_ms"],
        f"<= {GATE_THRESHOLDS['router_latency_p95_ms_max']:.0f} ms",
        routing["latency_p95_ms"] <= GATE_THRESHOLDS["router_latency_p95_ms_max"],
    )
    # Provider/grader failures shrink the sample that quality_retention/cost_savings
    # are computed from; a high failure rate must gate on its own, independent of
    # whatever the surviving few pairs happened to show.
    outcome_failure_rate = quality["failed_n"] / quality["n"] if quality and quality["n"] else None
    add_row(
        "outcome_completeness",
        outcome_failure_rate,
        f"failure rate <= {GATE_THRESHOLDS['outcome_failure_rate_max']:.0%}",
        None
        if outcome_failure_rate is None
        else outcome_failure_rate <= GATE_THRESHOLDS["outcome_failure_rate_max"],
    )
    quality_retention = quality["quality_retention"] if quality else None
    add_row(
        "quality_retention",
        quality_retention,
        f">= {GATE_THRESHOLDS['quality_retention_min']:.0%}",
        None
        if quality_retention is None
        else quality_retention >= GATE_THRESHOLDS["quality_retention_min"],
    )
    cost_savings = quality["cost_savings_pct"] if quality else None
    add_row(
        "cost_savings",
        cost_savings,
        f"{GATE_THRESHOLDS['cost_savings_min']:.0%}-{GATE_THRESHOLDS['cost_savings_max']:.0%}",
        None
        if cost_savings is None
        else GATE_THRESHOLDS["cost_savings_min"] <= cost_savings <= GATE_THRESHOLDS["cost_savings_max"],
    )

    verdicts = [row["verdict"] for row in rows]
    if "FAIL" in verdicts:
        overall = "FAIL"
    elif "NOT_MEASURED" in verdicts:
        overall = "INCOMPLETE"
    else:
        overall = "PASS"
    return {"rows": rows, "overall": overall}


def _pct(value: float | None) -> str:
    return "not measured" if value is None else f"{value:.2%}"


def _ci_str(interval: tuple[float, float] | None) -> str:
    return "not measured" if interval is None else f"[{interval[0]:.2%}, {interval[1]:.2%}]"


def _p_str(value: float | None) -> str:
    return "not applicable (no discordant pairs)" if value is None else f"{value:.4f}"


def render_report(
    dataset_path: Path,
    classifier_version: str,
    routing: dict[str, Any],
    quality: dict[str, Any] | None,
    strong_model: str,
    category_slices: dict[str, dict[str, Any]] | None = None,
    language_slices: dict[str, dict[str, Any]] | None = None,
    gate: dict[str, Any] | None = None,
    run_metadata: dict[str, Any] | None = None,
) -> str:
    run_metadata = run_metadata or {}
    commit_sha = run_metadata.get("git_commit_sha")
    classifier_router_timeout_ms = run_metadata.get("classifier_router_timeout_ms")
    configured_router_timeout_ms = run_metadata.get("configured_router_timeout_ms")
    prompt_revision = run_metadata.get("classifier_prompt_revision")
    revisions = run_metadata.get("dataset_revisions") or []

    if classifier_router_timeout_ms is not None:
        router_timeout_line = f"- Router timeout (classifier instance): **{classifier_router_timeout_ms} ms**"
        if (
            configured_router_timeout_ms is not None
            and configured_router_timeout_ms != classifier_router_timeout_ms
        ):
            router_timeout_line += (
                f" — ⚠️ config.yaml declares {configured_router_timeout_ms} ms; "
                "the classifier is NOT using the configured value"
            )
    elif configured_router_timeout_ms is not None:
        router_timeout_line = (
            f"- Router timeout: not read from the classifier instance; "
            f"config.yaml declares {configured_router_timeout_ms} ms (unconfirmed)"
        )
    else:
        router_timeout_line = "- Router timeout: not recorded"
    lines = [
        "# Routing Benchmark Report",
        "",
        "## Run metadata",
        "",
        f"- Dataset: `{dataset_path}`",
        f"- Dataset source revision(s): "
        f"{', '.join(f'`{rev}`' for rev in revisions) if revisions else 'not recorded by source (project gold / hand-authored set)'}",
        f"- Records: {routing['n']}",
        f"- Classifier: `{classifier_version}`",
        f"- Classifier prompt revision: "
        f"{f'`{prompt_revision}`' if prompt_revision else 'not applicable (classifier has no LLM prompt)'}",
        router_timeout_line,
        f"- Gateway commit: {f'`{commit_sha}`' if commit_sha else 'not recorded (not a git checkout, or git unavailable)'}",
        f"- Strong-only baseline: `{strong_model}`",
        "",
        "## Classifier routing",
        "",
        f"- Tier accuracy: **{routing['accuracy']:.2%}**",
        f"- Macro F1: **{routing['macro_f1']:.2%}**",
        f"- Hard prompts routed to T1: **{_pct(routing['hard_to_t1_rate'])}** (n={routing['hard_n']})",
        f"- Classifier fallback rate: **{routing['fallback_rate']:.2%}**",
        f"- Classifier latency: p50 **{routing['latency_p50_ms']:.2f} ms**, "
        f"p95 **{routing['latency_p95_ms']:.2f} ms**",
        "",
        "| Expected \\ Predicted | T1 | T2 | T3 |",
        "|---|---:|---:|---:|",
    ]
    for tier in TIERS:
        row = routing["confusion"][tier]
        lines.append(f"| {tier} | {row['T1']} | {row['T2']} | {row['T3']} |")

    if category_slices:
        lines.extend(
            [
                "",
                "### Category slices",
                "",
                "| Category | N | Tier accuracy | T3→T1 count |",
                "|---|---:|---:|---:|",
            ]
        )
        for category, values in category_slices.items():
            lines.append(
                f"| {category} | {values['n']} | {values['accuracy']:.2%} | {values['hard_to_t1']} |"
            )
    if language_slices:
        lines.extend(
            [
                "",
                "### Language slices",
                "",
                "| Language | N | Tier accuracy | T3→T1 count |",
                "|---|---:|---:|---:|",
            ]
        )
        for language, values in language_slices.items():
            lines.append(
                f"| {language} | {values['n']} | {values['accuracy']:.2%} | {values['hard_to_t1']} |"
            )

    lines.extend(["", "## Response quality and cost", ""])
    if quality is None:
        lines.extend(
            [
                "**Not measured in this run.** No paired model-outcome file was supplied. "
                "Routing labels measure classifier agreement, not answer quality; this report does not conflate them.",
                "",
                "Supply `--outcomes <jsonl>` after running each prompt through SmartRoute and the strong-only baseline.",
            ]
        )
    else:
        lines.extend(
            [
                f"- Paired samples: {quality['n']}",
                f"- Valid paired samples: {quality['valid_n']}; failed/incomplete: {quality['failed_n']}",
                f"- SmartRoute objective accuracy: **{_pct(quality['smart_accuracy'])}** "
                f"(95% Wilson CI: {_ci_str(quality['smart_accuracy_ci95'])}, n={quality['objective_n']})",
                f"- Strong-only objective accuracy: **{_pct(quality['strong_accuracy'])}** "
                f"(95% Wilson CI: {_ci_str(quality['strong_accuracy_ci95'])}, n={quality['objective_n']})",
                f"- McNemar exact test (smart vs strong, paired objective): "
                f"p = {_p_str(quality['mcnemar_p_value'])}",
                f"- Objective QR: **{_pct(quality['qr_objective'])}**",
                f"- Pairwise QR: **{_pct(quality['qr_pairwise'])}**",
                f"- Combined Quality Retention: **{_pct(quality['quality_retention'])}**",
                f"- Hard-task retention: **{_pct(quality['quality_retention_hard'])}**",
                f"- Critical-fail rate: **{_pct(quality['critical_fail_rate'])}**",
                f"- SmartRoute cost: **${quality['smart_cost_usd']:.6f}** "
                f"(of which classifier: ${quality['smart_classifier_cost_usd']:.6f})",
                f"- Strong-only cost: **${quality['strong_cost_usd']:.6f}** "
                f"(of which classifier: ${quality['strong_classifier_cost_usd']:.6f})",
                f"- Cost savings: **{_pct(quality['cost_savings_pct'])}**",
            ]
        )

    if gate is not None:
        lines.extend(
            [
                "",
                "## Release gate (Issue #211)",
                "",
                f"**Overall: {gate['overall']}**",
                "",
                "| Metric | Value | Threshold | Verdict |",
                "|---|---:|---|---|",
            ]
        )
        for row in gate["rows"]:
            value = "not measured" if row["value"] is None else f"{row['value']:.4g}"
            lines.append(f"| {row['metric']} | {value} | {row['threshold']} | {row['verdict']} |")
        lines.extend(
            [
                "",
                "A sixth #211 threshold — no held-out prompt overlaps the classifier's own "
                "system prompt/few-shot examples — is a dataset property, not a run output, "
                "and is not scored in this table.",
            ]
        )

    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "- Tier accuracy/F1 evaluates the classifier against human tier labels; it is not response quality.",
            "- Quality Retention is only reported from paired recorded outputs on identical prompts.",
            "- The strong-only model, pricing snapshot, dataset revision, and judge decisions are run inputs.",
            "- Cost totals include classifier spend (`router_cost_usd` from each outcome run); "
            "cost savings are not overstated by omitting it.",
            "",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--classifier-module", default="src.gateway.app.core.classifier_v1_5")
    parser.add_argument("--classifier-class", default="ClassifierV1_5Heuristic")
    parser.add_argument("--pricing", type=Path, default=Path("src/gateway/app/config/pricing.yaml"))
    parser.add_argument(
        "--gateway-config",
        type=Path,
        default=Path("src/gateway/app/config/config.yaml"),
        help="Read for router_timeout_ms in the report's Run metadata (#211 reproducibility).",
    )
    parser.add_argument("--strong-model")
    parser.add_argument("--outcomes", type=Path)
    parser.add_argument("--output", type=Path, default=Path("evals/benchmark_report.md"))
    parser.add_argument("--json-output", type=Path)
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help=(
            "Exit 1 unless the #211 release gate overall verdict is PASS (CI usage). "
            "FAIL and INCOMPLETE (missing --outcomes, or a metric with nothing to "
            "measure it on) both exit non-zero — an incomplete run must not read as green."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # A relative --gateway-config must resolve against the checkout being benchmarked
    # (--project-root), not the process's CWD — otherwise "benchmark a different
    # checkout" (documented for --project-root/--classifier-module) can silently read
    # config.yaml from the wrong repo.
    if not args.gateway_config.is_absolute():
        args.gateway_config = args.project_root / args.gateway_config
    records = load_dataset(args.dataset)
    classifier = load_classifier(args.project_root, args.classifier_module, args.classifier_class)
    predictions = asyncio.run(evaluate_routing(records, classifier))
    routing = routing_summary(predictions)
    configured_strong_model, prices = load_pricing(args.pricing)
    strong_model = args.strong_model or configured_strong_model
    quality = (
        quality_summary(load_outcomes(args.outcomes), predictions, prices, strong_model)
        if args.outcomes
        else None
    )
    classifier_version = getattr(classifier, "CLASSIFIER_VERSION", None)
    if classifier_version is None:
        classifier_module = sys.modules.get(classifier.__class__.__module__)
        classifier_version = getattr(classifier_module, "CLASSIFIER_VERSION", "unknown")
    category_slices = routing_slices(predictions, records, "category")
    language_slices = routing_slices(predictions, records, "language")
    gate = release_gate(routing, quality)
    classifier_module_for_metadata = sys.modules.get(classifier.__class__.__module__)
    # The classifier is constructed with no arguments (see load_classifier), so it runs
    # on its own constructor default unless something wires config.yaml through — the
    # two can and do disagree (e.g. ClassifierV2AI defaults to 2500ms while config.yaml
    # currently declares 4000ms). classifier_router_timeout_ms is what actually applied
    # to this run's classify() calls; configured_router_timeout_ms is only what the
    # gateway's config file declares, kept for comparison, not asserted as what ran.
    classifier_router_timeout_ms = getattr(classifier, "router_timeout_ms", None)
    configured_router_timeout_ms = read_router_timeout_ms(args.gateway_config)
    run_metadata = {
        "git_commit_sha": git_commit_sha(args.project_root),
        "classifier_router_timeout_ms": classifier_router_timeout_ms,
        "configured_router_timeout_ms": configured_router_timeout_ms,
        "classifier_prompt_revision": getattr(classifier_module_for_metadata, "PROMPT_REVISION", None),
        "dataset_revisions": dataset_revisions(args.dataset),
    }
    report = render_report(
        args.dataset,
        str(classifier_version),
        routing,
        quality,
        strong_model,
        category_slices,
        language_slices,
        gate,
        run_metadata,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(
                {
                    "routing": routing,
                    "category_slices": category_slices,
                    "language_slices": language_slices,
                    "quality": quality,
                    "gate": gate,
                    "run_metadata": run_metadata,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(
        f"Wrote {args.output} ({routing['n']} records, accuracy={routing['accuracy']:.2%}, "
        f"gate={gate['overall']})"
    )
    if args.fail_on_gate and gate["overall"] != "PASS":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
