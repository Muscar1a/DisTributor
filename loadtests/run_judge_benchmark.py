"""Run contract, quota, routing, resilience, and Locust capacity benchmarks."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
HOST = os.getenv("SR_BENCHMARK_HOST", "https://p-156-staging.onrender.com").rstrip("/")
RESULTS = ROOT / "loadtests" / "results" / "judge"
PYTHON = Path(os.getenv("SR_BENCHMARK_PYTHON", sys.executable))
RESULTS.mkdir(parents=True, exist_ok=True)


def local_secret(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    env_path = ROOT / ".env"
    if not env_path.exists():
        env_path = ROOT.parents[1] / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
            if raw.strip().startswith(f"{name}="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(f"Missing {name}")


ADMIN_KEY = local_secret("STAGING_ADMIN_KEY")
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_KEY}


@contextmanager
def temporary_key(name: str, rpm: int):
    with httpx.Client(timeout=45) as client:
        response = client.post(
            f"{HOST}/admin/keys",
            headers=ADMIN_HEADERS,
            json={"name": name, "rate_limit_per_min": rpm},
        )
        response.raise_for_status()
        created = response.json()
    try:
        yield created
    finally:
        with httpx.Client(timeout=45) as client:
            response = client.delete(f"{HOST}/admin/keys/{created['id']}", headers=ADMIN_HEADERS)
            if response.status_code not in {200, 404}:
                response.raise_for_status()


def error_code(response: httpx.Response) -> str | None:
    try:
        return response.json().get("error", {}).get("code")
    except Exception:
        return None


def safe_probe(
    client: httpx.Client,
    name: str,
    method: str,
    path: str,
    expected_status: int,
    expected_code: str | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], httpx.Response]:
    started = time.perf_counter()
    response = client.request(method, f"{HOST}{path}", **kwargs)
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    actual_code = error_code(response)
    passed = response.status_code == expected_status and (expected_code is None or actual_code == expected_code)
    result = {
        "name": name,
        "method": method,
        "path": path,
        "expected_status": expected_status,
        "actual_status": response.status_code,
        "expected_error_code": expected_code,
        "actual_error_code": actual_code,
        "retry_after": response.headers.get("Retry-After"),
        "latency_ms": elapsed,
        "passed": passed,
    }
    return result, response


def chat_payload(prompt: str = "Hi", **smartroute: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "auto",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 1,
        "stream": False,
    }
    if smartroute:
        body["smartroute"] = smartroute
    return body


def run_contract_and_routing() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    with temporary_key(f"judge-contract-{int(time.time())}", 500) as key:
        auth = {"Authorization": f"Bearer {key['key']}"}
        with httpx.Client(timeout=45) as client:
            for spec in (
                ("health", "GET", "/healthz", 200, None, {}),
                ("readiness", "GET", "/readyz", 200, None, {}),
                ("missing auth", "POST", "/v1/chat/completions", 401, "invalid_api_key", {"json": chat_payload()}),
                (
                    "invalid auth",
                    "POST",
                    "/v1/chat/completions",
                    401,
                    "invalid_api_key",
                    {"headers": {"Authorization": "Bearer invalid"}, "json": chat_payload()},
                ),
                (
                    "unsupported tools",
                    "POST",
                    "/v1/chat/completions",
                    400,
                    "unsupported_parameter",
                    {"headers": auth, "json": {**chat_payload(), "tools": []}},
                ),
                (
                    "too many messages",
                    "POST",
                    "/v1/chat/completions",
                    400,
                    "too_many_messages",
                    {"headers": auth, "json": {**chat_payload(), "messages": [{"role": "user", "content": "x"}] * 51}},
                ),
                (
                    "missing messages",
                    "POST",
                    "/v1/chat/completions",
                    422,
                    "validation_error",
                    {"headers": auth, "json": {"model": "auto"}},
                ),
                (
                    "empty content",
                    "POST",
                    "/v1/chat/completions",
                    422,
                    "validation_error",
                    {"headers": auth, "json": {**chat_payload(), "messages": [{"role": "user", "content": ""}]}},
                ),
                (
                    "context too long",
                    "POST",
                    "/v1/chat/completions",
                    400,
                    "context_too_long",
                    {"headers": auth, "json": chat_payload("x" * 40_000)},
                ),
                (
                    "body too large",
                    "POST",
                    "/v1/chat/completions",
                    413,
                    "request_too_large",
                    {"headers": auth, "json": chat_payload("x" * 1_010_000)},
                ),
                (
                    "unknown forced model",
                    "POST",
                    "/v1/chat/completions",
                    400,
                    "unknown_model",
                    {"headers": auth, "json": chat_payload("Hi", force_model="does-not-exist")},
                ),
                ("models list", "GET", "/v1/models", 200, None, {"headers": auth}),
            ):
                result, _ = safe_probe(client, *spec[:5], **spec[5])
                results.append(result)

            model_ids: list[str] = []
            models_response = client.get(f"{HOST}/v1/models", headers=auth)
            if models_response.status_code == 200:
                model_ids = [item["id"] for item in models_response.json().get("data", [])]

            for tier, model in (("T1", "mock-cheap"), ("T2", "mock-mid"), ("T3", "mock-premium")):
                result, response = safe_probe(
                    client,
                    f"force tier {tier}",
                    "POST",
                    "/v1/chat/completions",
                    200,
                    headers=auth,
                    json=chat_payload("Hi", force_tier=tier),
                )
                if response.status_code == 200:
                    metadata = response.json().get("smartroute", {})
                    result["observed_tier"] = metadata.get("tier")
                    result["observed_model"] = metadata.get("model_used")
                    result["observed_provider"] = metadata.get("provider")
                    result["router_latency_ms"] = metadata.get("latency_router_ms")
                    result["passed"] = (
                        result["passed"] and metadata.get("tier") == tier and metadata.get("model_used") == model
                    )
                results.append(result)

            usage_result, completion = safe_probe(
                client,
                "completion for usage lookup",
                "POST",
                "/v1/chat/completions",
                200,
                headers=auth,
                json=chat_payload("Hi"),
            )
            results.append(usage_result)
            if completion.status_code == 200:
                request_id = completion.headers.get("X-SR-Request-Id")
                usage, _ = safe_probe(client, "usage lookup", "GET", f"/v1/usage/{request_id}", 200, headers=auth)
                results.append(usage)

            stream, stream_response = safe_probe(
                client,
                "streaming SSE",
                "POST",
                "/v1/chat/completions",
                200,
                headers=auth,
                json={**chat_payload("Hi"), "stream": True},
            )
            stream["content_type"] = stream_response.headers.get("content-type")
            stream["has_done_marker"] = "data: [DONE]" in stream_response.text
            stream["passed"] = stream["passed"] and stream["has_done_marker"]
            results.append(stream)

            labeled = {
                "T1": [
                    "Hi",
                    "Translate hello to Vietnamese",
                    "What is 2+2?",
                    "Define API",
                    "Summarize: cats are mammals",
                    "Say thank you",
                    "What is HTTP?",
                    "Name Vietnam's capital",
                    "Fix this typo: teh",
                    "Return JSON with ok=true",
                ],
                "T2": [
                    "Compare REST and GraphQL",
                    "Explain dependency injection with an example",
                    "Write a Python binary search",
                    "Summarize the tradeoffs of SQL indexes",
                    "Create five unit-test cases for a parser",
                    "Explain OAuth authorization code flow",
                    "Refactor a function for readability",
                    "Compare queues and pub-sub",
                    "Write a paginated API endpoint",
                    "Explain database normalization",
                ],
                "T3": [
                    "Design a distributed rate limiter with failure recovery",
                    "Debug a production-only deadlock in a worker pool",
                    "Threat-model a multi-tenant authentication system",
                    "Prove the time complexity of this graph algorithm",
                    "Design an exactly-once payment workflow",
                    "Optimize a database handling ten million writes per second",
                    "Analyze a race condition that randomly fails in CI",
                    "Design consensus under network partitions",
                    "Solve a dynamic programming problem with proof",
                    "Review microservice architecture for cascading failures",
                ],
            }
            confusion: Counter[str] = Counter()
            for expected, prompts in labeled.items():
                for prompt in prompts:
                    started = time.perf_counter()
                    response = client.post(f"{HOST}/v1/chat/completions", headers=auth, json=chat_payload(prompt))
                    latency = round((time.perf_counter() - started) * 1000, 2)
                    if response.status_code == 200:
                        meta = response.json()["smartroute"]
                        predicted = meta["tier"]
                        confusion[f"{expected}->{predicted}"] += 1
                        route_rows.append(
                            {
                                "expected": expected,
                                "predicted": predicted,
                                "score": meta["difficulty_score"],
                                "router_latency_ms": meta["latency_router_ms"],
                                "total_latency_ms": latency,
                                "prompt": prompt,
                            }
                        )
                    else:
                        confusion[f"{expected}->HTTP{response.status_code}"] += 1

    correct = sum(value for key, value in confusion.items() if key.split("->")[0] == key.split("->")[1])
    hard_to_t1 = confusion.get("T3->T1", 0)
    return {
        "probes": results,
        "models_advertised": model_ids,
        "routing_rows": route_rows,
        "routing_confusion": dict(confusion),
        "routing_accuracy": correct / 30,
        "hard_routed_to_t1": hard_to_t1,
    }


def run_rate_limit_boundary() -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    with temporary_key(f"judge-rpm-a-{int(time.time())}", 5) as first:
        with temporary_key(f"judge-rpm-b-{int(time.time())}", 5) as second:
            with httpx.Client(timeout=45) as client:
                first_headers = {"Authorization": f"Bearer {first['key']}"}
                for index in range(1, 7):
                    result, _ = safe_probe(
                        client,
                        f"key A request {index}",
                        "POST",
                        "/v1/chat/completions",
                        200 if index <= 5 else 429,
                        None if index <= 5 else "rate_limit_exceeded",
                        headers=first_headers,
                        json=chat_payload("Hi"),
                    )
                    observations.append(result)
                isolated, _ = safe_probe(
                    client,
                    "key B isolation",
                    "POST",
                    "/v1/chat/completions",
                    200,
                    headers={"Authorization": f"Bearer {second['key']}"},
                    json=chat_payload("Hi"),
                )
                observations.append(isolated)
        with httpx.Client(timeout=45) as client:
            client.delete(f"{HOST}/admin/keys/{first['id']}", headers=ADMIN_HEADERS).raise_for_status()
            revoked, _ = safe_probe(
                client,
                "revoked key",
                "POST",
                "/v1/chat/completions",
                401,
                "invalid_api_key",
                headers={"Authorization": f"Bearer {first['key']}"},
                json=chat_payload("Hi"),
            )
            observations.append(revoked)
    return {"configured_rpm": 5, "observations": observations, "passed": all(item["passed"] for item in observations)}


def run_daily_quota_boundary() -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    with temporary_key(f"judge-quota-{int(time.time())}", 60) as key:
        headers = {"Authorization": f"Bearer {key['key']}"}
        with httpx.Client(timeout=45) as client:
            for index in range(1, 10):
                started = time.perf_counter()
                response = client.post(f"{HOST}/v1/chat/completions", headers=headers, json=chat_payload("x" * 31_000))
                observations.append(
                    {
                        "request": index,
                        "status": response.status_code,
                        "error_code": error_code(response),
                        "retry_after": response.headers.get("Retry-After"),
                        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                    }
                )
                if error_code(response) == "daily_token_budget_exceeded":
                    break
    limited = next((item for item in observations if item["error_code"] == "daily_token_budget_exceeded"), None)
    return {"observations": observations, "passed": limited is not None, "first_quota_rejection": limited}


def parse_locust_stats(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, Any] = {}
    for row in rows:
        key = "http" if row["Type"] == "POST" else "router" if row["Type"] == "ROUTER" else "aggregate"
        result[key] = {
            "requests": int(row["Request Count"]),
            "failures": int(row["Failure Count"]),
            "rps": float(row["Requests/s"]),
            "average_ms": float(row["Average Response Time"]),
            "min_ms": float(row["Min Response Time"]),
            "max_ms": float(row["Max Response Time"]),
            "p50_ms": float(row["50%"]),
            "p90_ms": float(row["90%"]),
            "p95_ms": float(row["95%"]),
            "p99_ms": float(row["99%"]),
        }
    return result


def run_capacity() -> list[dict[str, Any]]:
    stages = (
        ("baseline_users_1", 1, "5m"),
        ("required_users_3", 3, "10m"),
        ("prd_max_users_5", 5, "15m"),
    )
    outcomes: list[dict[str, Any]] = []
    for name, users, duration in stages:
        with temporary_key(f"judge-{name}-{int(time.time())}", 300) as key:
            prefix = RESULTS / name
            summary = RESULTS / f"{name}_route_summary.json"
            env = os.environ.copy()
            env.update(
                {
                    "SR_LOAD_TEST_API_KEY": key["key"],
                    "SR_RPS_PER_USER": "0.5",
                    "SR_STAGE_SUMMARY_PATH": str(summary),
                    "SR_STOP_ON_FAILURE": "true",
                }
            )
            command = [
                str(PYTHON),
                "-m",
                "locust",
                "-f",
                str(ROOT / "loadtests" / "judge_locustfile.py"),
                "--host",
                HOST,
                "--headless",
                "--only-summary",
                "--users",
                str(users),
                "--spawn-rate",
                "1",
                "--run-time",
                duration,
                "--csv",
                str(prefix),
                "--html",
                str(prefix.with_suffix(".html")),
                "--exit-code-on-error",
                "1",
            ]
            print(f"Running {name}: users={users}, duration={duration}", flush=True)
            completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
            stats = parse_locust_stats(Path(f"{prefix}_stats.csv"))
            route_summary = json.loads(summary.read_text(encoding="utf-8")) if summary.exists() else {}
            outcome = {
                "name": name,
                "users": users,
                "duration": duration,
                "exit_code": completed.returncode,
                "stats": stats,
                "route_summary": route_summary,
            }
            outcomes.append(outcome)
            if completed.returncode != 0 or stats.get("http", {}).get("failures", 0):
                break
    return outcomes


def main() -> int:
    started = datetime.now(UTC)
    report: dict[str, Any] = {
        "generated_at": started.isoformat(),
        "target": HOST,
        "deployment_commit": "5d9a84eccf15a58a5139fc2ce03478aca4e2e370",
        "contract_and_routing": run_contract_and_routing(),
        "rate_limit": run_rate_limit_boundary(),
        "daily_quota": run_daily_quota_boundary(),
        "capacity": run_capacity(),
    }
    report["finished_at"] = datetime.now(UTC).isoformat()
    output = RESULTS / "results.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
