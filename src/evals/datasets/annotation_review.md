# Human annotation review guide

`mixed_200.jsonl` is a draft dataset. A reviewer must check every prompt before it can be treated as gold data.

## Review batches

Work through these four batches and record the reviewer identity in `annotator`:

1. `VI-001` — `wc-vi-001` through `wc-vi-050`
2. `VI-002` — `wc-vi-051` through `wc-vi-100`
3. `EN-001` — `wc-en-001` through `wc-en-050`
4. `EN-002` — `wc-en-051` through `wc-en-100`

## Rubric and permitted values

Check that the prompt is text-only, understandable in its stated language, and does not expose personal data, credentials, or a request that depends on unavailable attached media. Recheck the assigned category and difficulty.

- `category`: `chitchat`, `factual_qa`, `explanation`, `translation`, `summarization`, `information_extraction`, `writing`, `coding`, `math_reasoning`, `analysis_planning`, or `other`.
- `difficulty` and `expected_tier` must remain paired: `easy`/`T1`, `medium`/`T2`, `hard`/`T3`.
- Easy/T1: chitchat, short/direct facts, direct rewrite, translation, or extraction; no multi-step reasoning or specialist knowledge.
- Medium/T2: structured explanations, moderate writing or summarization, one-step analysis, basic code or math, or several output constraints.
- Hard/T3: multi-step reasoning, nontrivial debugging or design, complex math, specialist analysis, or long/many interdependent constraints.
- When uncertain, choose the higher tier to protect evaluation quality.
- `pii_review_status`: use `human_verified` only after the PII/media review; otherwise keep `pending_human_review`.
- `annotation_status`: use `human_verified` when the draft labels are correct. Use `human_revised` when a reviewer changes labels, and add a concise reason in `annotation_notes`.

Do not edit `id`, `prompt`, `language`, or any provenance field (`source_dataset`, `source_revision`, `source_record_id`, `source_url`, `license`). Do not put PII, credentials, or copied sensitive text into notes. A real reviewer replaces `codex-draft` in `annotator`; do not claim human review without completing both review statuses.

Validate after each batch and before publishing:

```powershell
python src/evals/validate_dataset.py
python src/evals/validate_dataset.py --require-gold
```

The first command verifies structure and reports pending-review warnings. The second command is intentionally expected to fail until humans have reviewed all 200 records, replaced the draft annotator, and marked both review gates complete.
