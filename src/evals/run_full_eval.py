"""run_full_eval.py — chạy bộ đề qua 4 cách định tuyến, đo chi phí · độ trễ · độ chính xác.

Bốn cách chạy (AC-1 của #127):
    all_cheap    ép mọi câu xuống T1  (rẻ nhất)
    all_premium  ép mọi câu lên  T3   (mốc so sánh tier, KHÔNG ép cứng 1 model — xem dưới)
    random       chọn hạng ngẫu nhiên, có seed để chạy lại ra y hệt
    smartroute   để gateway tự chấm điểm và chọn

`all_premium` là "tier baseline" chứ không phải "fixed model baseline": nó chỉ gửi
`force_tier=T3`, không gửi `force_model`. Nếu model chính của T3 (`premium_baseline_model`
trong pricing.yaml) lỗi/quá tải, gateway TỰ chuyển sang model dự phòng cùng tier thay vì trả
lỗi cho người dùng — cố ý, vì ưu tiên có câu trả lời hơn là ép đúng 1 model rồi báo lỗi khi nó
sập. Cột "Số lần fallback" trong báo cáo cho biết arm này có bị chuyển model hay không; nếu > 0
cho `all_premium`, baseline hôm đó không hoàn toàn là 1 model duy nhất trên mọi câu.

Ba nguyên tắc chống đốt tiền — mỗi lượt gọi là tiền thật:
  1. Kết quả ghi ngay từng dòng vào tệp raw. Chạy hỏng giữa chừng không mất phần đã chạy.
  2. Chạy lại trên cùng tệp raw sẽ **bỏ qua** cặp (id, mode) đã có. Đây cũng chính là
     cơ chế cache `all_premium` mà AC-1 yêu cầu: chạy một lần rồi dùng lại mãi.
  3. Mặc định chỉ chạy 5 câu. Muốn chạy đủ phải nói rõ `--limit 0`.

Resume an toàn: mỗi tệp raw có một tệp `<raw>.fingerprint.json` đi kèm, ghi lại dataset
(hash nội dung), seed, policy, max_tokens, base_url, và commit_sha thật của gateway (qua
GET /healthz). Đổi bất kỳ trường nào rồi chạy lại trên CÙNG tệp raw sẽ bị chặn — công cụ
không lặng lẽ trộn số liệu của hai cấu hình khác nhau vào một báo cáo. Dùng `--no-resume`
để cố ý chạy sạch trên tệp raw đó, hoặc đổi `--raw` sang tệp khác. `--limit` và `--modes`
KHÔNG nằm trong fingerprint — mở rộng limit hay thêm mode mới là quy trình dùng bình
thường (xem ví dụ dưới), không phải đổi cấu hình.

Ví dụ:
    # xem kế hoạch, không gọi gì cả
    uv run python src/evals/run_full_eval.py --dry-run --limit 0

    # chạy thử miễn phí (cần USE_MOCK_PROVIDERS=true trong .env)
    uv run python src/evals/run_full_eval.py --limit 5

    # chạy thật 50 câu rồi mới chạy đủ
    uv run python src/evals/run_full_eval.py --limit 50
    uv run python src/evals/run_full_eval.py --limit 0

    # chỉ tổng hợp lại từ tệp raw đã có, không gọi API
    uv run python src/evals/run_full_eval.py --summary-only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

EVALS_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = EVALS_DIR / "datasets" / "mixed_200.jsonl"
DEFAULT_RESULTS_DIR = EVALS_DIR / "results"

# Console Windows mặc định là cp1252, in tiếng Việt sẽ ném UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# Hạng ép cho từng cách chạy. None = không ép, để gateway tự quyết.
MODE_TIERS: dict[str, str | None] = {
    "all_cheap": "T1",
    "all_premium": "T3",
    "random": "RANDOM",
    "smartroute": None,
}
TIERS = ("T1", "T2", "T3")
DEFAULT_MODES = ("all_premium", "all_cheap", "random", "smartroute")


# ─────────────────────────────── kiểu dữ liệu ────────────────────────────────


@dataclass
class Task:
    """Một lượt gọi cần thực hiện: câu hỏi nào, chạy theo cách nào."""

    record: dict
    mode: str
    forced_tier: str | None

    @property
    def prompt_id(self) -> str:
        return str(self.record.get("id", ""))

    @property
    def key(self) -> tuple[str, str]:
        return (self.prompt_id, self.mode)


@dataclass
class ModeStats:
    """Số liệu gộp của một cách chạy."""

    mode: str
    ok: int = 0
    failed: int = 0
    cost_usd: float = 0.0
    latency_total: list[int] = field(default_factory=list)
    latency_router: list[int] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    fallbacks: int = 0
    tier_counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(TIERS, 0))
    routed_correct: int = 0
    routed_labelled: int = 0
    cost_missing: int = 0  # lượt gọi thành công nhưng không lấy được chi phí

    @property
    def total(self) -> int:
        return self.ok + self.failed

    @property
    def routing_accuracy(self) -> float | None:
        if not self.routed_labelled:
            return None
        return self.routed_correct / self.routed_labelled


# ──────────────────────────────── đọc / ghi ──────────────────────────────────


def load_dataset(path: Path, limit: int) -> list[dict]:
    """Đọc tệp .jsonl, mỗi dòng một câu hỏi. limit=0 nghĩa là lấy hết."""
    if not path.exists():
        sys.exit(f"Không tìm thấy bộ đề: {path}")
    records: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.exit(f"{path}:{line_no} không phải JSON hợp lệ: {exc}")
        if not record.get("prompt"):
            sys.exit(f"{path}:{line_no} thiếu trường 'prompt'")
        records.append(record)
        if limit and len(records) >= limit:
            break
    return records


def load_done_keys(raw_path: Path) -> set[tuple[str, str]]:
    """Các cặp (id, mode) mà LƯỢT GẦN NHẤT trong tệp raw đã thành công.

    Chỉ dòng cuối cùng của mỗi (id, mode) quyết định — khớp với cách `summarise`
    tổng hợp số liệu (cũng lấy dòng cuối). Nếu chỉ đếm "từng có ok=True", một
    lần thành công cũ sẽ che mất một lần thất bại mới hơn (ví dụ sau khi chạy lại
    bằng --no-resume mà lượt đó lỗi): report tính đúng là failed, nhưng lần chạy
    tiếp theo lại im lặng skip, không thử lại.
    """
    latest_ok: dict[tuple[str, str], bool] = {}
    if not raw_path.exists():
        return set()
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = (str(row.get("id", "")), str(row.get("mode", "")))
        latest_ok[key] = bool(row.get("ok"))
    return {key for key, ok in latest_ok.items() if ok}


def read_rows(raw_path: Path) -> list[dict]:
    rows: list[dict] = []
    if not raw_path.exists():
        return rows
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def append_row(raw_path: Path, row: dict) -> None:
    """Ghi ngay từng dòng — chạy hỏng giữa chừng vẫn giữ được phần đã xong."""
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    with raw_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ────────────────────── dấu vân tay cấu hình (resume an toàn) ────────────────
#
# Cache resume chỉ khoá theo (id, mode) — đổi dataset/seed/policy/max_tokens/
# base_url/commit gateway giữa hai lần chạy thì các cặp key trùng vẫn bị coi là
# "đã xong", report sẽ lặng lẽ trộn số liệu của hai cấu hình khác nhau. `limit`
# và `modes` CỐ Ý không nằm trong dấu vân tay: mở rộng limit hoặc thêm mode mới
# là quy trình dùng bình thường của công cụ này (xem docstring đầu file), không
# phải thứ làm số liệu cũ hết hiệu lực.


def fingerprint_path(raw_path: Path) -> Path:
    return raw_path.with_name(raw_path.name + ".fingerprint.json")


def fetch_gateway_commit_sha(client: httpx.Client) -> str | None:
    """Đọc commit_sha thật của gateway đang chạy qua GET /healthz (Issue #197).

    Không suy luận từ git local — script này gọi HTTP, gateway có thể là máy
    khác. Không raise: gateway cũ chưa có endpoint, hoặc /healthz lỗi tạm thời,
    đều không được làm hỏng cả lượt chạy vì một trường thông tin.
    """
    try:
        response = client.get("/healthz")
        if response.status_code != 200:
            return None
        commit_sha = response.json().get("commit_sha")
    except (httpx.HTTPError, ValueError):
        return None
    return commit_sha if commit_sha and commit_sha != "unknown" else None


def compute_run_fingerprint(
    *,
    dataset: Path,
    seed: int,
    policy: str | None,
    max_tokens: int | None,
    base_url: str,
    gateway_commit_sha: str | None,
) -> dict[str, Any]:
    dataset_sha256 = hashlib.sha256(dataset.read_bytes()).hexdigest()[:16]
    return {
        "dataset_path": str(dataset),
        "dataset_sha256_16": dataset_sha256,
        "seed": seed,
        "policy": policy,
        "max_tokens": max_tokens,
        "base_url": base_url,
        "gateway_commit_sha": gateway_commit_sha,
    }


def load_fingerprint(raw_path: Path) -> dict[str, Any] | None:
    path = fingerprint_path(raw_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_fingerprint(raw_path: Path, fingerprint: dict[str, Any]) -> None:
    fingerprint_path(raw_path).write_text(
        json.dumps(fingerprint, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fingerprint_mismatch(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Trả về danh sách các trường lệch nhau, dạng người đọc được. Rỗng = khớp."""
    keys = sorted(set(old) | set(new))
    return [f"{key}: {old.get(key)!r} -> {new.get(key)!r}" for key in keys if old.get(key) != new.get(key)]


# ───────────────────────────────── gọi API ───────────────────────────────────


def build_body(record: dict, forced_tier: str | None, policy: str | None, max_tokens: int | None) -> dict:
    smartroute: dict = {}
    if forced_tier:
        smartroute["force_tier"] = forced_tier
    if policy:
        smartroute["policy"] = policy

    body: dict = {
        "model": "auto",
        "messages": [{"role": "user", "content": record["prompt"]}],
    }
    if max_tokens:
        body["max_tokens"] = max_tokens
    if smartroute:
        body["smartroute"] = smartroute
    return body


def run_task(client: httpx.Client, task: Task, policy: str | None, max_tokens: int | None) -> dict:
    """Gọi gateway một lượt, trả về một dòng kết quả (luôn trả về, không ném lỗi)."""
    row: dict = {
        "id": task.prompt_id,
        "mode": task.mode,
        "forced_tier": task.forced_tier,
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "expected_tier": task.record.get("expected_tier"),
        "category": task.record.get("category"),
        "difficulty_label": task.record.get("difficulty"),
        "language": task.record.get("language"),
        "ok": False,
    }
    body = build_body(task.record, task.forced_tier, policy, max_tokens)
    started = time.perf_counter()
    try:
        response = client.post("/v1/chat/completions", json=body)
    except httpx.HTTPError as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["client_ms"] = int((time.perf_counter() - started) * 1000)
        return row

    row["client_ms"] = int((time.perf_counter() - started) * 1000)
    row["status_code"] = response.status_code

    try:
        payload = response.json()
    except ValueError:
        row["error"] = f"phản hồi không phải JSON: {response.text[:200]}"
        return row

    if response.status_code != 200:
        error = payload.get("error") if isinstance(payload, dict) else None
        row["error"] = json.dumps(error, ensure_ascii=False) if error else str(payload)[:300]
        return row

    meta = payload.get("smartroute") or {}
    usage = payload.get("usage") or {}
    choices = payload.get("choices") or [{}]

    row.update(
        {
            "ok": True,
            "request_id": meta.get("request_id"),
            "tier": meta.get("tier"),
            "tier_effective": meta.get("tier_effective") or meta.get("tier"),
            "difficulty_score": meta.get("difficulty_score"),
            "signals": meta.get("signals"),
            "model_used": meta.get("model_used"),
            "provider": meta.get("provider"),
            "policy": meta.get("policy"),
            # router_cost_usd đã final ngay ở Phase 1 (được set trước khi gọi
            # provider — xem chat_completions.py `pending`), khác với cost_usd
            # (Phase 2, luôn None ở đây, phải chờ fetch_final_usage).
            "cost_routing_usd": meta.get("router_cost_usd", 0.0),
            "cost_generation_usd": meta.get("cost_usd"),
            "cost_usd": meta.get("cost_usd"),
            "latency_total_ms": meta.get("latency_total_ms"),
            "latency_router_ms": meta.get("latency_router_ms"),
            "fallback_count": meta.get("fallback_count", 0),
            "chain_attempted": meta.get("chain_attempted"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "answer": (choices[0].get("message") or {}).get("content"),
        }
    )
    fetch_final_usage(client, row)
    return row


def fetch_final_usage(client: httpx.Client, row: dict, tries: int = 6, delay: float = 0.4) -> None:
    """Lấy chi phí, độ trễ, và định tuyến cuối cùng qua `/v1/usage/{request_id}`.

    Gateway ghi log 2 pha. Phản hồi tức thời của /v1/chat/completions build từ dòng
    Phase 1 ("pending", ghi TRƯỚC khi gọi provider): model_used/provider ở đó luôn
    là model DỰ ĐỊNH gọi, fallback_count luôn là 0, chain_attempted chỉ có 1 phần
    tử trạng thái "pending" — dù chuyện fallback (nếu có) đã xảy ra xong trước khi
    response được trả về. Chỉ dòng Phase 2 trong DB (đọc qua endpoint này) mới có
    model/provider/fallback_count/chain_attempted THẬT. Nên `cost_usd` trong phản
    hồi tức thời cũng luôn là None — phải hỏi lại endpoint usage mới có số.
    (Giao diện Playground cũng làm đúng như vậy.)
    """
    request_id = row.get("request_id")
    if not request_id:
        return
    for attempt in range(tries):
        try:
            response = client.get(f"/v1/usage/{request_id}")
            if response.status_code != 200:
                return
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return

        meta = payload.get("smartroute") or {}
        if payload.get("status") == "complete" or meta.get("cost_usd") is not None:
            cost = meta.get("cost_usd")
            row["cost_generation_usd"] = cost
            row["cost_usd"] = cost
            row["latency_total_ms"] = meta.get("latency_total_ms", row.get("latency_total_ms"))
            row["latency_router_ms"] = meta.get("latency_router_ms", row.get("latency_router_ms"))
            row["usage_estimated"] = meta.get("usage_estimated")
            # Model/fallback thật chỉ chốt ở Phase 2 — đồng bộ lại, ghi đè giá trị
            # "dự định" của Phase 1 mà run_task đã tạm ghi vào row.
            row["model_used"] = meta.get("model_used", row.get("model_used"))
            row["provider"] = meta.get("provider", row.get("provider"))
            row["fallback_count"] = meta.get("fallback_count", row.get("fallback_count"))
            row["chain_attempted"] = meta.get("chain_attempted", row.get("chain_attempted"))
            row["usage_settled"] = True
            return
        if attempt < tries - 1:
            time.sleep(delay)
    # Hết lượt thử mà vẫn "pending" — giữ nguyên dòng, đánh dấu để lúc tổng hợp biết.
    row["usage_settled"] = False


# ─────────────────────────────── tổng hợp số ─────────────────────────────────


def summarise(rows: list[dict], modes: tuple[str, ...]) -> dict[str, ModeStats]:
    stats = {mode: ModeStats(mode=mode) for mode in modes}
    # Một cặp (id, mode) có thể xuất hiện nhiều lần nếu chạy lại — lấy dòng cuối.
    latest: dict[tuple[str, str], dict] = {}
    for row in rows:
        latest[(str(row.get("id")), str(row.get("mode")))] = row

    for (_, mode), row in latest.items():
        stat = stats.get(mode)
        if stat is None:
            continue
        if not row.get("ok"):
            stat.failed += 1
            continue

        stat.ok += 1
        if row.get("cost_usd") is None:
            stat.cost_missing += 1
        stat.cost_usd += float(row.get("cost_usd") or 0.0)
        stat.cost_usd += float(row.get("cost_routing_usd") or 0.0)
        if row.get("latency_total_ms") is not None:
            stat.latency_total.append(int(row["latency_total_ms"]))
        if row.get("latency_router_ms") is not None:
            stat.latency_router.append(int(row["latency_router_ms"]))
        stat.prompt_tokens += int(row.get("prompt_tokens") or 0)
        stat.completion_tokens += int(row.get("completion_tokens") or 0)
        stat.fallbacks += int(row.get("fallback_count") or 0)

        tier = row.get("tier_effective") or row.get("tier")
        if tier in stat.tier_counts:
            stat.tier_counts[tier] += 1

        # Định tuyến đúng hạng: chỉ tính cho smartroute, vì ba cách kia bị ép hạng.
        expected = row.get("expected_tier")
        if mode == "smartroute" and expected in TIERS:
            stat.routed_labelled += 1
            if tier == expected:
                stat.routed_correct += 1
    return stats


def percentile(values: list[int], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * pct
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def fmt_money(value: float | None) -> str:
    return "—" if value is None else f"${value:.6f}"


def fmt_ms(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}ms"


def fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def render_report(stats: dict[str, ModeStats], dataset: Path, baseline_mode: str) -> str:
    baseline = stats.get(baseline_mode)
    baseline_cost = baseline.cost_usd if baseline and baseline.ok else None

    lines: list[str] = [
        "# Kết quả đo — 4 cách định tuyến",
        "",
        f"- Bộ đề: `{dataset.name}`",
        f"- Thời điểm: {datetime.now(UTC).isoformat(timespec='seconds')}",
        f"- Mốc so sánh tiết kiệm: `{baseline_mode}`",
        "",
        "| Cách chạy | Số câu | Lỗi | Tổng tiền | Tiết kiệm | Độ trễ p50 | p95 | Router p95 | Định tuyến đúng |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for mode, stat in stats.items():
        savings = None
        if baseline_cost and stat.ok and mode != baseline_mode:
            savings = (baseline_cost - stat.cost_usd) / baseline_cost
        lines.append(
            "| `{mode}` | {ok} | {failed} | {cost} | {savings} | {p50} | {p95} | {rp95} | {acc} |".format(
                mode=mode,
                ok=stat.ok,
                failed=stat.failed,
                cost=fmt_money(stat.cost_usd if stat.ok else None),
                savings="— (mốc)" if mode == baseline_mode else fmt_pct(savings),
                p50=fmt_ms(percentile(stat.latency_total, 0.50)),
                p95=fmt_ms(percentile(stat.latency_total, 0.95)),
                rp95=fmt_ms(percentile(stat.latency_router, 0.95)),
                acc=fmt_pct(stat.routing_accuracy),
            )
        )

    lines += [
        "",
        "## Phân bố hạng thực tế",
        "",
        "| Cách chạy | T1 | T2 | T3 | Số lần fallback |",
        "|---|---|---|---|---|",
    ]
    for mode, stat in stats.items():
        counts = stat.tier_counts
        lines.append(f"| `{mode}` | {counts['T1']} | {counts['T2']} | {counts['T3']} | {stat.fallbacks} |")

    lines += ["", "## Token", "", "| Cách chạy | Token vào | Token ra |", "|---|---|---|"]
    for mode, stat in stats.items():
        lines.append(f"| `{mode}` | {stat.prompt_tokens} | {stat.completion_tokens} |")

    missing = {mode: stat.cost_missing for mode, stat in stats.items() if stat.cost_missing}
    if missing:
        lines += [
            "",
            "> ⚠️ **Cảnh báo:** có lượt gọi thành công nhưng không lấy được chi phí "
            f"(usage chưa kịp ghi xong): {missing}. Tổng tiền ở trên vì thế **thấp hơn thực tế**.",
        ]

    lines += [
        "",
        "> Cột **Định tuyến đúng** chỉ tính cho `smartroute` — ba cách kia bị ép hạng nên",
        "> so với `expected_tier` là vô nghĩa.",
        "",
        "> Chưa có cột **chất lượng**: bộ đề hiện chỉ có nhãn `expected_tier`, chưa có đáp án đúng.",
        "> Muốn đo chất lượng cần bộ đề có đáp án (MATH-500, HumanEval) hoặc mô hình chấm điểm.",
        "",
    ]
    return "\n".join(lines)


def print_console(stats: dict[str, ModeStats], baseline_mode: str) -> None:
    baseline = stats.get(baseline_mode)
    baseline_cost = baseline.cost_usd if baseline and baseline.ok else None
    header = f"{'cách chạy':<14}{'xong':>6}{'lỗi':>6}{'tiền':>13}{'tiết kiệm':>12}{'p50':>9}{'đúng hạng':>12}"
    print("\n" + header)
    print("-" * len(header))
    for mode, stat in stats.items():
        savings = "— (mốc)"
        if baseline_cost and stat.ok and mode != baseline_mode:
            savings = fmt_pct((baseline_cost - stat.cost_usd) / baseline_cost)
        print(
            f"{mode:<14}{stat.ok:>6}{stat.failed:>6}{fmt_money(stat.cost_usd):>13}"
            f"{savings:>12}{fmt_ms(percentile(stat.latency_total, 0.5)):>9}"
            f"{fmt_pct(stat.routing_accuracy):>12}"
        )
    print()


# ──────────────────────────────── điều phối ──────────────────────────────────


def build_tasks(records: list[dict], modes: tuple[str, ...], seed: int) -> list[Task]:
    """Dựng danh sách lượt gọi. `all_premium` xếp trước để có mốc so sánh sớm."""
    rng = random.Random(seed)
    # Bốc hạng ngẫu nhiên theo id, không theo thứ tự chạy → chạy lại vẫn ra y hệt.
    random_tier = {str(rec.get("id")): rng.choice(TIERS) for rec in records}

    tasks: list[Task] = []
    for mode in modes:
        spec = MODE_TIERS[mode]
        for record in records:
            forced = random_tier[str(record.get("id"))] if spec == "RANDOM" else spec
            tasks.append(Task(record=record, mode=mode, forced_tier=forced))
    return tasks


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Chạy bộ đề qua 4 cách định tuyến và đo số.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="địa chỉ gateway")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--limit", type=int, default=5, help="số câu (0 = chạy hết). Mặc định 5 cho an toàn.")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES), help="danh sách cách chạy, ngăn bởi dấu phẩy")
    parser.add_argument("--baseline", default="all_premium", help="cách chạy dùng làm mốc tính tiết kiệm")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RESULTS_DIR / "raw.jsonl")
    parser.add_argument("--report", type=Path, default=DEFAULT_RESULTS_DIR / "eval_summary.md")
    parser.add_argument("--policy", default=None, help="ép một policy cho mọi lượt (mặc định: theo gateway)")
    parser.add_argument("--max-tokens", type=int, default=None, help="giới hạn token ra, để kìm chi phí")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--sleep", type=float, default=0.0, help="nghỉ giữa hai lượt gọi (giây), tránh bị chặn")
    parser.add_argument("--api-key", default=None, help="Bearer token nếu gateway bật xác thực")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true", help="chỉ in kế hoạch, không gọi API")
    parser.add_argument("--summary-only", action="store_true", help="chỉ tổng hợp lại từ tệp raw có sẵn")
    parser.add_argument("--no-resume", action="store_true", help="chạy lại tất cả, bỏ qua tệp raw cũ")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    modes = tuple(m.strip() for m in args.modes.split(",") if m.strip())
    unknown = [m for m in modes if m not in MODE_TIERS]
    if unknown:
        sys.exit(f"Cách chạy không hợp lệ: {unknown}. Hợp lệ: {list(MODE_TIERS)}")

    if args.summary_only:
        rows = read_rows(args.raw)
        if not rows:
            sys.exit(f"Chưa có dữ liệu trong {args.raw}")
        stats = summarise(rows, modes)
        print_console(stats, args.baseline)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(render_report(stats, args.dataset, args.baseline), encoding="utf-8")
        print(f"Đã ghi báo cáo: {args.report}")
        return 0

    records = load_dataset(args.dataset, args.limit)
    tasks = build_tasks(records, modes, args.seed)

    done = set() if args.no_resume else load_done_keys(args.raw)
    todo = [t for t in tasks if t.key not in done]
    skipped = len(tasks) - len(todo)

    per_mode = defaultdict(int)
    for task in todo:
        per_mode[task.mode] += 1

    print(f"Bộ đề        : {args.dataset.name} — {len(records)} câu")
    print(f"Cách chạy    : {', '.join(modes)}")
    print(f"Tổng lượt gọi: {len(tasks)}  (bỏ qua vì đã chạy: {skipped}  →  cần gọi: {len(todo)})")
    for mode in modes:
        print(f"  - {mode:<13}{per_mode[mode]:>5} lượt")
    print(f"Tệp raw      : {args.raw}")

    if args.dry_run:
        print("\n[--dry-run] Không gọi API. Bỏ cờ này để chạy thật.")
        return 0
    if not todo:
        print("\nKhông còn lượt nào cần gọi. Dùng --summary-only để tổng hợp lại.")
        return 0

    headers = {"Authorization": f"Bearer {args.api_key}"} if args.api_key else {}
    failures = 0
    with httpx.Client(base_url=args.base_url, timeout=args.timeout, headers=headers) as client:
        fingerprint = compute_run_fingerprint(
            dataset=args.dataset,
            seed=args.seed,
            policy=args.policy,
            max_tokens=args.max_tokens,
            base_url=args.base_url,
            gateway_commit_sha=fetch_gateway_commit_sha(client),
        )
        if not args.no_resume:
            previous_fingerprint = load_fingerprint(args.raw)
            if previous_fingerprint is not None:
                mismatch = fingerprint_mismatch(previous_fingerprint, fingerprint)
                if mismatch:
                    sys.exit(
                        f"Cấu hình lần này khác lần trước đã ghi vào {args.raw} — "
                        "tiếp tục resume sẽ trộn số liệu của hai cấu hình khác nhau:\n"
                        + "\n".join(f"  - {line}" for line in mismatch)
                        + "\n\nDùng --no-resume để chạy sạch trên tệp raw này, "
                        "hoặc đổi --raw sang tệp khác cho cấu hình mới."
                    )
        save_fingerprint(args.raw, fingerprint)

        for index, task in enumerate(todo, start=1):
            row = run_task(client, task, args.policy, args.max_tokens)
            append_row(args.raw, row)
            if row.get("ok"):
                mark = f"{row.get('tier_effective') or '??'} {row.get('model_used') or '?'}"
            else:
                failures += 1
                mark = f"LỖI {str(row.get('error'))[:60]}"
            print(f"[{index}/{len(todo)}] {task.mode:<13}{task.prompt_id:<14}{mark}")
            if args.sleep:
                time.sleep(args.sleep)

    rows = read_rows(args.raw)
    stats = summarise(rows, modes)
    print_console(stats, args.baseline)

    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(stats, args.dataset, args.baseline), encoding="utf-8")
    print(f"Đã ghi báo cáo: {args.report}")
    print(f"Dữ liệu thô  : {args.raw}")
    if failures:
        print(f"\nCó {failures} lượt lỗi — chạy lại lệnh cũ để thử lại đúng những lượt đó.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
