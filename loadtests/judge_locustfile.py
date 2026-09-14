"""Locust workload for judge-facing SmartRoute staging capacity evidence."""

from __future__ import annotations

import json
import os
import threading
from collections import Counter
from pathlib import Path

from locust import constant_throughput, events, task
from locust.contrib.fasthttp import FastHttpUser

API_KEY = os.environ["SR_LOAD_TEST_API_KEY"]
RPS_PER_USER = float(os.getenv("SR_RPS_PER_USER", "0.5"))
SUMMARY_PATH = Path(os.environ["SR_STAGE_SUMMARY_PATH"])
STOP_ON_FAILURE = os.getenv("SR_STOP_ON_FAILURE", "true").lower() in {"1", "true", "yes"}

WORKLOADS = (
    ("easy", "T1", "Hi"),
    ("medium", "T2", "Compare REST and GraphQL."),
    ("hard", "T3", "Design a distributed lock with failure recovery and security tradeoffs."),
)

_lock = threading.Lock()
_routes: Counter[str] = Counter()
_http_statuses: Counter[str] = Counter()
_error_codes: Counter[str] = Counter()
_contract_failures: list[str] = []


def _record_failure(message: str) -> None:
    with _lock:
        _contract_failures.append(message[:500])


class SmartRouteCapacityUser(FastHttpUser):
    wait_time = constant_throughput(RPS_PER_USER)
    connection_timeout = 10.0
    network_timeout = 30.0

    def on_start(self) -> None:
        self.headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "SmartRoute-Judge-Benchmark/1.0",
        }

    def _completion(self, workload: str, expected_tier: str, prompt: str) -> None:
        payload = {
            "model": "auto",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": 1,
            "stream": False,
            "smartroute": {"force_tier": expected_tier},
        }
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            headers=self.headers,
            name="/v1/chat/completions",
            catch_response=True,
        ) as response:
            with _lock:
                _http_statuses[str(response.status_code)] += 1
            if response.status_code != 200:
                try:
                    body = response.json()
                    code = str(body.get("error", {}).get("code", "unknown"))
                except Exception:
                    code = "invalid_error_body"
                with _lock:
                    _error_codes[code] += 1
                message = (
                    f"HTTP {response.status_code}, code={code}, retry_after={response.headers.get('Retry-After', '')}"
                )
                _record_failure(message)
                response.failure(message)
                if STOP_ON_FAILURE and self.environment.runner:
                    self.environment.runner.quit()
                return

            try:
                body = response.json()
                metadata = body["smartroute"]
                router_latency_ms = float(metadata["latency_router_ms"])
                tier = str(metadata["tier"])
                model = str(metadata["model_used"])
                provider = str(metadata["provider"])
                request_id = response.headers["X-SR-Request-Id"]
                assert request_id
                assert tier == expected_tier, f"expected {expected_tier}, got {tier}"
                assert provider == "mock", f"expected mock, got {provider}"
                assert model == f"mock-{'cheap' if tier == 'T1' else 'mid' if tier == 'T2' else 'premium'}"
            except (AssertionError, KeyError, TypeError, ValueError) as exc:
                message = f"response contract: {exc}"
                _record_failure(message)
                response.failure(message)
                if STOP_ON_FAILURE and self.environment.runner:
                    self.environment.runner.quit()
                return

            response.success()
            with _lock:
                _routes[f"{workload}:{tier}:{model}:{provider}"] += 1
            events.request.fire(
                request_type="ROUTER",
                name="routing decision",
                response_time=router_latency_ms,
                response_length=0,
                exception=None,
                context={"workload": workload, "tier": tier},
            )

    @task(40)
    def easy(self) -> None:
        self._completion(*WORKLOADS[0])

    @task(35)
    def medium(self) -> None:
        self._completion(*WORKLOADS[1])

    @task(25)
    def hard(self) -> None:
        self._completion(*WORKLOADS[2])


@events.test_stop.add_listener
def write_stage_summary(environment, **_kwargs) -> None:
    stats = environment.stats.total
    payload = {
        "http_statuses": dict(_http_statuses),
        "error_codes": dict(_error_codes),
        "routes": dict(_routes),
        "contract_failures": _contract_failures[:20],
        "locust_total_requests_including_router_metrics": stats.num_requests,
        "locust_total_failures": stats.num_failures,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
