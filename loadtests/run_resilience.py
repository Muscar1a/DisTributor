"""Run isolated provider-error and circuit-breaker probes after capacity testing."""

from __future__ import annotations

import json
import time

import httpx
from run_judge_benchmark import HOST, RESULTS, chat_payload, temporary_key


def probe(client: httpx.Client, name: str, headers: dict[str, str], payload: dict, expected: set[int]) -> dict:
    started = time.perf_counter()
    response = client.post(f"{HOST}/v1/chat/completions", headers=headers, json=payload)
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    error = body.get("error", {}) if isinstance(body, dict) else {}
    details = error.get("details", {}) if isinstance(error, dict) else {}
    return {
        "name": name,
        "status": response.status_code,
        "expected_statuses": sorted(expected),
        "error_code": error.get("code"),
        "chain_attempted_count": len(details.get("chain_attempted", [])) if isinstance(details, dict) else 0,
        "retry_after": response.headers.get("Retry-After"),
        "latency_ms": elapsed,
        "passed": response.status_code in expected,
    }


def main() -> int:
    observations: list[dict] = []
    with temporary_key(f"judge-resilience-{int(time.time())}", 100) as key:
        headers = {"Authorization": f"Bearer {key['key']}"}
        with httpx.Client(timeout=45) as client:
            observations.append(
                probe(
                    client, "forced provider 429", headers, chat_payload("#force_429", force_model="mock-cheap"), {502}
                )
            )
            observations.append(
                probe(
                    client, "forced provider 500", headers, chat_payload("#force_500", force_model="mock-cheap"), {502}
                )
            )
            for index in range(1, 6):
                observations.append(
                    probe(
                        client,
                        f"circuit trigger {index}",
                        headers,
                        chat_payload("#force_500", force_model="mock-cheap"),
                        {400, 502},
                    )
                )
            observations.append(
                probe(
                    client,
                    "unaffected model while cheap circuit open",
                    headers,
                    chat_payload("Hi", force_model="mock-mid"),
                    {200},
                )
            )
            observations.append(
                probe(
                    client,
                    "cheap model immediately after circuit opens",
                    headers,
                    chat_payload("Hi", force_model="mock-cheap"),
                    {400, 502},
                )
            )

    # The configured recovery timeout is 300 seconds. Wait in bounded intervals so
    # operators can observe the staging instance while the circuit recovers.
    for _ in range(30):
        time.sleep(10)
    with temporary_key(f"judge-resilience-recovery-{int(time.time())}", 100) as key:
        headers = {"Authorization": f"Bearer {key['key']}"}
        with httpx.Client(timeout=45) as client:
            observations.append(
                probe(
                    client,
                    "cheap model after recovery timeout",
                    headers,
                    chat_payload("Hi", force_model="mock-cheap"),
                    {200},
                )
            )

    result = {
        "configured_circuit_recovery_seconds": 300,
        "observations": observations,
        "passed": all(item["passed"] for item in observations),
    }
    output = RESULTS / "resilience.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(output)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
