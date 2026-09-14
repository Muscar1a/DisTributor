# Routing benchmark evaluation design (Classifier v1.5)

## 1. Decision summary

The evaluation is deliberately split into two experiments:

1. **Classifier evaluation** asks whether v1.5 assigns the intended tier, how often it dangerously under-routes hard prompts, and how much latency it adds. This experiment is offline and does not call an LLM.
2. **System evaluation** asks whether responses produced after routing retain the strong model's quality while reducing actual token cost. This experiment uses paired, recorded outputs from SmartRoute and a strong-only baseline.

These measurements must not be merged conceptually. Agreement with an `expected_tier` label is routing accuracy, not answer quality. The runner therefore leaves Quality Retention and Cost Savings explicitly “not measured” until paired model outcomes are supplied.

## 2. Dataset choice

### 2.1 First executable benchmark: project gold set

The first v1.5 run uses `src/evals/datasets/mixed_200.jsonl` because it is:

- bilingual Vietnamese/English and close to the gateway's expected traffic;
- already labeled with T1/T2/T3, category, and difficulty;
- large enough to reveal tier collapse, over-routing, and catastrophic T3→T1 mistakes quickly;
- local and revisionable, so classifier changes can be compared without network or provider variance.

It is appropriate for **routing accuracy, macro F1, confusion matrix, T3→T1 rate, and classifier latency**. It is not an answer-quality benchmark: most records have no reference answer or executable test. Its current AI-assisted labels and pending PII/annotation reviews are a limitation, so results are diagnostic until the human review is complete.

### 2.2 Standard response benchmarks

The staged standard suite is:

| Dataset | Why selected | Primary scoring | Role |
|---|---|---|---|
| EvalPlus (HumanEval+/MBPP+) | Executable tests and stronger hidden tests; directly targets v1.5's coding focus | pass@1 | Primary coding quality |
| LiveCodeBench | Time-sliced coding problems reduce contamination risk and cover newer tasks | pass@1 | Coding robustness |
| MATH-500 | Deterministic final answers across a useful reasoning range | exact/equivalence match | Math regression |
| GPQA Diamond | Expert-level questions stress dangerous under-routing | exact multiple-choice accuracy | Hard-task guardrail |
| MMLU-Pro | Broad non-coding coverage and more challenging choices than classic MMLU | exact multiple-choice accuracy | Domain regression |
| MT-Bench-101 | Multi-turn categories expose route changes caused by conversation state | fixed pairwise judge rubric | Session-routing phase |

The order matters. EvalPlus and LiveCodeBench come first because v1.5 was designed mainly to separate coding task bands C1/C2/C3. MATH-500, GPQA Diamond, and MMLU-Pro ensure that coding improvements do not regress non-coding routing. MT-Bench-101 is a later phase because it evaluates session routing as well as the single-turn classifier and therefore needs conversation-state capture.

Each imported record must be normalized to JSONL with at least `id`, `prompt`, `benchmark`, `expected_tier`, `category`, and `language`. Dataset revision, split, license, and conversion script must be pinned before publishing cross-run comparisons. `expected_tier` is a project annotation; it must not be inferred from whether one particular model happened to answer correctly.

## 3. Baseline model decision

The baseline is **the model named by `premium_baseline_model` in the committed pricing configuration**. The v1.5 evaluation checkout currently uses OpenAI `gpt-5.4` as the T3 primary and premium baseline. The runner reads this setting rather than hard-coding a dated provider model ID.

For the current OpenAI-only primary ladder, T1 uses `gpt-5.4-nano`, T2 uses `gpt-5.4-mini`, and T3 uses `gpt-5.4`. Gemini and Groq remain fallback providers so an OpenAI outage does not remove the gateway's fallback behavior.

This is the correct comparison for the product claim: “route selectively instead of sending every request to the strongest model in the serving pool.” The baseline must therefore:

- use the same premium model on every prompt;
- receive the identical normalized messages and generation parameters as the routed run;
- be executed once per prompt and cached by dataset revision + prompt + parameters + model ID;
- record actual input/output token usage, not estimate premium cost from cheap-model token counts;
- fail the validation if recorded outcomes name a different strong model.

Using an external frontier model as the baseline would mix routing gains with a different product/provider configuration. External models may be used as judges, but not silently substituted for the strong-only serving baseline. If the configured premium model changes, the report is a new benchmark series and must name the new snapshot.

## 4. Quality definition

Quality is measured on identical prompts with paired SmartRoute and strong-only outputs.

### 4.1 Objective tasks

For executable or exact-answer datasets:

```text
QR_objective = accuracy_smartroute / accuracy_strong_only
```

Correctness comes from unit tests, exact multiple-choice matching, or the benchmark's pinned equivalence grader. Classifier tier agreement never substitutes for correctness.

### 4.2 Open-ended tasks

For records without an objective grader, a fixed judge from a model family outside the routed serving chain compares SmartRoute and strong-only responses twice with positions swapped. Each record scores:

- `1.0`: SmartRoute wins both orders;
- `0.0`: strong-only wins both orders;
- `0.5`: ties, split decisions, or inconsistent orders.

`QR_pairwise` is the mean of these per-record points. Temperature is zero and the committed rubric covers instruction following, factual correctness, and completeness.

### 4.3 Combined quality and safety guards

```text
QR = (N_objective × QR_objective + N_pairwise × QR_pairwise)
     / (N_objective + N_pairwise)

Target conditions:
  QR >= 0.95
  QR_hard >= 0.90
  critical_fail_rate <= 0.05
```

`critical_fail_rate` is the fraction of hard objective prompts that v1.5 routes to T1 and SmartRoute answers incorrectly. The hard-task condition prevents strong performance on easy prompts from hiding dangerous under-routing.

If strong-only objective accuracy is zero, `QR_objective` is undefined rather than infinity or zero. The report must expose that condition. Missing outputs, judge failures, and provider errors are recorded separately; they are not silently scored as ties.

## 5. Cost definition

For each recorded model response:

```text
cost = prompt_tokens × input_price_per_1M / 1,000,000
     + completion_tokens × output_price_per_1M / 1,000,000

Cost Savings % = (cost_strong_only - cost_smartroute) / cost_strong_only
```

Prices come from the pinned project pricing snapshot. Both runs use their own actual token counts. A zero-cost mock model is useful for testing the harness but cannot support a production savings claim.

## 6. Runner and outcome contract

Implementation tracking: GitHub issue #159 is the answer-quality follow-up to #149.

Routing-only example:

```powershell
.\.venv\Scripts\python.exe src/evals/run_benchmark_eval.py `
  --project-root . `
  --dataset src/evals/datasets/mixed_200.jsonl `
  --output evals/benchmark_report.md
```

When this checkout does not contain v1.5, `--project-root` may target a checkout that does. The default import is `src.gateway.app.core.classifier_v1_5.ClassifierV1_5Heuristic`.

For response quality, pass `--outcomes results.jsonl`. Each line is a paired record:

```json
{"id":"sample-1","quality_type":"objective","smart":{"model_id":"gemini-flash","prompt_tokens":100,"completion_tokens":30,"correct":true,"router_cost_usd":0.00002},"strong":{"model_id":"gemini-pro","prompt_tokens":100,"completion_tokens":40,"correct":true,"router_cost_usd":0.0}}
```

`router_cost_usd` is the classifier's own LLM spend for that run, as reported by the gateway
(`src/gateway/app/api/schemas.py` §9.1; zero for the heuristic classifiers, non-zero for `classifier_v2`).
`run_answer_quality_eval.py` already records it on every run. `smart_cost_usd`/`strong_cost_usd` in the
report include it — omitting it would understate SmartRoute's true cost and overstate `cost_savings_pct` —
and it is also broken out on its own line so classifier spend stays visible rather than buried in the
total. The field is optional and defaults to 0 for older outcome files that predate it.

An open-ended record additionally contains:

```json
{"pairwise":{"forward":"smart","reverse":"tie"}}
```

Allowed judge values are `smart`, `strong`, and `tie`. Raw responses and judge rationales should be retained in the run artifact even though the metric loader only requires the normalized verdicts.

The first objective sample can be prepared and dry-run without provider usage:

```powershell
.\.venv\Scripts\python.exe src/evals/prepare_standard_benchmark.py math500 `
  --revision 6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be `
  --limit 20 --output evals/datasets/math500_sample_20.jsonl

.\.venv\Scripts\python.exe src/evals/run_answer_quality_eval.py `
  --dataset evals/datasets/math500_sample_20.jsonl `
  --output evals/results/math500_sample_20_outcomes.jsonl
```

The paired runner is a dry run unless `--execute` is supplied. That flag exists to prevent an accidental 2×N provider-cost event. Set `SMARTROUTE_API_KEY` when the target gateway requires client authentication.
`--requests-per-minute` throttles the combined SmartRoute and strong-only request stream; its conservative default is 6 RPM.

### 6.1 Four-arm cost/latency runner (`run_full_eval.py`)

`run_benchmark_eval.py` scores the classifier offline; `run_full_eval.py` drives a live gateway and
compares four routing arms end to end. Arms are `all_cheap` (forced T1), `all_premium` (forced T3,
the savings baseline), `random` (seeded tier draw), and `smartroute` (gateway decides).

```powershell
# plan only, no provider calls
.\.venv\Scripts\python.exe src/evals/run_full_eval.py --dry-run --limit 0

# free smoke run (needs USE_MOCK_PROVIDERS=true in .env)
.\.venv\Scripts\python.exe src/evals/run_full_eval.py --limit 5

# real run, resumable; rerun the same command to retry only failed calls
.\.venv\Scripts\python.exe src/evals/run_full_eval.py --limit 0 --api-key $env:SMARTROUTE_API_KEY

# re-aggregate an existing raw file without calling the API
.\.venv\Scripts\python.exe src/evals/run_full_eval.py --summary-only
```

Cost guards: results are appended per row, a rerun skips any `(id, mode)` pair whose **most recent**
attempt succeeded (this is also the `all_premium` baseline cache), and the default `--limit` is 5 so a
full run must be requested explicitly with `--limit 0`.

Outputs land in `src/evals/results/` — `raw.jsonl` (git-ignored, contains real prompts and
responses), a `raw.jsonl.fingerprint.json` sidecar (also git-ignored), and `eval_summary.md`. Per-row
cost includes `cost_routing_usd`, so the classifier's own token spend is inside the reported totals.

Resume safety: before making any real gateway call, the runner computes a fingerprint of
`--dataset` (content hash), `--seed`, `--policy`, `--max-tokens`, `--base-url`, and the gateway's own
`commit_sha` (read live from `GET /healthz`, issue #197 — not assumed from local git state, since the
gateway may be remote). If a fingerprint already exists next to `--raw` and any of those differ, the
run exits with a diff instead of silently resuming into a mismatched cache; pass `--no-resume` to
intentionally start over on that same `--raw` file, or point `--raw` at a fresh path. `--limit` and
`--modes` are deliberately excluded — growing `--limit` or adding a mode is the tool's normal
incremental-run workflow, not a reason to invalidate cached rows. `--dry-run` and `--summary-only`
never call the network and are not subject to this check.

Scope limits to keep in mind when citing its numbers:

- It measures cost, latency, tier distribution, fallback count, and routing agreement against
  `expected_tier`. It does **not** grade answer correctness — end-to-end answer quality comes from
  `run_answer_quality_eval.py` plus the graders in `src/evals/benchmarks/objective.py`.
- The `random` arm draws tiers in dataset order, so its numbers are only comparable across runs when
  the dataset file itself is pinned.
- `all_premium` is a **tier baseline, not a fixed-model baseline**: it sends `force_tier=T3` only, not
  `force_model`. If T3's primary model is unavailable, the gateway falls back to another model in the
  same tier rather than erroring the request — chosen deliberately over pinning `force_model`, which
  would turn a primary-model outage into a hole in the report instead of a routed answer. Each mode's
  "Số lần fallback" column in `eval_summary.md` reports whether this happened; a non-zero count on
  `all_premium` means that day's baseline cost/quality wasn't from a single model on every prompt.
- `eval_summary.md` itself does not yet print a "Run metadata" section (dataset/seed/gateway commit as
  readable lines) the way `run_benchmark_eval.py`'s report does — the fingerprint sidecar has the same
  data machine-readable, but a human has to open that file rather than the report.

### 6.2 Run metadata (#211 reproducibility)

The Markdown report's "Run metadata" section, and `run_metadata` in `--json-output`, now
record — best-effort, never blocking the run if unavailable:

- **Gateway commit** (`git rev-parse HEAD` under `--project-root`); "not recorded" outside a
  git checkout. This is the commit of the *local checkout used to import the classifier for
  routing*, not necessarily the commit of a deployed gateway that produced a `--outcomes`
  file — those can differ if `--outcomes` was collected from a live server on another commit.
- **Router timeout**, reported as two separate values because they can and do disagree:
  - `classifier_router_timeout_ms` — read from the live classifier instance's own
    `router_timeout_ms` attribute after `load_classifier()` constructs it with no
    arguments. This is what actually applied to this run's `classify()` calls.
  - `configured_router_timeout_ms` — `routing.router_timeout_ms` from `--gateway-config`
    (default `src/gateway/app/config/config.yaml`, resolved against `--project-root` when
    given as a relative path). Only what the config file *declares*; not asserted as what ran.
  - `ClassifierV1_5Heuristic` reads its own default from `load_gateway_settings()`, so it
    normally agrees with the config file. `ClassifierV2AI` hard-codes `2500` as its
    constructor default and does **not** consult config.yaml, so it disagrees whenever the
    config value has been tuned away from that default (it currently has: `4000`) — the
    report renders a `⚠️` warning line in that case rather than silently showing the
    config-declared number as if it were what ran.
- **Classifier prompt revision** (the classifier module's `PROMPT_REVISION`, e.g. `r5` for
  ClassifierV2); "not applicable" for classifiers with no LLM prompt (v1, v1.5 heuristic).
- **Dataset source revision(s)** — the distinct `source_revision` values found in the dataset
  file itself, as written by `prepare_standard_benchmark.py`; empty for the project gold set
  and hand-authored sets, which don't carry this field.

None of these raise on failure — a missing git checkout, an unreadable `--gateway-config`, or
a malformed one (bad YAML syntax, non-mapping structure, non-numeric value) all degrade the
relevant metadata line to "not recorded"/"unconfirmed", they do not fail the benchmark run.

### 6.3 Statistical significance and the #211 release gate

For objective (accuracy/pass@1) records, `run_benchmark_eval.py` now reports, per run:

- A 95% Wilson score interval for SmartRoute's and the strong-only baseline's accuracy
  (`wilson_interval`, closed-form — no scipy/numpy dependency).
- An exact two-sided McNemar test p-value comparing SmartRoute vs strong-only on the same
  paired prompts (`mcnemar_exact_p`), since this is a paired design, not two independent
  samples.

These do not yet cover pairwise (open-ended, judge-scored) records — only objective ones.

`release_gate()` checks five of #211's six product-acceptance thresholds against one run
(quality retention ≥ 90%, cost savings 60–85%, severe T3→T1 under-routing ≤ 5%, classifier
fallback ≤ 1%, router p95 ≤ 1s), plus a sixth row of its own — `outcome_completeness`
(outcome-pair failure rate ≤ 5%) — and renders a PASS/FAIL/NOT_MEASURED table in both the
Markdown report and `--json-output`. Pass `--fail-on-gate` to exit non-zero unless the
overall verdict is PASS — FAIL *and* INCOMPLETE (missing `--outcomes`, or a metric with no
denominator, e.g. zero T3-labelled prompts) both exit non-zero, so an incomplete run cannot
read as green in CI. The default (no `--fail-on-gate`) stays exit 0 either way, so existing
report-generation usage is unaffected. The named sixth #211 threshold (no held-out prompt
appears in the classifier's own system prompt/few-shot examples) is a property of the
*dataset*, not of a run's output, so it is not scored by this gate — it belongs with
dataset validation instead (`mixed_200_exclusions.txt`).

`outcome_completeness` exists because `quality_retention`/`cost_savings` alone cannot tell a
trustworthy measurement from one computed on a handful of survivors after most outcome pairs
errored — e.g. 1 valid pair out of 500 that happens to look good would otherwise gate PASS.
Similarly, `routing_summary()["hard_to_t1_rate"]` is `None` (not `0.0`) when a dataset has
zero T3-labelled prompts, so `severe_underroute_t3_to_t1` reads NOT_MEASURED rather than a
default-clean PASS on a metric nothing was actually measured against.

**This machinery is not yet backed by trustworthy data.** `smart-model`/`strong-model` in
the examples above are toy fixtures. A real gate verdict needs the full-size datasets from
§2.2 (MMLU-Pro 420, MATH-500 500, HumanEval+ 164) and real paired outcomes from
`run_answer_quality_eval.py --execute`; a 20-sample stub run will produce Wilson intervals
too wide to support any product claim.

## 7. Reproducibility and reporting rules

- Commit dataset adapters and pin upstream revisions/splits.
- Record classifier commit, classifier version, model IDs, generation parameters, pricing snapshot, and outcome cache hash. §6.2 automates the commit/timeout/prompt-revision part of this for `run_benchmark_eval.py` output; it still doesn't cover the paired outcome runner or provider generation parameters.
- Report per-benchmark metrics before any aggregate.
- Never publish Quality Retention from tier labels or synthetic model-quality ranks.
- Treat the initial 200-prompt result as diagnostic until its annotations are human-verified.
- §6.3's Wilson intervals and McNemar test cover objective-task accuracy; add bootstrap confidence intervals for pairwise (judge-scored) Quality Retention before making a final claim there.
