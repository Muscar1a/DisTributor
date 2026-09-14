# MATH-500 Full Three-Arm Benchmark

## Decision

Classifier v1.5 does not improve quality per cost over the weakest fixed-model baseline on
MATH-500. It scores 318/500 (63.6%), compared with 323/500 (64.6%) for all GPT-5.4-nano,
while costing 41.13% more. The paired difference is not statistically significant (exact
two-sided McNemar p = 0.6147).

Against all GPT-5.4, v1.5 saves 88.01% of modeled provider cost but retains only 85.48% of
its accuracy, below the project's 95% quality-retention target. This corroborates the
MMLU-Pro result: **v1.5 is not a quality-per-dollar winner under the current routing policy.**

## Run metadata

- Date: 2026-08-25
- Benchmark: full MATH-500 test set (500 questions)
- Upstream revision: `6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be`
- Generated dataset SHA-256: `4932706E8C10BB7F32087D3BEBB19A895D056C83BB04CCB25F038D04626828C2`
- Arms: all GPT-5.4-nano; classifier `heuristic-v1.5`; all GPT-5.4
- Routed distribution: 405 nano, 95 mini, 0 GPT-5.4
- Generation: temperature 0, 1,024 output-token limit
- Validity: 500/500 successful responses in every arm; zero permanent provider errors
- Scoring: symbolic answer equivalence with `math-verify==0.9.0`
- Cost: recorded token usage priced by `src/gateway/app/config/pricing.yaml`

## Overall results

| Metric | All nano | Classifier v1.5 | All GPT-5.4 |
|---|---:|---:|---:|
| Correct | 323/500 | 318/500 | 372/500 |
| Accuracy | 64.60% | 63.60% | 74.40% |
| Wilson 95% interval | 60.31-68.67% | 59.29-67.70% | 70.40-78.03% |
| Prompt tokens | 41,347 | 41,347 | 41,347 |
| Completion tokens | 135,019 | 127,317 | 132,057 |
| Modeled cost | $0.177043 | $0.249857 | $2.084223 |
| Cost per correct answer | $0.000548 | $0.000786 | $0.005603 |
| Correct answers per dollar | 1,824 | 1,273 | 178 |

## Pairwise interpretation

### v1.5 versus all-nano

- Absolute accuracy difference: **-1.00 point**; relative difference: **-1.55%**.
- Cost premium: **+41.13%** ($0.072814 more for five fewer correct answers).
- Paired outcomes: both correct 289; v1.5-only correct 29; nano-only correct 34;
  neither correct 148.
- Exact two-sided paired McNemar/sign test: **p = 0.6147**.

### v1.5 versus all GPT-5.4

- Quality retention: **85.48%**.
- Absolute accuracy gap: **-10.80 points**.
- Modeled cost savings: **88.01%**.
- Paired outcomes: both correct 311; v1.5-only correct 7; GPT-5.4-only correct 61;
  neither correct 121.
- Exact two-sided paired McNemar/sign test: **p = 7.39e-12**.

## Results by difficulty

Each score is correct answers out of the number of questions at that level.

| Level | N | All nano | v1.5 | All GPT-5.4 |
|---:|---:|---:|---:|---:|
| 1 | 43 | 30 | 31 | 34 |
| 2 | 90 | 66 | 65 | 68 |
| 3 | 105 | 79 | 75 | 85 |
| 4 | 128 | 80 | 78 | 94 |
| 5 | 134 | 68 | 69 | 91 |

## Results by subject

| Subject | N | All nano | v1.5 | All GPT-5.4 |
|---|---:|---:|---:|---:|
| Algebra | 124 | 98 | 92 | 102 |
| Counting & Probability | 38 | 31 | 28 | 34 |
| Geometry | 41 | 21 | 22 | 29 |
| Intermediate Algebra | 97 | 42 | 45 | 57 |
| Number Theory | 62 | 52 | 50 | 61 |
| Prealgebra | 82 | 62 | 62 | 64 |
| Precalculus | 56 | 17 | 19 | 25 |

The level and subject slices are diagnostic, not independent confirmatory tests. V1.5 is
close to nano across every level; its small gains in geometry, intermediate algebra, and
precalculus do not offset losses elsewhere.

## Grading integrity

The previous normalized-string scorer misclassified mathematically equivalent answers such
as `x=2` versus `2`, unreduced fractions, and degree notation. This run is regraded from the
cached raw responses using the pinned Math-Verify symbolic parser. The regrade runs in the
provided network-disabled Docker image with per-expression timeouts. Raw response caches are
gitignored; their SHA-256 hashes are recorded in the machine-readable metrics file.

## Artifacts and reproduction

- Machine-readable summary: `evals/math500_full_500_three_arm_metrics.json`
- Grading image: `src/evals/Dockerfile.mathverify`
- Offline three-arm grader: `src/evals/grade_math_three_arm.py`
- Gitignored paired cache: `evals/results/math500_full_500_v15_vs_gpt54.jsonl`
- Gitignored nano cache: `evals/results/math500_full_500_nano.jsonl`

Recreate the normalized dataset from the pinned upstream revision:

```powershell
python src/evals/prepare_standard_benchmark.py math500 `
  --revision 6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be `
  --output evals/datasets/math500_full_500.jsonl
```

Regrade cached responses without network access:

```powershell
docker build -f src/evals/Dockerfile.mathverify -t smartroute-mathverify:0.9.0 .
docker run --rm --network none --cpus 4 --memory 6g `
  -v "${PWD}:/work" -w /work smartroute-mathverify:0.9.0 `
  python -m src.evals.grade_math_three_arm `
  --dataset evals/datasets/math500_full_500.jsonl `
  --paired evals/results/math500_full_500_v15_vs_gpt54.jsonl `
  --nano evals/results/math500_full_500_nano.jsonl `
  --output evals/math500_full_500_three_arm_grade.json
```
