# Classifier v2 vs GPT-4o baselines

Run date: 2026-08-27
Source: `dev` at `d24c7b5fed734ebae91e29cc785dc48239f0fdd1`

## Result

Classifier v2 beat GPT-4o-mini on HumanEval+ and MATH-500, but not on MMLU-Pro. It also
beat the GPT-4o point estimate on HumanEval+ and MATH-500; neither difference versus GPT-4o
was statistically significant. On MATH-500, the v2 improvement over GPT-4o-mini was
significant (exact two-sided paired p = 0.0059).

| Benchmark | N | GPT-4o-mini | Classifier v2 | GPT-4o | v2 cost | v2 vs low | v2 savings vs high |
|---|---:|---:|---:|---:|---:|---:|---:|
| MMLU-Pro | 420 | 41.43% | 39.05% | 45.95% | $0.05855 | 4.63x | 73.09% |
| HumanEval+ | 164 | 81.71% | 87.20% | 84.15% | $0.09667 | 6.85x | 58.98% |
| MATH-500 | 500 | 59.80% | 64.80% | 61.60% | $0.27496 | 1.52x | 89.47% |

Across the 1,084 scored examples, total spend was $0.20791 for GPT-4o-mini, $0.43019 for
classifier v2, and $3.06505 for GPT-4o. That makes v2 2.07x the low baseline's cost and
85.96% cheaper than the high baseline. The combined 58.21% v2 score is a descriptive
micro-average only because these benchmarks test different capabilities.

## Statistical checks

| Benchmark | Comparison | Discordant pairs (v2 / baseline) | Exact two-sided p |
|---|---|---:|---:|
| MMLU-Pro | v2 vs GPT-4o-mini | 54 / 64 | 0.4075 |
| MMLU-Pro | v2 vs GPT-4o | 53 / 82 | 0.0156 |
| HumanEval+ | v2 vs GPT-4o-mini | 17 / 8 | 0.1078 |
| HumanEval+ | v2 vs GPT-4o | 14 / 9 | 0.4049 |
| MATH-500 | v2 vs GPT-4o-mini | 51 / 26 | 0.0059 |
| MATH-500 | v2 vs GPT-4o | 40 / 24 | 0.0599 |

Wilson 95% intervals were 36.82-46.20%, 34.50-43.79%, and 41.24-50.73% on MMLU-Pro;
75.09-86.88%, 81.22-91.47%, and 77.78-88.95% on HumanEval+; and 55.44-64.01%,
60.52-68.86%, and 57.26-65.76% on MATH-500. Each sequence is low, v2, high.

## Routing and operational caveat

The benchmark left `models.yaml` unchanged. Classifier v2 therefore used the current dev
routes and fallbacks:

- MMLU-Pro: 298 GPT-5.4-nano, 108 GPT-5.4-mini, 4 GPT-5.4, and 10 Llama 3.3 70B.
- HumanEval+: 5 GPT-5.4-nano and 159 GPT-5.4-mini.
- MATH-500: 409 GPT-5.4-nano and 91 GPT-5.4-mini.

The live v2 classifier hit its configured 2.5-second deadline and emitted `v2_fallback` on
239/420 MMLU-Pro, 60/164 HumanEval+, and 296/500 MATH-500 examples. These are valid
end-to-end operational scores for the current dev configuration, but they do not isolate the
quality of successful v2 classifier calls. MMLU-Pro in particular is mostly fallback behavior.

The fixed GPT-4o-mini and GPT-4o arms bypassed the LLM classifier, reported
`heuristic-v1`, and had zero router cost. This keeps their costs from being inflated by a
classifier they do not use.

## Reproducibility

- MMLU-Pro: 420-example stratified set, source revision
  `b189ec765aa7ed75c8acfea42df31fdae71f97be`.
- HumanEval+: all 164 tasks, graded offline with `evalplus==0.3.1`; dataset hash
  `fe585eb4df8c88d844eeb463ea4d0302`.
- MATH-500: all 500 tasks, source revision
  `6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be`, normalized SHA-256
  `eac901cebec0c10729ba74738b38c7922c3f0729c04a3e563c8581bdc993d3ac`, graded
  offline with `math-verify==0.9.0`.
- All arms completed every example with no permanent request errors. Live generation was
  checkpointed by task ID; graders ran in pinned containers with networking disabled.

Machine-readable results, including costs, confidence intervals, paired counts, routing
distributions, and MATH-500 slices, are in
`evals/classifier_v2_gpt4o_baselines_metrics.json`.
