# HumanEval+ Full OpenAI Ladder Report

## Decision

Classifier v1.5 does **not** meet the coding-quality promotion gate on the full HumanEval+
suite. SmartRoute retains 92.81% of the GPT-5.4 baseline pass rate, below the predeclared 95%
target, and trails the baseline by 6.71 percentage points, above the allowed 5-point gap.

The run does confirm the cost hypothesis: SmartRoute reduces modeled provider cost by 71.36%.
Classifier v2 should use this run as its coding baseline and must recover at least four
additional passing tasks without giving up the cost advantage.

## Run metadata

- Date: 2026-08-23
- Benchmark: HumanEval+ v0.1.10 via EvalPlus 0.3.1
- Dataset: `evals/datasets/humanevalplus_full_164.jsonl`
- Dataset hash: `fe585eb4df8c88d844eeb463ea4d0302`
- Records: 164 paired prompts; 164 valid routed and baseline responses
- Classifier: `heuristic-v1.5`
- Routed models: GPT-5.4-mini on 154 tasks; GPT-5.4-nano on 10 tasks
- Strong-only baseline: GPT-5.4
- Generation: temperature 0, 1,024 output-token limit, 30 requests/minute, four workers
- Reliability: zero permanent API errors and zero retries
- Execution: pinned EvalPlus Docker image, no network, four CPUs, 6 GiB memory

## Dataset, baseline, and quality definition

HumanEval+ measures executable Python answer quality. A submission counts as correct only when
it passes both the original HumanEval tests and the stricter Plus tests. This is more relevant
to coding routing than classifier-label agreement or multiple-choice accuracy, although it
still represents isolated functions rather than repository-level software engineering.

GPT-5.4 is the configured T3 baseline. Each prompt was sent once through SmartRoute and once
directly to GPT-5.4, so quality and cost are paired on identical inputs.

- Primary metric: HumanEval+ pass@1.
- Quality retention (QR): routed pass@1 divided by GPT-5.4 pass@1.
- Promotion gate: QR at least 95% and an absolute pass@1 gap no greater than 5 points.
- Cost: recorded token usage priced by `src/gateway/app/config/pricing.yaml`.

## Full result

| Metric | SmartRoute | GPT-5.4 baseline | Difference |
|---|---:|---:|---:|
| Valid submissions | 164/164 | 164/164 | 0 |
| HumanEval base pass@1 | 146/164 (89.02%) | 158/164 (96.34%) | -7.32 points |
| HumanEval+ pass@1 | 142/164 (86.59%) | 153/164 (93.29%) | -6.71 points |
| Prompt tokens | 25,636 | 25,636 | 0 |
| Completion tokens | 18,319 | 17,439 | +880 |
| Modeled cost | $0.093283 | $0.325675 | -$0.232392 |

- Quality retention: **92.81%** — fails the 95% gate by 2.19 points.
- Modeled cost savings: **71.36%**.
- Paired outcomes: both pass 142; SmartRoute-only pass 0; GPT-5.4-only pass 11;
  neither passes 11.
- Exact two-sided sign/McNemar test on the 11 discordant pairs: **p = 0.00098**. The observed
  quality loss is unlikely to be explained by paired sampling noise alone.

## Classifier v2 acceptance target

Hold the GPT-5.4 baseline outputs fixed for a comparable routing experiment. With 153 baseline
passes, v2 needs at least **146/164 routed passes (89.02%)** to satisfy QR >= 95%; this also
satisfies the five-point absolute-gap gate. That means recovering at least four of v1.5's
misses. Preserve at least 60% modeled cost savings as a secondary constraint.

The highest-value v2 analysis set is the 11 tasks passed only by GPT-5.4:

| Task | v1.5 routed model |
|---|---|
| HumanEval/95 | GPT-5.4-mini |
| HumanEval/101 | GPT-5.4-mini |
| HumanEval/106 | GPT-5.4-mini |
| HumanEval/108 | GPT-5.4-mini |
| HumanEval/115 | GPT-5.4-mini |
| HumanEval/126 | GPT-5.4-mini |
| HumanEval/127 | GPT-5.4-mini |
| HumanEval/129 | GPT-5.4-nano |
| HumanEval/130 | GPT-5.4-mini |
| HumanEval/134 | GPT-5.4-mini |
| HumanEval/147 | GPT-5.4-mini |

These failures show that simply eliminating T1 routing is insufficient: ten of the eleven
quality-regression tasks were already routed to GPT-5.4-mini. V2 needs better signals for when
apparently compact function-completion prompts require T3 capability, or a targeted escalation
policy informed by risk rather than prompt length alone.

## Reproduction

Raw paired generations are in the gitignored file
`evals/results/humanevalplus_openai_ladder_paired_164.jsonl`.

Execute generated code only in the pinned, network-disabled container:

```powershell
docker run --rm --network none --cpus 4 --memory 6g `
  -v "${PWD}:/work" smartroute-evalplus:0.3.1 `
  python -m src.evals.grade_evalplus_subset `
  --outcomes evals/results/humanevalplus_openai_ladder_paired_164.jsonl `
  --output evals/humanevalplus_openai_ladder_full_metrics.json `
  --dataset-hash fe585eb4df8c88d844eeb463ea4d0302
```

Machine-readable results are stored in
`evals/humanevalplus_openai_ladder_full_metrics.json`.
