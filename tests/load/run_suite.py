"""Chạy cả bộ đo tải: mỗi mức người dùng lặp nhiều lần, rồi tính trung bình.

Vì sao có script này: mọi lần đo hỏng hôm nay đều do xoay khoá bằng tay — dùng lại
khoá đã tiêu gần hết ngân sách nên giữa chừng gặp 429 và Locust tự dừng. Script tạo
MỘT khoá mới trước mỗi lần chạy và thu hồi ngay sau đó, nên không lần nào ăn vào
ngân sách của lần khác.

Kết quả nhiều lần chạy được gộp lại: in trung bình kèm khoảng dao động (thấp nhất —
cao nhất), vì trung bình của ba lần mà giấu độ lệch thì che mất chính thứ cần biết.

Chạy:
    python run_suite.py --users 1 3 5 --repeats 3 --duration 5m
    python run_suite.py --aggregate-only          # gộp lại từ CSV đã có

Cần SR_ADMIN_KEY và SR_HOST như `loadkey.py`.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from loadkey import _request, resolve_admin_key  # noqa: E402

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[1]
_LOCUSTFILE = _HERE / "locustfile.py"
_PYTHON = _REPO_ROOT / ".venv" / "Scripts" / "python.exe"
if not _PYTHON.exists():  # Linux/macOS
    _PYTHON = _REPO_ROOT / ".venv" / "bin" / "python"

# Các dòng chỉ số Locust phát ra; giữ đúng tên để gộp được với lần đo trước.
_METRICS = (
    "POST /v1/chat/completions",
    "POST /v1/chat/completions (session)",
    "ROUTER routing decision",
)


def _create_key(host: str, admin_key: str, name: str, rpm: int) -> tuple[int, str] | None:
    status, payload = _request(
        "POST", host, "/admin/keys", admin_key, {"name": name, "rate_limit_per_min": rpm}
    )
    if status != 201 or not isinstance(payload, dict):
        print(f"  ! tạo khoá thất bại: HTTP {status} {payload}")
        return None
    return payload["id"], payload["key"]


def _revoke_key(host: str, admin_key: str, key_id: int) -> None:
    status, _ = _request("DELETE", host, f"/admin/keys/{key_id}", admin_key)
    if status != 200:
        print(f"  ! thu hồi khoá {key_id} thất bại (HTTP {status}) — nhớ xoá tay")


def _run_locust(host: str, api_key: str, users: int, duration: str, csv_prefix: Path) -> int:
    csv_prefix.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(_PYTHON), "-m", "locust",
        "-f", str(_LOCUSTFILE),
        "--host", host,
        "--headless",
        "-u", str(users), "-r", "1",
        "-t", duration,
        "--csv", str(csv_prefix),
        "--sr-api-key", api_key,
        "--sr-abort-error-rate", "0.05",
        "--sr-diag-file", str(csv_prefix) + "-diag.jsonl",
        "--only-summary",
    ]
    proc = subprocess.run(cmd, cwd=str(_REPO_ROOT))
    return proc.returncode


def _read_stats(path: Path) -> dict[str, dict[str, float]]:
    """Đọc <prefix>_stats.csv thành {tên chỉ số: {cột: số}}."""
    out: dict[str, dict[str, float]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            name = f"{row['Type']} {row['Name']}".strip()
            if row["Type"] == "" or name not in _METRICS:
                continue
            out[name] = {
                "requests": float(row["Request Count"]),
                "failures": float(row["Failure Count"]),
                "median": float(row["Median Response Time"]),
                "p95": float(row["95%"]),
                "p99": float(row["99%"]),
                "rps": float(row["Requests/s"]),
            }
    return out


def _summarise(runs: list[dict[str, dict[str, float]]]) -> dict:
    """Trung bình + khoảng dao động cho từng chỉ số qua các lần chạy."""
    summary: dict[str, dict[str, dict[str, float]]] = {}
    for metric in _METRICS:
        series = [r[metric] for r in runs if metric in r]
        if not series:
            continue
        summary[metric] = {}
        for field in ("requests", "failures", "median", "p95", "p99", "rps"):
            values = [s[field] for s in series]
            summary[metric][field] = {
                "mean": round(statistics.mean(values), 2),
                "min": min(values),
                "max": max(values),
                "n": len(values),
            }
    return summary


def _print_table(level_summaries: dict[int, dict]) -> None:
    print("\n" + "=" * 78)
    print("TRUNG BÌNH QUA CÁC LẦN CHẠY  (trung bình · thấp nhất–cao nhất)")
    print("=" * 78)
    for users in sorted(level_summaries):
        summary = level_summaries[users]
        print(f"\n--- {users} người dùng ---")
        for metric, fields in summary.items():
            req = fields["requests"]
            fail = fields["failures"]
            p95 = fields["p95"]
            med = fields["median"]
            err_pct = (fail["mean"] / req["mean"] * 100) if req["mean"] else 0.0
            print(
                f"  {metric:38} "
                f"req {req['mean']:7.0f} ({req['min']:.0f}–{req['max']:.0f})  "
                f"lỗi {err_pct:5.2f}%  "
                f"trung vị {med['mean']:7.0f}  "
                f"p95 {p95['mean']:7.0f} ({p95['min']:.0f}–{p95['max']:.0f})"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="")
    parser.add_argument("--admin-key", default="")
    parser.add_argument("--users", type=int, nargs="+", default=[1, 3, 5])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--duration", default="5m")
    parser.add_argument("--rpm", type=int, default=600)
    parser.add_argument("--out-dir", default="out/load/suite")
    parser.add_argument("--aggregate-only", action="store_true", help="Chỉ gộp CSV đã có, không chạy lại.")
    args = parser.parse_args()

    import os

    host = args.host or os.getenv("SR_HOST", "https://p-156-staging.onrender.com")
    out_dir = Path(args.out_dir)
    level_summaries: dict[int, dict] = {}

    if not args.aggregate_only:
        admin_key, source = resolve_admin_key(args.admin_key)
        if not admin_key:
            print("Thiếu khoá quản trị (SR_ADMIN_KEY hoặc --admin-key).", file=sys.stderr)
            return 2
        print(f"[suite] host={host}  nguồn khoá quản trị={source}")
        print(f"[suite] {len(args.users)} mức × {args.repeats} lần × {args.duration}")

        for users in args.users:
            for rep in range(1, args.repeats + 1):
                tag = f"u{users}-r{rep}"
                print(f"\n[suite] ===== {users} người, lần {rep}/{args.repeats} =====")

                created = _create_key(host, admin_key, f"suite-{tag}-{int(time.time())}", args.rpm)
                if created is None:
                    return 1
                key_id, raw_key = created
                print(f"[suite] khoá mới id={key_id} (ngân sách token còn nguyên)")

                try:
                    code = _run_locust(host, raw_key, users, args.duration, out_dir / tag)
                    if code != 0:
                        print(f"[suite] CẢNH BÁO: lần chạy thoát với mã {code} — nhiều khả năng đã tự dừng vì lỗi.")
                finally:
                    _revoke_key(host, admin_key, key_id)
                    print(f"[suite] đã thu hồi khoá {key_id}")

    for users in args.users:
        runs = []
        for rep in range(1, args.repeats + 1):
            stats = _read_stats(out_dir / f"u{users}-r{rep}_stats.csv")
            if stats:
                runs.append(stats)
        if runs:
            level_summaries[users] = _summarise(runs)

    if not level_summaries:
        print("Không tìm thấy kết quả nào để gộp.", file=sys.stderr)
        return 1

    _print_table(level_summaries)
    report = out_dir / "summary.json"
    report.write_text(
        json.dumps({str(k): v for k, v in level_summaries.items()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[suite] đã ghi {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
