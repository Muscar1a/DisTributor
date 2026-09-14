# Routing Benchmark Report

## Run metadata

- Dataset: `evals\datasets\humanevalplus_full_164.jsonl`
- Records: 164
- Classifier: `heuristic-v1.5`
- Strong-only baseline: `gpt-5.4`

## Classifier routing

- Tier accuracy: **93.90%**
- Macro F1: **32.29%**
- Hard prompts routed to T1: **0.00%**
- Classifier latency: p50 **0.00 ms**, p95 **0.00 ms**

| Expected \ Predicted | T1 | T2 | T3 |
|---|---:|---:|---:|
| T1 | 0 | 0 | 0 |
| T2 | 10 | 154 | 0 |
| T3 | 0 | 0 | 0 |

### Category slices

| Category | N | Tier accuracy | T3→T1 count |
|---|---:|---:|---:|
| coding | 164 | 93.90% | 0 |

### Language slices

| Language | N | Tier accuracy | T3→T1 count |
|---|---:|---:|---:|
| en | 164 | 93.90% | 0 |

## Response quality and cost

**Not measured in this run.** No paired model-outcome file was supplied. Routing labels measure classifier agreement, not answer quality; this report does not conflate them.

Supply `--outcomes <jsonl>` after running each prompt through SmartRoute and the strong-only baseline.

## Interpretation guardrails

- Tier accuracy/F1 evaluates the classifier against human tier labels; it is not response quality.
- Quality Retention is only reported from paired recorded outputs on identical prompts.
- The strong-only model, pricing snapshot, dataset revision, and judge decisions are run inputs.
