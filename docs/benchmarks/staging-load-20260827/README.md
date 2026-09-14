# Staging load benchmark — 2026-08-27

The comprehensive rerun is documented in [`judge-report.md`](judge-report.md). The earlier interrupted acceptance attempt is retained below only as historical evidence.

Target: `https://p-156-staging.onrender.com`

Deployment commit: `5d9a84eccf15a58a5139fc2ce03478aca4e2e370`

Environment: Render free instance (512 MB RAM, 0.1 CPU), one application instance, mock provider enabled.

Workload: non-streaming `POST /v1/chat/completions`, 0.5 task starts/second/user, and the PRD's 40/35/25 easy-medium-hard prompt mix.

Pass criteria: HTTP error rate below 1%, router p95 below 300 ms, and completion of the planned stage duration.

| Stage | Duration reached | HTTP requests | Errors | HTTP p95 | HTTP p99 | Router p95 | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| Warm-up, 1 user | 5 min | 149 | 0 (0.00%) | 1,200 ms | 1,900 ms | 0 ms | PASS |
| Baseline, 1 user | 15 min | 449 | 0 (0.00%) | 1,200 ms | 1,500 ms | 0 ms | PASS |
| Required, 3 users | about 10 min of 15 min | 686 | 36 (5.25%) | unavailable after interruption | unavailable after interruption | below 300 ms before incident | INCONCLUSIVE / stopped |
| PRD maximum, 5 users | not started | — | — | — | — | — | NOT TESTED |

## Conclusion

The deployment demonstrated stable operation at one concurrent user and approximately 0.5 HTTP RPS for 15 minutes. The 3-user stage was stopped when a burst of non-200 responses exceeded the safety threshold.

Render access logs identify `429 Too Many Requests` responses during the incident, alongside earlier `502 Bad Gateway` responses. The temporary test key was configured for 300 requests/minute, while the planned 3-user workload was approximately 90 requests/minute. Therefore, the run does not prove that CPU or memory capacity was exhausted; it exposes a rate-limiter or test-state issue that must be diagnosed before capacity is measured again.

Per the PRD, gateway-generated 429 responses are excluded from the product success-rate denominator. They still invalidate this load-capacity run because the intended traffic was below the configured key limit.

After the stop, an authenticated smoke request completed successfully through the mock provider in 1,256 ms. This suggests the incident was transient rather than a persistent deployment/configuration failure.

## Evidence caveat

Locust was interrupted immediately after the failure burst. Its periodic 3-user CSV checkpoint contains 652 HTTP requests and only the first two failures; the final console summary recorded 686 HTTP requests, 36 failures, and 650 successful router measurements. The final console totals are authoritative for the interrupted stage.

Compact Locust exports are stored in [`raw/`](raw/). Large HTML reports and per-second history files are intentionally excluded.

## Recommended follow-up

1. Record response bodies, `Retry-After`, API-key ID, and configured limit on the first 429.
2. Run a targeted 3-user test for 5–10 minutes with Render CPU/RAM metrics visible.
3. Only after that passes, rerun the complete 1/3/5-user acceptance profile.
