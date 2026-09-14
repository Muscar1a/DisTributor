# Developer interview guide: issue 52 / H3

## Purpose and privacy boundary

This interview explores H3: developers' acceptable router latency overhead and the routing-log fields they need to debug and trust routing decisions. Record only the anonymized bands and preferences in `responses.csv`; do not record names, email addresses, company names, account identifiers, raw transcripts, or copied production data.

Ask for consent before recording any answer:

> May I record your anonymized, banded answers in an aggregate report? We will not store your name, email, company, raw transcript, or production content. You can decline or skip any question.

Record `consent_to_aggregate=yes` only after an explicit yes. A no or skipped answer is not used in aggregate findings.

## Screening and context

1. When answered, map `role_band` to exactly one value: `engineer`, `engineering_leader`, `product`, `data_ml`, or `other`.
2. When answered, map `experience_band` to exactly one value: `0-2`, `3-5`, `6-10`, or `10+`.
3. When answered, map LLM integration frequency to exactly one tag: `never`, `evaluating`, `monthly`, `weekly`, or `daily`.

## Latency and routing trade-offs

1. Map current end-to-end latency to one band: `<100`, `100-300`, `301-500`, `501-1000`, or `>1000` ms.
2. What router overhead is acceptable? Choose one: `<100`, `100-300`, `301-500`, `501-1000`, or `>1000` ms.
3. Ask which user flows or cases are especially latency-sensitive, then map zero or more semicolon-separated `latency_sensitive_cases` tags: `interactive_chat`, `autocomplete`, `voice_realtime`, `agent_loop`, `batch`, `other`.
4. Map the cost/quality trade-off to exactly one `cost_quality_preference`: `cost_first`, `balanced`, `quality_first`, or `context_dependent`.

## Routing-log requirements

Which routing-log fields help you debug or govern decisions? Offer: request ID, timestamp, tier, score, signals, reason, policy, model, provider, fallback chain, latency, tokens, cost, error, and content redaction. Store only these canonical labels, separated by semicolons, in `desired_log_fields`: `request_id`, `timestamp`, `tier`, `score`, `signals`, `reason`, `policy`, `model`, `provider`, `fallback_chain`, `latency`, `tokens`, `cost`, `error`, `content_redaction`.

Map privacy/debugging concerns to zero or more semicolon-separated `privacy_debugging_concerns` tags: `prompt_content`, `response_content`, `personal_data`, `secrets`, `retention`, `access_control`, `redaction`, `traceability`, `other`.

Ask open questions verbally, but store only the documented tags and bands. A blank non-ID field means the participant skipped that question; every nonblank value must use its documented vocabulary. Never store a quote, transcript, name, company, or free-text summary. Store `interview_date` as ISO `YYYY-MM-DD`, and record consent as `yes`, `no`, or `skipped` when answered.

## After the interview

1. Assign an anonymous ID in the form `DEV-NN`.
2. Enter only the permitted bands and summarized preferences in `responses.csv`.
3. Recheck explicit aggregate consent.
4. Recheck that the CSV contains no PII, company details, raw transcript, or production content.
