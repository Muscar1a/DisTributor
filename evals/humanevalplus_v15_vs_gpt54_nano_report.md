# HumanEval+ — Classifier v1.5 vs GPT-5.4-nano

## Decision

Classifier v1.5 produces slightly higher coding quality than forcing every request to
GPT-5.4-nano, but this run does **not** demonstrate better raw quality per dollar.

On the full 164-task HumanEval+ suite, v1.5 passes 142 tasks versus 138 for all-nano, a gain
of four passes (2.44 percentage points). The routed arm costs $0.093283 versus $0.037480 for
all-nano: 2.49 times the cost. Cost per passing solution is therefore 2.42 times higher for
v1.5. The exact paired McNemar/sign test gives p = 0.5034, so the observed four-pass advantage
is not statistically distinguishable from paired run variation at conventional thresholds.

The defensible claim from this run is: **v1.5 buys a small absolute quality increase over
all-nano, at a substantial incremental cost.** It does not establish superior pass-per-dollar
efficiency.

## Run metadata

- Date: 2026-08-24–25
- Benchmark: HumanEval+ v0.1.10 via EvalPlus 0.3.1
- Dataset hash: `fe585eb4df8c88d844eeb463ea4d0302`
- Records: 164; 164 valid v1.5 outputs and 164 valid nano outputs
- Routed arm: classifier `heuristic-v1.5`; GPT-5.4-mini on 154 tasks and GPT-5.4-nano on 10
- Comparison arm: GPT-5.4-nano forced on all 164 tasks
- Generation: temperature 0 and 1,024 output-token limit
- Grading: pinned `smartroute-evalplus:0.3.1` container, network disabled, four CPUs, 6 GiB
- Reliability: zero permanent provider errors
- Reuse note: the v1.5 generations are the cached 2026-08-23 full-suite arm; the nano
  generations are new. Prompts, dataset revision, grader, and generation settings match, but
  the calls were not made in the same wall-clock run.

## Results

| Metric | v1.5 routing | All GPT-5.4-nano | Difference |
|---|---:|---:|---:|
| Valid submissions | 164/164 | 164/164 | 0 |
| HumanEval base pass@1 | 146/164 (89.02%) | 144/164 (87.80%) | +1.22 points |
| HumanEval+ pass@1 | 142/164 (86.59%) | 138/164 (84.15%) | +2.44 points |
| Prompt tokens | 25,636 | 25,636 | 0 |
| Completion tokens | 18,319 | 25,882 | -7,563 |
| Modeled provider cost | $0.093283 | $0.037480 | +$0.055803 |
| Cost per Plus pass | $0.000657 | $0.000272 | 2.42× higher |
| Plus passes per dollar | 1,522 | 3,682 | 58.66% lower |

- Quality retention relative to all-nano: **102.90%**.
- Additional modeled cost per additional passing task: **$0.013951**.
- Paired outcomes: both pass 130; v1.5-only pass 12; nano-only pass 8; neither passes 14.
- Exact two-sided paired McNemar/sign test over 20 discordant tasks: **p = 0.5034**.

## Interpretation

All-nano is the stronger choice if the objective is strictly maximum passing solutions per
dollar. V1.5 is preferable only if the 2.44-point observed pass-rate increase is worth a 149%
cost increase, and this single run does not establish that the increase is reproducible.

For a stronger product claim, repeat both arms from scratch across multiple seeds/runs and
report a paired confidence interval. A policy claim should be framed as a quality-floor or
Pareto-frontier decision, not as unconditional quality-per-cost dominance.

## Artifacts

- Paired generations: `evals/results/humanevalplus_v15_vs_gpt54_nano_paired_164.jsonl`
- Nano-only generation cache: `evals/results/humanevalplus_gpt54_nano_baseline_164.jsonl`
- Machine-readable grading: `evals/humanevalplus_v15_vs_gpt54_nano_metrics.json`
