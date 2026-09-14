# MMLU-Pro OpenAI T3 smoke report

## Run configuration

- Benchmark: MMLU-Pro, test split
- Dataset revision: `b189ec765aa7ed75c8acfea42df31fdae71f97be`
- Sample: first 5 records from the pinned 20-record normalization artifact
- Model: OpenAI `gpt-5.4`
- Mode: strong-only T3 baseline
- Temperature: 0
- Maximum completion tokens: 1024
- Client throttle: 6 requests per minute
- Grader: deterministic option-letter exact match

## Result

| Metric | Result |
|---|---:|
| Valid responses | 5 / 5 |
| Correct | 4 / 5 |
| Accuracy | **80.00%** |
| Prompt tokens | 832 |
| Completion tokens | 20 |
| Calculated cost | **$0.002380** |

Per-record grading:

| Record | Reference | Response | Correct | Latency |
|---|---:|---:|---:|---:|
| `mmlu-pro-70` | I | I | yes | 4105 ms |
| `mmlu-pro-71` | F | F | yes | 2151 ms |
| `mmlu-pro-72` | J | J | yes | 1860 ms |
| `mmlu-pro-73` | C | H | no | 2100 ms |
| `mmlu-pro-74` | G | G | yes | 2132 ms |

## Interpretation

This is an API/provider smoke score, not a publishable estimate of MMLU-Pro accuracy: `N=5` has very high sampling uncertainty and the slice contains only the first records (all currently categorized as business). It proves that the pinned dataset → gateway → OpenAI T3 → deterministic grader → token/cost pipeline works.

It does not yet measure SmartRoute Quality Retention. Classifier v1.5 routes 17/20 records in this sample to T1 and 3/20 to T2; the routed provider chain returned 502 during the probe. A paired QR claim requires valid SmartRoute outputs on the same questions.
