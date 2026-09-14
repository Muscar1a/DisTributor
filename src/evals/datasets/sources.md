# Dataset sources and provenance

## Selected source

- Dataset: [allenai/WildChat-1M](https://huggingface.co/datasets/allenai/WildChat-1M)
- Revision: `7d6490e462285cf85d91eabea0f9a954fbddcd1f`
- License: [ODC Attribution 1.0](https://opendatacommons.org/licenses/by/1-0/)
- Accessed: `2026-08-13`

Contains information from WildChat-1M, made available under the ODC Attribution License.

## Dataset construction constraints

- Quota: 100 Vietnamese (`vi`) records and 100 English (`en`) records.
- Each record uses the first user turn only.
- Selection applies non-toxic, text-only, deduplication, and PII filters.
- Prompts over 16,000 estimated tokens are excluded.
- Every record must pass the human-review gate before it is marked human verified.

## Labeling limitation

The H1 difficulty-to-tier mapping (easy/T1, medium/T2, hard/T3) is an inference for evaluation routing, not a claim that the source dataset supplies those labels.

## multiturn_30.jsonl (doc 08 §11)

- Built by `src/evals/build_multiturn.py`; each line is one conversation with per-turn
  `expected_intent` / `expected_tier` labels.
- `source=template` (18 conversations): hand-labeled gold trajectories covering the 10 adversarial
  cases of `docs/design/08_adaptive_routing.md` §10 (`annotation_status=template_gold`).
- `source=wildchat` (optional, via `--wildchat N`): real multi-turn coding conversations from the
  same WildChat-1M revision above — ≥3 user turns, coding signal, non-toxic/PII/media filters
  reused from `build_mixed_200.py`; labels start as `pending_human_review`.

## mcq_false_positives.jsonl (Issue #211)

- Hand-authored, 11 records: 9 negatives across the four risk categories #211 names
  (`code`, `tai_lieu`, `danh_sach`, `hoi_thoai` — 2-3 each) plus 2 `control` true positives
  (real exam-style questions).
- Every prompt in this file was written to actually trigger classifier v1.5's structural MCQ
  regex (`_MCQ_RE` — sequential `A) ... B) ... C) ... D) ...` markers, or the literal phrase
  "refers to the following information") while representing something that is not an exam
  question: a code review comment, a design/architecture comparison, a scheduling poll, or a
  summarization request that happens to reuse MMLU-Pro's stock passage-intro phrase.
- Verified against `_MCQ_RE` directly (issue #210, `fix/issue-194-reasoning-genre`) before this
  file was committed: **all 9 negatives false-positive** — the regex currently classifies every
  one of them as an exam question, not just the code-block case. Only the 2 controls match
  correctly. `src/evals/tests/test_mcq_false_positives.py` turns this into a live regression
  check once #210's classifier module is importable on the checkout under test (it skips, rather
  than fails, when #210 is not merged yet).
- Schema: `id`, `category`, `language`, `expected_genre_mcq` (bool), `note`, `prompt`.

## Excluded sources

The dataset does not combine prompts from LMSYS/Kaggle Chatbot Arena, Dolly 15K, Natural Questions, UIT-ViQuAD 2.0, GSM8K, or MBPP.
