# SmartRoute Gateway Evaluation Report

## Benchmark summary

Paired benchmark results comparing SmartRoute vs all-premium baseline.
Full report: [`evals/mmlu_pro_openai_ladder_report.md`](../../evals/mmlu_pro_openai_ladder_report.md)

| Metric | SmartRoute | All-premium |
|---|---|---|
| Cost per run | $0.000315 | $0.002380 |
| Cost savings | **86.74%** | baseline |
| Quality Retention (paired) | 25.00% | 100% |
| Critical-fail rate | 60.00% | — |
| Classifier latency p50 | 0.50 ms | — |

> Dataset: `evals/datasets/mmlu_pro_sample_20.jsonl` (20 hard prompts, MMLU Pro domain).
> QR is low because the heuristic classifier over-routes hard prompts to T1; this is the known ceiling documented in `docs/implementation/routing_benchmark_eval_design.md`.

<!-- issue-52:start -->
## Issue 52: Gold-dataset and interview evidence

### Dataset composition and H1
- Prompts: 200; language: vi 100, en 100; source: real production requests.
- Difficulty: easy 46, medium 65, hard 89.
- Categories: analysis_planning 23, chitchat 16, coding 27, explanation 20, factual_qa 34, math_reasoning 17, other 14, summarization 5, translation 1, writing 43.
- Easy + Medium: 55.5% (111/200); H1 target is 60–70% inclusive.
- H1: MEASURED — below target (55.5% < 60%). Real traffic skews harder than the H1 hypothesis predicted. The SmartRoute cost-saving claim remains valid but operates on a harder distribution than assumed.
- Dataset: [`src/evals/datasets/mixed_200.jsonl`](datasets/mixed_200.jsonl), SHA `18bfbaa`.

### Developer interviews and H3
- H3: CONFIRMED (5/5 valid consented interviews)
- Participants: 2 backend engineers, 1 data scientist, 2 AI/engineering-adjacent roles.
- All 5 confirmed pain point: LLM vendor lock-in causes significant cost overrun in production workflows.
- All 5 expressed positive interest in the SmartRoute tiered-routing approach as a practical mitigation.
- Consent: all participants agreed their responses may be used as evaluation evidence.
- Raw responses: [`src/evals/interviews/responses.csv`](interviews/responses.csv)
<!-- issue-52:end -->
