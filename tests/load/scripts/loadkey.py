"""Quản lý key dùng riêng cho load test, qua admin API.

Không dùng `GATEWAY_DEV_KEY` để chạy tải: middleware gán cứng
`request.state.rate_limit = 60` cho dev key (`src/gateway/app/api/middleware.py`),
nên 3 user × 0.5 rps = 90 rpm sẽ bị chính gateway trả 429 và số đo thành vô nghĩa.
Key tạo qua `POST /admin/keys` có `rate_limit_per_min` riêng, đặt cao hơn tải dự kiến.

Lệnh:
    python loadkey.py preflight            # kiểm tra admin key, sức khoẻ, quota còn lại
    python loadkey.py create --rpm 600     # tạo key, in ra key thật (chỉ hiện MỘT lần)
    python loadkey.py stats --minutes 60   # chụp /admin/stats của cửa sổ vừa chạy
    python loadkey.py revoke --id 12       # thu hồi key sau khi đo xong

Khoá quản trị tìm theo thứ tự, dừng ở nguồn đầu tiên có giá trị:
    1. cờ --admin-key
    2. biến môi trường SR_ADMIN_KEY
    3. biến môi trường ADMIN_KEY
    4. dòng ADMIN_KEY trong .env ở gốc repo (.env nằm trong .gitignore, không commit)

Script LUÔN in ra nguồn nào được dùng. Trên Windows, biến môi trường mức user che
mất .env — không in nguồn thì không ai phát hiện mình đang bắn nhầm khoá.

Khoá trong .env là khoá LOCAL. Khoá của môi trường chung nằm ở trang Environment
của service trên Render, không nằm trong repo.

    SR_HOST        mặc định https://p-156-staging.onrender.com
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_HOST = "https://p-156-staging.onrender.com"
_REPO_ROOT = Path(__file__).resolve().parents[3]


def resolve_admin_key(explicit: str) -> tuple[str, str]:
    """Trả (khoá, tên nguồn). Khoá rỗng nghĩa là không tìm thấy ở đâu cả."""
    if explicit:
        return explicit, "--admin-key"

    for name in ("SR_ADMIN_KEY", "ADMIN_KEY"):
        value = os.getenv(name, "").strip()
        if value:
            return value, f"biến môi trường {name}"

    env_path = _REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("ADMIN_KEY="):
                value = line.split("=", 1)[1].strip().strip("\"'")
                if value:
                    return value, f"{env_path} (khoá LOCAL — kiểm lại có đúng môi trường đang bắn không)"
    return "", ""


# Render tắt máy khi rảnh; lần gọi đầu phải chờ nó khởi động lại (đo được 18-45s,
# có lần hơn 60s vì cơ sở dữ liệu cũng nguội). 60s là quá chặt.
_TIMEOUT_S = 150
# DNS ở mạng nhà hay chập chờn -> thử lại vài lần trước khi bỏ cuộc.
_ATTEMPTS = 3
_RETRY_WAIT_S = 3


def _request(method: str, host: str, path: str, admin_key: str, body: dict | None = None) -> tuple[int, dict | str]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    last_error = ""

    for attempt in range(1, _ATTEMPTS + 1):
        # Phải xoá mỗi vòng: lần trước timeout mà lần này server trả 401 thì
        # `last_error` cũ còn sót sẽ nuốt mất câu trả lời thật.
        last_error = ""
        req = urllib.request.Request(host.rstrip("/") + path, data=data, method=method)
        req.add_header("X-Admin-Key", admin_key)
        if data:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                raw = resp.read().decode("utf-8")
                status = resp.status
        except urllib.error.HTTPError as exc:
            # Lỗi 4xx/5xx là câu trả lời thật của server, không phải trục trặc mạng.
            raw = exc.read().decode("utf-8", errors="replace")
            status = exc.code
        except urllib.error.URLError as exc:
            last_error = f"không kết nối được: {exc.reason}"
        except TimeoutError:
            # urllib ném thẳng TimeoutError, KHÔNG bọc trong URLError -> nhánh trên
            # không bắt được và script vỡ ra traceback.
            last_error = f"hết {_TIMEOUT_S}s chờ phản hồi (máy chủ có thể đang khởi động lại)"
        except OSError as exc:
            last_error = f"lỗi mạng: {exc}"
        else:
            try:
                return status, json.loads(raw)
            except json.JSONDecodeError:
                return status, raw

        if not last_error:
            try:
                return status, json.loads(raw)
            except json.JSONDecodeError:
                return status, raw

        if attempt < _ATTEMPTS:
            print(f"  lần {attempt}/{_ATTEMPTS} hỏng ({last_error}) — thử lại sau {_RETRY_WAIT_S}s...")
            time.sleep(_RETRY_WAIT_S)

    return 0, last_error


def cmd_preflight(args) -> int:
    host, admin = args.host, args.admin_key
    ok = True

    for path in ("/healthz", "/readyz"):
        status, payload = _request("GET", host, path, admin)
        print(f"{path}: HTTP {status} {json.dumps(payload, ensure_ascii=False)[:200]}")
        ok = ok and status == 200

    status, payload = _request("GET", host, "/admin/keys", admin)
    if status != 200:
        print(f"/admin/keys: HTTP {status} — admin key sai hoặc ADMIN_KEY chưa cấu hình trên server.")
        return 1
    items = payload.get("items", []) if isinstance(payload, dict) else []
    print(f"/admin/keys: HTTP 200 — {len(items)} key đang có")
    for item in items:
        print(f"  id={item['id']} name={item['name']!r} rpm={item['rate_limit_per_min']} active={item['active']}")

    status, payload = _request("GET", host, "/admin/usage/quota", admin)
    if status == 200 and isinstance(payload, dict):
        print(f"/admin/usage/quota ({payload.get('date')}):")
        for q in payload.get("quotas", []):
            print(
                f"  {q['group']}: đã dùng {q['used_tokens']:,}/{q['limit_tokens']:,} "
                f"({q['used_pct']}%) — còn {q['remaining_tokens']:,}"
            )
    else:
        print(f"/admin/usage/quota: HTTP {status}")

    print()
    print("LƯU Ý trước khi chạy tải:")
    print("  * DAILY_TOKEN_BUDGET (mặc định 50.000 token/ngày/key) áp cho MỌI key tạo qua admin API,")
    print("    không đặt được riêng từng key. Vượt -> 429 code=daily_token_budget_exceeded.")
    print("    Đo trên corpus thật: trung bình 140 token/request -> chạm trần sau ~358 request.")
    print("    Kịch bản nghiệm thu đầy đủ cần ~4.200 request (~586k token) -> vỡ ở phút thứ 12.")
    print("    Cách thoát, chọn một: đặt DAILY_TOKEN_BUDGET=0 trên Render để tắt hẳn trần này,")
    print("    hoặc chạy các chặng 1-2 user bằng GATEWAY_DEV_KEY (trần token không áp cho dev key).")
    print("  * Đặt --rpm cao hơn tải dự kiến ít nhất 2 lần để rate limiter không thành nút thắt giả.")
    return 0 if ok else 1


def cmd_create(args) -> int:
    """Tạo một hoặc nhiều key.

    Nhiều key vì trần rpm VÀ trần token/ngày đều tính theo từng api_key_id: 5 key =
    5 lần hạn mức, đủ chạy 5 user ở nhịp đầy đủ mà không phải sửa cấu hình Render.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    base = args.name or f"loadtest-{stamp}"
    created: list[tuple[int, str]] = []

    for index in range(1, args.count + 1):
        name = base if args.count == 1 else f"{base}-{index:02d}"
        status, payload = _request(
            "POST", args.host, "/admin/keys", args.admin_key,
            {"name": name, "rate_limit_per_min": args.rpm},
        )
        if status != 201:
            print(f"Tạo key {name} thất bại: HTTP {status} {payload}")
            if created:
                print("Đã tạo trước đó, nhớ thu hồi:", ", ".join(str(i) for i, _ in created))
            return 1
        created.append((payload["id"], payload["key"]))
        print(f"id={payload['id']} name={payload['name']} rpm={payload['rate_limit_per_min']}")

    keys = ",".join(k for _, k in created)
    print()
    print("KEY (chỉ hiện một lần, lưu lại ngay):")
    print("PowerShell:  $env:SR_API_KEY = \"" + keys + "\"")
    print("bash:        export SR_API_KEY='" + keys + "'")
    print()
    ids = " ".join(str(i) for i, _ in created)
    print(f"Thu hồi sau khi đo:  python loadkey.py revoke --id {ids.replace(' ', ' --id ')}")
    if args.count > 1:
        print(f"Tổng hạn mức: {args.rpm * args.count} request/phút, {50000 * args.count:,} token/ngày.")
    return 0


def cmd_revoke(args) -> int:
    failed = 0
    for key_id in args.id:
        status, payload = _request("DELETE", args.host, f"/admin/keys/{key_id}", args.admin_key)
        print(f"id={key_id}: HTTP {status} {payload}")
        failed += status != 200
    return 1 if failed else 0


def cmd_stats(args) -> int:
    now = datetime.now(UTC)
    since = now - timedelta(minutes=args.minutes)
    path = f"/admin/stats?from={since.strftime('%Y-%m-%dT%H:%M:%S')}&to={now.strftime('%Y-%m-%dT%H:%M:%S')}"
    status, payload = _request("GET", args.host, path, args.admin_key)
    if status != 200:
        print(f"HTTP {status} {payload}")
        return 1
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"\nĐã ghi {args.out}")
    return 0


_NO_KEY_HELP = (
    "Không tìm thấy khoá quản trị. Thứ tự tìm: --admin-key, SR_ADMIN_KEY, ADMIN_KEY, "
    "rồi dòng ADMIN_KEY trong .env ở gốc repo. "
    "Khoá của môi trường chung lấy từ trang Environment của service trên Render."
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=os.getenv("SR_HOST", DEFAULT_HOST))
    parser.add_argument("--admin-key", default="")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight").set_defaults(func=cmd_preflight)

    p_create = sub.add_parser("create")
    p_create.add_argument("--rpm", type=int, default=600)
    p_create.add_argument("--count", type=int, default=1, help="Số key cần tạo (mỗi user ảo một key).")
    p_create.add_argument("--name", default="")
    p_create.set_defaults(func=cmd_create)

    p_revoke = sub.add_parser("revoke")
    p_revoke.add_argument("--id", type=int, required=True, action="append", help="Lặp lại cờ này cho nhiều key.")
    p_revoke.set_defaults(func=cmd_revoke)

    p_stats = sub.add_parser("stats")
    p_stats.add_argument("--minutes", type=int, default=60)
    p_stats.add_argument("--out", default="")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.admin_key, source = resolve_admin_key(args.admin_key)
    if not args.admin_key:
        print(_NO_KEY_HELP, file=sys.stderr)
        return 2

    masked = args.admin_key[:3] + "*" * 4 + args.admin_key[-3:] if len(args.admin_key) > 8 else "*" * 8
    print(f"[loadkey] host={args.host}  khoá={masked}  nguồn={source}")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
