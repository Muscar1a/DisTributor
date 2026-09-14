# SmartRoute staging judge benchmark

Date: 2026-08-27 (ICT)  
Target: `https://p-156-staging.onrender.com`  
Deployment: `5d9a84eccf15a58a5139fc2ce03478aca4e2e370`  
Platform: Render free instance, 512 MB RAM / 0.1 CPU, one instance, `USE_MOCK_PROVIDERS=true`

## Executive verdict

The gateway completed all planned 1/3/5-user capacity stages with **0 HTTP failures**, but it is not ready for a production-capacity claim. Throughput flattened at approximately **1.1 RPS** and p95 end-to-end latency increased from **1.4 s at one user** to **5.1 s at five users**. Router decision latency remained below the 300 ms SLO; the bottleneck is downstream/request processing or the constrained instance, not classifier timing.

The benchmark also exposed three API-contract issues and one routing-quality issue. These should be fixed before the result is presented as a full acceptance pass.

## Capacity results

Each stage used a fresh API key (300 RPM), short prompts, and forced T1/T2/T3 traffic in a 40/35/25 mix so the 50,000-token daily quota could not contaminate concurrency measurements.

| Stage | HTTP requests | Errors | RPS | HTTP avg | HTTP p50 | HTTP p95 | HTTP p99 | Router avg | Router p95 | Router p99 | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 user / 5 min | 149 | 0 (0.00%) | 0.501 | 1,179 ms | 1,200 ms | 1,400 ms | 1,500 ms | 9.9 ms | 0 ms | 300 ms | PASS |
| 3 users / 10 min | 664 | 0 (0.00%) | 1.108 | 2,701 ms | 2,700 ms | 3,000 ms | 3,100 ms | 4.4 ms | 0 ms | 290 ms | PASS |
| 5 users / 15 min | 954 | 0 (0.00%) | 1.063 | 4,689 ms | 4,700 ms | 5,100 ms | 5,300 ms | 5.4 ms | 0 ms | 290 ms | PASS with saturation signal |

Observed throughput does not scale with users: 3 users reached 1.108 RPS and 5 users reached only 1.063 RPS. This is the key capacity finding for the 0.1-CPU instance. Router p95 is rounded to zero because most decisions complete below Locust's millisecond resolution; the worst observed router sample was 646 ms at 5 users, so the p95 SLO still passed but tail outliers should be investigated.

Route distribution was preserved by the workload: 1-user 49/56/45, 3-user 247/234/183, and 5-user 377/340/237 (easy/medium/hard). Every successful response had the expected mock model and provider.

## Contract and functional probes

15 of 18 probes passed. Latencies below are client-observed and include Render/network time.

| Probe | Expected | Observed | Latency | Verdict |
|---|---|---|---:|---|
| `/healthz` | 200 | 200 | 437 ms | PASS |
| `/readyz` | 200 | 200 | 332 ms | PASS |
| Missing auth | 401 | **200** | 1,116 ms | FAIL — staging is in development/open auth mode |
| Invalid auth | 401 / `invalid_api_key` | 401 / `invalid_api_key` | 738 ms | PASS |
| Unsupported `tools` | 400 / `unsupported_parameter` | same | 369 ms | PASS |
| 51 messages | 400 / `too_many_messages` | **422 / `validation_error`** | 380 ms | FAIL |
| Missing messages | 422 / `validation_error` | same | 366 ms | PASS |
| Empty content | 422 / `validation_error` | same | 367 ms | PASS |
| Context too long | 400 / `context_too_long` | same | 409 ms | PASS |
| Body over 1 MB | 413 / `request_too_large` | same | 239 ms | PASS |
| Unknown forced model | 400 / `unknown_model` | 400 / code missing | 664 ms | FAIL — status is right, envelope code is absent |
| `/v1/models` | 200 | 200 | 382 ms | PASS, but advertises real-provider models while runtime uses mock models |
| Force T1/T2/T3 | 200 and matching mock model | all matched | 1,156–1,367 ms | PASS |
| Immediate usage lookup | 200 | 200 | 584 ms | PASS |
| Streaming SSE | 200 + `[DONE]` | 200 + `[DONE]` | 1,874 ms | PASS |

## Routing quality

The 30 labeled prompts produced:

| Expected \ Observed | T1 | T2 | T3 |
|---|---:|---:|---:|
| T1 | 10 | 0 | 0 |
| T2 | 10 | 0 | 0 |
| T3 | 10 | 0 | 0 |

Accuracy was **33.3% (10/30)**, with **10 hard prompts routed to T1**. This fails PRD AC-1.1 and is a serious quality risk. Scores were mostly 0–22 and the deployed `/v1/models` response still lists real-provider models even though the staging runtime is mock-backed. The result may reflect the deployed classifier version and should be confirmed against the intended classifier build before production use.

## Rate-limit and quota behavior

The exact RPM boundary passed:

- A key configured for 5 RPM accepted requests 1–5.
- Request 6 returned 429 with `rate_limit_exceeded` and `Retry-After: 60`.
- A second key was not affected.
- A revoked key returned 401.

The daily-token boundary also passed: an isolated key reached the configured 50,000-token daily budget and request 8 returned 429 `daily_token_budget_exceeded` with a reset-oriented `Retry-After`. This explains the previous run's 429 burst: it crossed the daily quota, not the 300-RPM key limit.

## Provider failure and circuit behavior

Forced mock-provider 429 and 500 cases returned the expected 502 provider error. Repeated forced failures opened the circuit, but because the endpoint escalates through the shared mock chain, all three mock models became unavailable; a request forced to `mock-mid` also returned 502. After the configured recovery interval, a fresh request to `mock-cheap` returned 200 in approximately 129 seconds of observed client time.

This demonstrates graceful error envelopes and circuit recovery, but also shows that a single forced failure can poison the whole mock provider chain. The circuit test was run last and its temporary key was revoked.

## What this proves—and does not prove

Proven:

- One-instance staging transport remained available through the 5-user scope.
- Router decision p95 stayed under the 300 ms target.
- Per-key RPM limiting, key isolation, revocation, daily quota, SSE, usage lookup, and provider-error responses are observable.

Not proven:

- Production capacity or horizontal scaling.
- Real-provider latency, fallback success, or provider quota behavior; staging was mock-backed.
- CPU/RAM saturation causality; Render resource metrics were not captured in this run.
- Classifier quality; the deployed 30-prompt sample failed the target and needs build/config confirmation.

## Required fixes before sign-off

1. Run staging with production-like auth enforcement (`APP_ENV=production` or `API_AUTH_REQUIRED=true`).
2. Return `400/too_many_messages` for the 51-message case.
3. Return `400/unknown_model` in the forced-model error envelope.
4. Align `/v1/models` with the active mock runtime, or make the runtime use the advertised models.
5. Diagnose why the classifier routes this labeled sample entirely to T1.
6. Capture Render CPU, memory, restart/instance events, and database metrics during another 5-user run.
