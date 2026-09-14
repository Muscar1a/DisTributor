# Classifier v2 HumanEval+ Pilot

## Decision

PR #167 contains a working LLM classifier v2, but it is not ready for promotion or a full
benchmark yet. Its v2-specific test suite passes, while repository CI fails on two Ruff
errors and the PR includes broad changes unrelated to classifier v2.

The five-task HumanEval+ smoke test passed: v2-routed answers and the GPT-5.4 baseline both
scored 5/5. This confirms the live integration and grading path, not classifier superiority;
the sample is too small and all five tasks were easy early-suite items.

## Implementation validation

- Source: PR #167, commit `51f5afa30067914c72d9a7d8614fad4b4f6c3d37`.
- Classifier model: GPT-5-nano, prompt revision r1, 2.5-second router timeout.
- Local focused tests: 19/19 passed.
- Live requests: all recorded `classifier_version=llm-v2`; no v1.5 fallback occurred.
- CI blocker: unused imports in `adapters/base.py` and `api/chat_completions.py`.
- Scope concern: 32 changed files, including unrelated dashboard/config edits and deletion of
  the Ollama adapter.

## Quality result

| Metric | v2 SmartRoute | GPT-5.4 baseline |
|---|---:|---:|
| Valid submissions | 5/5 | 5/5 |
| HumanEval+ pass@1 | 5/5 (100%) | 5/5 (100%) |
| Quality retention | 100% | — |

All five v2 requests classified the task as L3 and routed to GPT-5.4-mini. Observed classifier
latency was 1,322–2,270 ms. There were no provider errors.

Quality means executable correctness: a response passes only when it passes both the original
HumanEval tests and the stricter HumanEval+ tests. Grading used the pinned EvalPlus 0.3.1 image,
dataset hash `fe585eb4df8c88d844eeb463ea4d0302`, with networking disabled.

## Next gate

Before paying for the full 164-task run:

1. Fix PR #167 CI and separate or justify unrelated changes.
2. Run v2 first on the 11 known v1.5 regressions from the full baseline report. V2 must recover
   at least four routed passes to make the full-run promotion target plausible.
3. If that targeted test is promising, run all 164 tasks. Promotion still requires at least
   146/164 routed passes, quality retention at least 95%, an absolute gap no greater than five
   percentage points, and at least 60% modeled cost savings.

Machine-readable pilot metrics are in `evals/humanevalplus_v2_pilot_metrics.json`. Raw provider
responses remain outside the committed report artifacts.
