# MMLU-Pro Stratified Three-Arm Benchmark

## Decision

Classifier v1.5 sits between the two fixed-model baselines on both quality and cost, but it
does not meet the project's quality-retention gate and does not beat all-nano on raw
correct-answers-per-dollar efficiency.

Compared with all GPT-5.4-nano, v1.5 answers 17 more questions correctly (+4.05 percentage
points) for 2.39 times the cost. The paired difference is suggestive but not statistically
significant (exact two-sided McNemar p = 0.0857). Compared with all GPT-5.4, v1.5 saves 80.75%
of modeled provider cost but retains only 64.13% of its accuracy, far below the 95% target.

The defensible product claim is: **v1.5 offers a middle quality/cost operating point, not
quality-per-dollar dominance.**

## Run metadata

- Date: 2026-08-25
- Benchmark: MMLU-Pro, 420-question deterministic stratified subset
- Sampling: 30 questions from each of 14 categories, ranked by SHA-256 of seed + record ID
- Selection seed: `mmlu-pro-stratified-420-v1`
- Dataset SHA-256: `1EB48EF14C41BA1F90145B0AC3D86EAEEEBF9C43D21078807B6288CB250A8596`
- Arms: all GPT-5.4-nano; classifier `heuristic-v1.5`; all GPT-5.4
- Routed distribution: 289 nano, 124 mini, 7 GPT-5.4
- Generation: temperature 0, 16 output-token limit
- Validity: 420/420 successful responses in every arm; zero permanent provider errors
- Scoring: exact multiple-choice answer match
- Cost: recorded token usage priced by `src/gateway/app/config/pricing.yaml`

## Overall results

| Metric | All nano | Classifier v1.5 | All GPT-5.4 |
|---|---:|---:|---:|
| Correct | 160/420 | 177/420 | 276/420 |
| Accuracy | 38.10% | 42.14% | 65.71% |
| Wilson 95% interval | 33.58-42.83% | 37.51-46.92% | 61.05-70.09% |
| Prompt tokens | 79,056 | 79,056 | 79,056 |
| Completion tokens | 1,731 | 2,004 | 1,704 |
| Modeled cost | $0.017975 | $0.042966 | $0.223200 |
| Cost per correct answer | $0.000112 | $0.000243 | $0.000809 |
| Correct answers per dollar | 8,901 | 4,119 | 1,237 |

## Pairwise interpretation

### v1.5 versus all-nano

- Absolute accuracy gain: **+4.05 points**; relative accuracy gain: **+10.63%**.
- Cost premium: **+139.04%**.
- Incremental cost per additional correct answer: **$0.001470**.
- Paired outcomes: both correct 125; v1.5-only correct 52; nano-only correct 35;
  neither correct 208.
- Exact two-sided paired McNemar/sign test: **p = 0.0857**.

### v1.5 versus all GPT-5.4

- Quality retention: **64.13%**.
- Absolute accuracy gap: **-23.57 points**.
- Modeled cost savings: **80.75%**.
- Paired outcomes: both correct 153; v1.5-only correct 24; GPT-5.4-only correct 123;
  neither correct 120.
- Exact two-sided paired McNemar/sign test: **p = 3.18e-17**.

## Category results

Each cell is correct answers out of 30.

| Category | All nano | v1.5 | All GPT-5.4 |
|---|---:|---:|---:|
| Biology | 18 | 17 | 26 |
| Business | 7 | 4 | 12 |
| Chemistry | 8 | 10 | 11 |
| Computer science | 10 | 14 | 23 |
| Economics | 14 | 16 | 21 |
| Engineering | 7 | 12 | 14 |
| Health | 16 | 18 | 25 |
| History | 10 | 15 | 20 |
| Law | 8 | 10 | 17 |
| Math | 8 | 6 | 17 |
| Other | 9 | 13 | 23 |
| Philosophy | 13 | 15 | 23 |
| Physics | 8 | 6 | 17 |
| Psychology | 24 | 21 | 27 |

V1.5 beats nano in 9 categories, ties in none, and loses in 5. Its weakest relative slices
are business, math, physics, psychology, and biology. Because each category has only 30
questions, slice differences are diagnostic rather than conclusive.

## Artifacts

- Dataset: `evals/datasets/mmlu_pro_stratified_420.jsonl`
- Machine-readable summary: `evals/mmlu_pro_stratified_420_three_arm_metrics.json`
- Gitignored paired cache: `evals/results/mmlu_pro_stratified_420_v15_vs_gpt54.jsonl`
- Gitignored nano cache: `evals/results/mmlu_pro_stratified_420_nano.jsonl`

Recreate the exact sample from the pinned upstream revision:

```powershell
python src/evals/prepare_standard_benchmark.py mmlu-pro `
  --revision b189ec765aa7ed75c8acfea42df31fdae71f97be `
  --per-category 30 --seed mmlu-pro-stratified-420-v1 `
  --output evals/datasets/mmlu_pro_stratified_420.jsonl
```
