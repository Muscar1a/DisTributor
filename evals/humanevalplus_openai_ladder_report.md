# HumanEval+ OpenAI Ladder Smoke Report

## Decision

This coding benchmark is a better fit for classifier v1.5 than MMLU-Pro alone because the
router is intended to choose model capacity for developer tasks. HumanEval+ measures whether
generated Python actually passes executable tests, including the stricter EvalPlus tests,
rather than whether a model can select a multiple-choice answer.

The five-item result is a successful pipeline smoke test, not a production-quality claim.
The sample is the first five ordered HumanEval+ tasks, all routed to T2, and is too small and
too easy to distinguish the routed model from the baseline.

## Run metadata

- Date: 2026-08-23
- Dataset: `evals/datasets/humanevalplus_sample_5.jsonl`
- Benchmark: HumanEval+ v0.1.10 via EvalPlus 0.3.1
- Dataset hash: `fe585eb4df8c88d844eeb463ea4d0302`
- Records: 5 paired prompts
- Classifier: `heuristic-v1.5`
- Routed model observed: `gpt-5.4-mini` (5/5)
- Strong-only baseline: `gpt-5.4`
- Generation limit: 6 requests/minute, 1,024 output tokens/request
- Execution: pinned EvalPlus Docker image, no network, 2 CPUs, 4 GiB memory

## Why this dataset and baseline

HumanEval+ is small enough to run repeatedly and adds substantially more tests than the
original HumanEval suite. Its objective pass/fail signal is much closer to model answer
quality for code than classifier-label agreement or MMLU accuracy. It still covers isolated
Python functions rather than repository-level engineering, so a later benchmark should add
SWE-bench-style tasks or a private repository-task set.

GPT-5.4 is the strong-only baseline because it is the configured T3 OpenAI model. The paired
design sends the identical prompt once through SmartRoute and once directly to GPT-5.4; this
isolates the quality/cost effect of routing better than comparing unrelated published scores.

## Quality definition

- Primary metric: HumanEval+ pass@1, requiring both base and Plus tests to pass.
- Quality retention (QR): routed pass@1 divided by GPT-5.4 pass@1.
- Cost: token usage priced from `src/gateway/app/config/pricing.yaml`.
- Suggested promotion gate for the full 164-task suite: routed pass@1 no more than 5 percentage
  points below GPT-5.4 and QR at least 95%. Report paired confidence intervals before a
  production decision.

## Smoke result

| Metric | SmartRoute | GPT-5.4 baseline |
|---|---:|---:|
| Valid submissions | 5/5 | 5/5 |
| HumanEval base pass@1 | 100% | 100% |
| HumanEval+ pass@1 | 100% | 100% |
| Prompt tokens | 656 | 656 |
| Completion tokens | 588 | 642 |
| Modeled cost | $0.003138 | $0.011270 |

- Quality retention: **100%**
- Modeled cost savings: **72.16%**
- Interpretation: good enough to validate the benchmark path; **not enough evidence to ship
  the classifier for coding quality**.

## Reproduction

Build the pinned sandbox:

```powershell
docker build --pull=false -f src/evals/Dockerfile.evalplus -t smartroute-evalplus:0.3.1 .
```

Generate paired outputs through the running local gateway:

```powershell
python -u src/evals/run_answer_quality_eval.py `
  --dataset evals/datasets/humanevalplus_sample_5.jsonl `
  --output evals/results/humanevalplus_openai_ladder_paired_5.jsonl `
  --limit 5 --mode paired --base-url http://127.0.0.1:8000 `
  --pricing src/gateway/app/config/pricing.yaml --strong-model gpt-5.4 `
  --requests-per-minute 6 --max-tokens 1024 --timeout 180 --execute
```

Execute untrusted model output only in the network-disabled container:

```powershell
docker run --rm --network none --cpus 2 --memory 4g `
  -v "${PWD}:/work" smartroute-evalplus:0.3.1 `
  python -m src.evals.grade_evalplus_subset `
  --outcomes evals/results/humanevalplus_openai_ladder_paired_5.jsonl `
  --output evals/humanevalplus_openai_ladder_metrics.json `
  --dataset-hash fe585eb4df8c88d844eeb463ea4d0302
```

Raw generations remain gitignored because they can contain model-produced content.
