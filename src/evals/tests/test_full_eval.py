"""Bảo vệ các bất biến của run_full_eval.py — cái mà #211 dựa vào để tin số liệu.

Ba thứ được khoá lại ở đây:
  1. Cùng seed + cùng bộ đề  → cùng kế hoạch chạy (tái lập được).
  2. Lượt gọi lỗi KHÔNG bị coi là xong (cache không nuốt mất lỗi).
  3. Chi phí gộp cả tiền classifier, và độ chính xác định tuyến chỉ tính cho smartroute.
"""

import json

import httpx
import pytest

from src.evals.run_full_eval import (
    TIERS,
    Task,
    build_body,
    build_tasks,
    compute_run_fingerprint,
    fetch_final_usage,
    fetch_gateway_commit_sha,
    fingerprint_mismatch,
    load_dataset,
    load_done_keys,
    load_fingerprint,
    run_task,
    save_fingerprint,
    summarise,
)


def _record(record_id: str, prompt: str = "hỏi gì đó", **extra) -> dict:
    return {"id": record_id, "prompt": prompt, **extra}


def _raw(path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


# ─────────────────────────── 1. kế hoạch chạy tái lập ────────────────────────


def test_build_tasks_same_seed_gives_same_plan():
    records = [_record(f"p{i}") for i in range(10)]
    modes = ("all_premium", "random", "smartroute")

    first = [(t.prompt_id, t.mode, t.forced_tier) for t in build_tasks(records, modes, seed=42)]
    second = [(t.prompt_id, t.mode, t.forced_tier) for t in build_tasks(records, modes, seed=42)]

    assert first == second


def test_random_tier_is_stable_when_limit_grows():
    """Chạy --limit 5 rồi --limit 0 phải giữ nguyên hạng đã bốc cho 5 câu đầu.

    Đây là bất biến thật của cách bốc hiện tại: hạng phụ thuộc THỨ TỰ trong bộ đề.
    Nên bộ đề phải được ghim (yêu cầu tái lập của #211) thì arm `random` mới so
    sánh được giữa hai lần chạy.
    """
    records = [_record(f"p{i}") for i in range(10)]
    small = {t.prompt_id: t.forced_tier for t in build_tasks(records[:5], ("random",), seed=7)}
    full = {t.prompt_id: t.forced_tier for t in build_tasks(records, ("random",), seed=7)}

    assert all(full[pid] == tier for pid, tier in small.items())
    assert set(full.values()) <= set(TIERS)


def test_forced_tier_per_mode():
    records = [_record("p1")]
    tasks = build_tasks(records, ("all_cheap", "all_premium", "smartroute"), seed=1)
    forced = {t.mode: t.forced_tier for t in tasks}

    assert forced["all_cheap"] == "T1"
    assert forced["all_premium"] == "T3"
    assert forced["smartroute"] is None


def test_build_body_only_sends_smartroute_block_when_needed():
    plain = build_body(_record("p1"), None, None, None)
    assert "smartroute" not in plain
    assert plain["model"] == "auto"

    forced = build_body(_record("p1"), "T3", "cost_saver", 256)
    assert forced["smartroute"] == {"force_tier": "T3", "policy": "cost_saver"}
    assert forced["max_tokens"] == 256


# ──────────────────────── 2. cache không được nuốt lỗi ───────────────────────


def test_failed_call_is_not_marked_done(tmp_path):
    raw = tmp_path / "raw.jsonl"
    _raw(
        raw,
        [
            {"id": "p1", "mode": "smartroute", "ok": True},
            {"id": "p2", "mode": "smartroute", "ok": False, "error": "timeout"},
        ],
    )

    done = load_done_keys(raw)

    assert ("p1", "smartroute") in done
    assert ("p2", "smartroute") not in done


def test_load_done_keys_skips_broken_lines(tmp_path):
    raw = tmp_path / "raw.jsonl"
    raw.write_text(
        '{"id": "p1", "mode": "smartroute", "ok": true}\nkhông-phải-json\n\n',
        encoding="utf-8",
    )

    assert load_done_keys(raw) == {("p1", "smartroute")}


def test_old_success_does_not_mask_a_newer_failure(tmp_path):
    """Reviewer-flagged bug: load_done_keys used to mark a key done if ANY row for
    it ever succeeded, while summarise() takes the LAST row. After --no-resume logs
    a fresh failure for a key that had once succeeded, the two disagreed — summarise
    correctly reported it failed, but the next normal run still skipped retrying it."""
    raw = tmp_path / "raw.jsonl"
    _raw(
        raw,
        [
            {"id": "p1", "mode": "smartroute", "ok": True},
            {"id": "p1", "mode": "smartroute", "ok": False, "error": "timeout"},
        ],
    )

    assert load_done_keys(raw) == set()


def test_newer_success_after_older_failure_is_done(tmp_path):
    raw = tmp_path / "raw.jsonl"
    _raw(
        raw,
        [
            {"id": "p1", "mode": "smartroute", "ok": False, "error": "timeout"},
            {"id": "p1", "mode": "smartroute", "ok": True},
        ],
    )

    assert load_done_keys(raw) == {("p1", "smartroute")}


def test_load_dataset_limit_zero_reads_everything(tmp_path):
    dataset = tmp_path / "d.jsonl"
    _raw(dataset, [_record(f"p{i}") for i in range(4)])

    assert len(load_dataset(dataset, 0)) == 4
    assert len(load_dataset(dataset, 2)) == 2


# ─────────────────────────── 3. tổng hợp số đúng ─────────────────────────────


def test_summarise_counts_router_cost_into_total():
    rows = [
        {
            "id": "p1",
            "mode": "smartroute",
            "ok": True,
            "cost_usd": 0.001,
            "cost_routing_usd": 0.0002,
        }
    ]

    stats = summarise(rows, ("smartroute",))

    assert stats["smartroute"].cost_usd == pytest.approx(0.0012)
    assert stats["smartroute"].cost_missing == 0


def test_summarise_flags_rows_without_cost():
    rows = [{"id": "p1", "mode": "smartroute", "ok": True, "cost_usd": None}]

    stats = summarise(rows, ("smartroute",))

    assert stats["smartroute"].ok == 1
    assert stats["smartroute"].cost_missing == 1


def test_summarise_keeps_last_attempt_per_id_and_mode():
    """Chạy lại một câu bị lỗi phải thay dòng cũ, không cộng dồn thành hai lượt."""
    rows = [
        {"id": "p1", "mode": "smartroute", "ok": False},
        {"id": "p1", "mode": "smartroute", "ok": True, "cost_usd": 0.01},
    ]

    stats = summarise(rows, ("smartroute",))

    assert (stats["smartroute"].ok, stats["smartroute"].failed) == (1, 0)


def test_routing_accuracy_only_counts_smartroute():
    rows = [
        {"id": "p1", "mode": "smartroute", "ok": True, "tier_effective": "T3", "expected_tier": "T3"},
        {"id": "p2", "mode": "smartroute", "ok": True, "tier_effective": "T1", "expected_tier": "T3"},
        # Ba cách kia bị ép hạng nên không được tính là "định tuyến đúng".
        {"id": "p1", "mode": "all_premium", "ok": True, "tier_effective": "T3", "expected_tier": "T3"},
    ]

    stats = summarise(rows, ("smartroute", "all_premium"))

    assert stats["smartroute"].routing_accuracy == 0.5
    assert stats["all_premium"].routing_accuracy is None


def test_summarise_ignores_unknown_mode():
    rows = [{"id": "p1", "mode": "mode-la", "ok": True}]

    stats = summarise(rows, ("smartroute",))

    assert stats["smartroute"].total == 0


# ──────────── 4. gọi gateway: đọc đúng router cost, đồng bộ fallback thật ────────


def _chat_response(*, model_used: str, router_cost_usd: float) -> dict:
    """Phase-1 ("pending") shape của response tức thời — cost_usd luôn None,
    model_used/fallback_count là dự định, chưa phản ánh fallback thật (nếu có)."""
    return {
        "model": model_used,
        "choices": [{"message": {"content": "42"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        "smartroute": {
            "request_id": "rid-1",
            "tier": "T3",
            "tier_effective": "T3",
            "model_used": model_used,
            "provider": "openai",
            "policy": None,
            "router_cost_usd": router_cost_usd,
            "cost_usd": None,
            "fallback_count": 0,
            "chain_attempted": [{"model": model_used, "provider": "openai", "status": "pending"}],
        },
    }


def _usage_response(*, model_used: str, provider: str, fallback_count: int, cost_usd: float) -> dict:
    """Phase-2 ("complete") shape của GET /v1/usage/{id} — model/fallback thật."""
    return {
        "status": "complete",
        "smartroute": {
            "model_used": model_used,
            "provider": provider,
            "fallback_count": fallback_count,
            "chain_attempted": [
                {"model": "primary-model", "provider": "openai", "status": "error"},
                {"model": model_used, "provider": provider, "status": "ok"},
            ],
            "cost_usd": cost_usd,
            "latency_total_ms": 500,
            "latency_router_ms": 20,
            "usage_estimated": False,
        },
    }


def test_run_task_reads_router_cost_from_phase_one_response():
    """router_cost_usd is already final in the immediate response (set before the
    provider call) — must not be hard-coded to 0.0 or left for the Phase-2 fetch."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, json=_chat_response(model_used="primary-model", router_cost_usd=0.00002))
        return httpx.Response(200, json=_usage_response(model_used="primary-model", provider="openai", fallback_count=0, cost_usd=0.001))

    task = Task(record={"id": "p1", "prompt": "hỏi gì đó"}, mode="all_premium", forced_tier="T3")
    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        row = run_task(client, task, policy=None, max_tokens=None)

    assert row["cost_routing_usd"] == pytest.approx(0.00002)


def test_fetch_final_usage_syncs_real_model_after_fallback():
    """Reviewer-flagged bug: when a fallback happens, the immediate response still
    names the PRIMARY model (Phase 1, written before the provider call) — only
    /v1/usage/{id} (Phase 2) has the model that actually answered. fetch_final_usage
    must overwrite model_used/provider/fallback_count/chain_attempted, not just cost."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            return httpx.Response(200, json=_chat_response(model_used="primary-model", router_cost_usd=0.0))
        return httpx.Response(
            200,
            json=_usage_response(model_used="fallback-model", provider="google", fallback_count=1, cost_usd=0.001),
        )

    task = Task(record={"id": "p1", "prompt": "hỏi gì đó"}, mode="all_premium", forced_tier="T3")
    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        row = run_task(client, task, policy=None, max_tokens=None)

    assert row["model_used"] == "fallback-model"
    assert row["provider"] == "google"
    assert row["fallback_count"] == 1
    assert len(row["chain_attempted"]) == 2
    assert row["usage_settled"] is True


def test_fetch_final_usage_leaves_fields_alone_when_usage_never_settles():
    row = {"request_id": "rid-1", "model_used": "primary-model", "fallback_count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "pending", "smartroute": {"cost_usd": None}})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        fetch_final_usage(client, row, tries=1, delay=0.0)

    assert row["usage_settled"] is False
    assert row["model_used"] == "primary-model"


# ──────── 5. dấu vân tay cấu hình: resume không được trộn hai cấu hình khác nhau ──


def test_compute_run_fingerprint_changes_when_dataset_content_changes(tmp_path):
    dataset = tmp_path / "d.jsonl"
    dataset.write_text('{"id": "p1", "prompt": "a"}\n', encoding="utf-8")
    kwargs = dict(seed=1, policy=None, max_tokens=None, base_url="http://x", gateway_commit_sha="abc123")

    before = compute_run_fingerprint(dataset=dataset, **kwargs)
    dataset.write_text('{"id": "p1", "prompt": "b"}\n', encoding="utf-8")
    after = compute_run_fingerprint(dataset=dataset, **kwargs)

    assert before["dataset_sha256_16"] != after["dataset_sha256_16"]


def test_fingerprint_mismatch_reports_changed_fields_only():
    old = {"seed": 1, "policy": None, "base_url": "http://x"}
    new = {"seed": 1, "policy": "cost_saver", "base_url": "http://y"}

    diff = fingerprint_mismatch(old, new)

    assert len(diff) == 2
    assert any("policy" in line for line in diff)
    assert any("base_url" in line for line in diff)


def test_fingerprint_mismatch_empty_when_identical():
    fp = {"seed": 1, "policy": None}
    assert fingerprint_mismatch(fp, dict(fp)) == []


def test_save_and_load_fingerprint_round_trip(tmp_path):
    raw = tmp_path / "raw.jsonl"
    fingerprint = {"seed": 7, "dataset_sha256_16": "abc"}

    assert load_fingerprint(raw) is None
    save_fingerprint(raw, fingerprint)

    assert load_fingerprint(raw) == fingerprint
    assert (tmp_path / "raw.jsonl.fingerprint.json").exists()


def test_load_fingerprint_ignores_corrupt_file(tmp_path):
    raw = tmp_path / "raw.jsonl"
    (tmp_path / "raw.jsonl.fingerprint.json").write_text("not json", encoding="utf-8")

    assert load_fingerprint(raw) is None


def test_fetch_gateway_commit_sha_reads_healthz():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/healthz"
        return httpx.Response(200, json={"status": "ok", "commit_sha": "77ddfd4"})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        assert fetch_gateway_commit_sha(client) == "77ddfd4"


def test_fetch_gateway_commit_sha_none_when_unknown_or_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "commit_sha": "unknown"})

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        assert fetch_gateway_commit_sha(client) is None


def test_fetch_gateway_commit_sha_none_when_endpoint_unavailable():
    """Older gateway without /healthz, or a network hiccup — must not raise."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        assert fetch_gateway_commit_sha(client) is None
