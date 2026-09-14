"""Run paired SmartRoute/strong-only requests and persist resumable outcomes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.evals.benchmarks.objective import grade_response
from src.evals.run_benchmark_eval import load_pricing


@dataclass
class RequestPacer:
    """Enforce a process-local request rate across smart and baseline calls."""

    requests_per_minute: float
    next_allowed_at: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def wait(self) -> None:
        if self.requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be greater than zero")
        with self.lock:
            now = time.monotonic()
            scheduled_at = max(now, self.next_allowed_at)
            self.next_allowed_at = scheduled_at + 60.0 / self.requests_per_minute
        delay = scheduled_at - now
        if delay > 0:
            time.sleep(delay)


def load_normalized_records(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    required = {"id", "prompt", "grader", "quality_type", "expected_tier"}
    for index, row in enumerate(rows, 1):
        missing = required - row.keys()
        if missing:
            raise ValueError(f"{path}:{index}: missing fields {sorted(missing)}")
        if not str(row["grader"]).startswith("evalplus_") and "reference_answer" not in row:
            raise ValueError(f"{path}:{index}: missing fields ['reference_answer']")
        if row["quality_type"] != "objective":
            raise ValueError(f"{path}:{index}: paired runner currently supports objective records only")
    return rows if limit is None else rows[:limit]


def completed_ids(path: Path, mode: str = "paired") -> set[str]:
    if not path.exists():
        return set()
    done = set()
    required_runs = ("strong",) if mode == "strong-only" else ("smart", "strong")
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if not any(run in row for run in required_runs):
            done.add(str(row["id"]))
            continue
        if all(row.get(run, {}).get("content") and not row[run].get("error") for run in required_runs):
            done.add(str(row["id"]))
    return done


def request_model(
    client: httpx.Client,
    endpoint: str,
    record: dict[str, Any],
    smartroute: dict[str, Any],
    max_tokens: int,
    max_attempts: int,
) -> dict[str, Any]:
    started = time.perf_counter()
    for attempt in range(1, max_attempts + 1):
        try:
            response = client.post(
                endpoint,
                json={
                    "model": "auto",
                    "messages": [{"role": "user", "content": record["prompt"]}],
                    "temperature": 0,
                    "max_tokens": max_tokens,
                    "stream": False,
                    "smartroute": smartroute,
                },
            )
            response.raise_for_status()
            payload = response.json()
            content = str(payload["choices"][0]["message"]["content"])
            usage = payload["usage"]
            metadata = payload.get("smartroute") or {}
            deferred_grader = str(record["grader"]).startswith("evalplus_") or record["grader"] == "math_verify_v1"
            return {
                "model_id": str(metadata.get("model_used") or payload.get("model")),
                "provider": metadata.get("provider") or response.headers.get("X-SR-Provider"),
                "prompt_tokens": int(usage["prompt_tokens"]),
                "completion_tokens": int(usage["completion_tokens"]),
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "request_id": metadata.get("request_id") or response.headers.get("X-SR-Request-Id"),
                "difficulty_score": metadata.get("difficulty_score"),
                "tier": metadata.get("tier"),
                "signals": metadata.get("signals") or [],
                "classifier_version": metadata.get("classifier_version"),
                "router_cost_usd": float(metadata.get("router_cost_usd") or 0.0),
                "latency_router_ms": metadata.get("latency_router_ms"),
                "content": content,
                "correct": None
                if deferred_grader
                else grade_response(record["grader"], content, record["reference_answer"]),
                "error": None,
                "attempts": attempt,
            }
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            retryable = isinstance(exc, httpx.TransportError) or (
                isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {429, 500, 502, 503, 504}
            )
            if retryable and attempt < max_attempts:
                retry_after = 0.0
                if isinstance(exc, httpx.HTTPStatusError):
                    try:
                        retry_after = float(exc.response.headers.get("Retry-After", "0"))
                    except ValueError:
                        retry_after = 0.0
                time.sleep(max(retry_after, min(2 ** (attempt - 1), 30)))
                continue
            return {
                "model_id": smartroute.get("force_model") or "unknown",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "latency_ms": round((time.perf_counter() - started) * 1000),
                "content": None,
                "correct": None,
                "error": f"{type(exc).__name__}: {exc}",
                "attempts": attempt,
            }
    raise AssertionError("unreachable")


def append_outcome(path: Path, outcome: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(outcome, ensure_ascii=False) + "\n")
        handle.flush()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=os.getenv("SMARTROUTE_API_KEY"))
    parser.add_argument("--pricing", type=Path, default=Path("src/gateway/app/config/pricing.yaml"))
    parser.add_argument("--strong-model")
    parser.add_argument(
        "--classifier-version",
        choices=("v1", "v1.5", "v2"),
        default="v1.5",
        help="Classifier requested for routed calls (default: v1.5).",
    )
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument(
        "--mode",
        choices=("paired", "strong-only"),
        default="paired",
        help="Use strong-only for a baseline score without spending routed calls.",
    )
    parser.add_argument(
        "--requests-per-minute",
        type=float,
        default=6.0,
        help="Process-local rate across both routed and strong-only calls (default: 6 RPM).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually call the gateway and incur provider usage; otherwise only print the run plan.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.workers < 1:
        raise ValueError("workers must be greater than zero")
    if args.max_attempts < 1:
        raise ValueError("max_attempts must be greater than zero")
    records = load_normalized_records(args.dataset, args.limit)
    configured_strong, _prices = load_pricing(args.pricing)
    strong_model = args.strong_model or configured_strong
    done = completed_ids(args.output, args.mode)
    pending = [record for record in records if str(record["id"]) not in done]
    print(
        f"Plan: {len(pending)} pending {args.mode} samples ({len(done)} cached), "
        f"classifier={args.classifier_version}, baseline={strong_model}, "
        f"endpoint={args.base_url}/v1/chat/completions"
    )
    if not args.execute:
        print("Dry run only. Add --execute to call providers.")
        return 0

    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"
    endpoint = args.base_url.rstrip("/") + "/v1/chat/completions"
    pacer = RequestPacer(args.requests_per_minute)
    strong_results: list[bool] = []

    def evaluate(record: dict[str, Any]) -> dict[str, Any]:
        if args.mode == "paired":
            pacer.wait()
            smart = request_model(
                client,
                endpoint,
                record,
                {"classifier_version": args.classifier_version},
                args.max_tokens,
                args.max_attempts,
            )
        else:
            smart = {"error": "not_run", "correct": None}
        pacer.wait()
        strong = request_model(
            client,
            endpoint,
            record,
            {"force_model": strong_model},
            args.max_tokens,
            args.max_attempts,
        )
        return {
            "id": record["id"],
            "mode": args.mode,
            "classifier_version": args.classifier_version,
            "benchmark": record.get("benchmark"),
            "expected_tier": record["expected_tier"],
            "quality_type": "objective",
            "grader": record["grader"],
            "source_revision": record.get("source_revision"),
            "reference_answer": record.get("reference_answer"),
            "smart": smart,
            "strong": strong,
        }

    with httpx.Client(headers=headers, timeout=args.timeout) as client:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(evaluate, record): record for record in pending}
            for position, future in enumerate(as_completed(futures), 1):
                outcome = future.result()
                append_outcome(args.output, outcome)
                strong = outcome["strong"]
                if strong["correct"] is not None:
                    strong_results.append(bool(strong["correct"]))
                print(
                    f"[{position}/{len(pending)}] {outcome['id']}: "
                    f"smart={outcome['smart']['correct']} strong={strong['correct']}"
                )
    if strong_results:
        print(
            f"Strong-only accuracy: {sum(strong_results)}/{len(strong_results)} = {sum(strong_results) / len(strong_results):.2%}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
