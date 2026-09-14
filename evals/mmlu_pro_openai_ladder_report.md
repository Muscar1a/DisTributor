# Routing Benchmark Report

## Run metadata

- Dataset: `evals\datasets\mmlu_pro_sample_20.jsonl`
- Records: 20
- Classifier: `heuristic-v1.5`
- Strong-only baseline: `gpt-5.4`

## Classifier routing

- Tier accuracy: **0.00%**
- Macro F1: **0.00%**
- Hard prompts routed to T1: **85.00%**
- Classifier latency: p50 **0.50 ms**, p95 **1.05 ms**

| Expected \ Predicted | T1 | T2 | T3 |
|---|---:|---:|---:|
| T1 | 0 | 0 | 0 |
| T2 | 0 | 0 | 0 |
| T3 | 17 | 3 | 0 |

### Category slices

| Category | N | Tier accuracy | T3→T1 count |
|---|---:|---:|---:|
| business | 20 | 0.00% | 17 |

### Language slices

| Language | N | Tier accuracy | T3→T1 count |
|---|---:|---:|---:|
| en | 20 | 0.00% | 17 |

## Response quality and cost

- Paired samples: 5
- Valid paired samples: 5; failed/incomplete: 0
- Objective QR: **25.00%**
- Pairwise QR: **not measured**
- Combined Quality Retention: **25.00%**
- Hard-task retention: **25.00%**
- Critical-fail rate: **60.00%**
- SmartRoute cost: **$0.000315**
- Strong-only cost: **$0.002380**
- Cost savings: **86.74%**

## Interpretation guardrails

- Tier accuracy/F1 evaluates the classifier against human tier labels; it is not response quality.
- Quality Retention is only reported from paired recorded outputs on identical prompts.
- The strong-only model, pricing snapshot, dataset revision, and judge decisions are run inputs.
