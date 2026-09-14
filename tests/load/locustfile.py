"""Locust load harness cho SmartRoute Gateway.

Bắn tải vào `POST /v1/chat/completions` bằng chính bộ dữ liệu đã gán nhãn của
team (`prompts.py` nạp `mixed_200.jsonl` và `multiturn_30.jsonl`), đo riêng độ trễ
router, và ghi lại BẰNG CHỨNG của mọi response không phải 2xx.

Hai loại người dùng ảo chạy song song:
  * `ChatUser`    — câu hỏi một lượt, không session.
  * `SessionUser` — hội thoại 2–4 lượt, cùng một `session_id`, mang theo toàn bộ
    lịch sử. Đây mới là đường đi qua SessionRouter: mỗi lượt đọc + ghi
    `routing_state` trong cơ sở dữ liệu, tức đường tốn kém nhất khi có tải.

Vì sao có phần diagnostics: lần benchmark 2026-08-27
(`docs/benchmarks/staging-load-20260827/README.md`) dừng giữa chừng vì một loạt
429 mà không ai biết 429 đó đến từ đâu — client rate limiter (`rate_limit_exceeded`)
hay daily token budget (`daily_token_budget_exceeded`). Hai mã lỗi đó nằm ở hai chỗ
khác nhau trong code và cách xử lý ngược nhau. Harness này ghi `error.code`,
`Retry-After` và `X-SR-Request-Id` của các lỗi đầu tiên.

Metric phát ra:
  * `POST /v1/chat/completions`             — câu một lượt, độ trễ HTTP đầu-cuối.
  * `POST /v1/chat/completions (session)`   — từng lượt trong hội thoại nhiều lượt.
    Tên chỉ số phải THUẦN ASCII: Locust ghi CSV bằng bảng mã mặc định của hệ điều
    hành, dấu tiếng Việt làm greenlet ghi CSV chết và mất sạch file kết quả.
  * `ROUTER routing decision`               — `smartroute.latency_router_ms` từ body,
    giữ đúng tên của lần benchmark trước để hai lần chạy so được với nhau.

Xem `tests/load/README.md` để biết cách chạy.
"""

from __future__ import annotations

import itertools
import json
import random
import sys
import time
import uuid
from pathlib import Path

import gevent
from locust import HttpUser, LoadTestShape, constant_throughput, events, task

# Locust nạp file này theo đường dẫn, không qua package -> `tests.load` không nằm
# trên sys.path. Thêm thư mục hiện tại để `import prompts` chạy ở mọi cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Console Windows mặc định cp1252: print chuỗi tiếng Việt là UnicodeEncodeError
# ngay trong event handler, chết trước khi bắn ra được request nào.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):  # stream đã bị thay thế / không đổi được
        pass

from prompts import (  # noqa: E402
    describe,
    load_conversations,
    load_single_turn,
    resample_to_prd_mix,
)

# --- Tham số dòng lệnh -------------------------------------------------------


@events.init_command_line_parser.add_listener
def _add_arguments(parser):
    parser.add_argument(
        "--sr-api-key",
        env_var="SR_API_KEY",
        default="",
        help=(
            "Gateway key gửi ở header Authorization: Bearer. Nhiều khoá thì ngăn cách bằng "
            "dấu phẩy — mỗi user ảo nhận một khoá xoay vòng. Cả trần rpm lẫn trần token/ngày "
            "đều tính theo TỪNG khoá, nên N khoá = N lần hạn mức."
        ),
    )
    parser.add_argument(
        "--sr-classifier",
        env_var="SR_CLASSIFIER",
        default="",
        choices=["", "v1.5", "v2"],
        help="Ép classifier_version. Rỗng = dùng mặc định của server (heuristic v1).",
    )
    parser.add_argument(
        "--sr-policy",
        env_var="SR_POLICY",
        default="balanced",
        choices=["cost_first", "balanced", "quality_first"],
        help="Policy gửi kèm mỗi request.",
    )
    parser.add_argument(
        "--sr-mix",
        env_var="SR_MIX",
        default="dataset",
        choices=["dataset", "prd"],
        help="'dataset' = phân bố thật của mixed_200 (46/65/89); 'prd' = ép về 40/35/25.",
    )
    parser.add_argument(
        "--sr-abort-error-rate",
        env_var="SR_ABORT_ERROR_RATE",
        type=float,
        default=0.10,
        help="Tự dừng khi tỉ lệ lỗi vượt ngưỡng này (0 = tắt). Chốt an toàn cho môi trường chung.",
    )
    parser.add_argument(
        "--sr-abort-min-requests",
        env_var="SR_ABORT_MIN_REQUESTS",
        type=int,
        default=50,
        help="Chỉ xét ngưỡng dừng sau khi đã có bấy nhiêu request (tránh dừng vì 1 lỗi lúc khởi động).",
    )
    parser.add_argument(
        "--sr-diag-file",
        env_var="SR_DIAG_FILE",
        default="",
        help="Đường dẫn JSONL ghi chi tiết lỗi. Rỗng = chỉ in ra stdout.",
    )
    parser.add_argument(
        "--sr-diag-limit",
        env_var="SR_DIAG_LIMIT",
        type=int,
        default=50,
        help="Số lỗi tối đa ghi chi tiết (tránh phình file khi hỏng hàng loạt).",
    )
    parser.add_argument(
        "--sr-shape",
        env_var="SR_SHAPE",
        default="",
        choices=["", "acceptance", "ramp"],
        help=(
            "'acceptance' = 4 chặng 1/1/3/5 user (kiểm 'có đổ không'). "
            "'ramp' = tăng dần tới khi gãy (đo 'chịu được bao nhiêu'). Rỗng = dùng -u/-r."
        ),
    )
    parser.add_argument(
        "--sr-ramp-step",
        env_var="SR_RAMP_STEP",
        type=int,
        default=2,
        help="Chế độ ramp: cộng thêm bấy nhiêu user mỗi bậc.",
    )
    parser.add_argument(
        "--sr-ramp-hold",
        env_var="SR_RAMP_HOLD",
        type=int,
        default=60,
        help="Chế độ ramp: giữ mỗi bậc bấy nhiêu giây trước khi tăng tiếp.",
    )
    parser.add_argument(
        "--sr-ramp-max",
        env_var="SR_RAMP_MAX",
        type=int,
        default=40,
        help="Chế độ ramp: trần số user, dừng khi chạm (chốt an toàn cứng).",
    )
    parser.add_argument(
        "--sr-session-pct",
        env_var="SR_SESSION_PCT",
        type=int,
        default=60,
        help=(
            "Phần trăm user ảo chạy hội thoại nhiều lượt (còn lại hỏi câu lẻ). "
            "Mặc định 60 vì đây là sản phẩm trợ lý hội thoại — người dùng thật hiếm khi "
            "hỏi đúng một câu rồi thôi, và hội thoại là đường tốn kém nhất (đọc/ghi "
            "routing_state mỗi lượt)."
        ),
    )
    parser.add_argument(
        "--sr-throughput",
        env_var="SR_THROUGHPUT",
        type=float,
        default=0.5,
        help="Số request mỗi giây trên mỗi user.",
    )


# --- Trạng thái dùng chung ---------------------------------------------------


class _Diagnostics:
    """Gom bằng chứng lỗi. Một tiến trình Locust = một instance."""

    def __init__(self) -> None:
        self.records: list[dict] = []
        self.path: Path | None = None
        self.limit = 50
        self.by_code: dict[str, int] = {}

    def configure(self, path: str, limit: int) -> None:
        self.limit = limit
        if path:
            self.path = Path(path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def record(self, response, **context) -> str:
        code = error_code(response)
        self.by_code[code] = self.by_code.get(code, 0) + 1
        if len(self.records) >= self.limit:
            return code

        rec = {
            "ts": time.time(),
            "status": response.status_code,
            "error_code": code,
            "retry_after": response.headers.get("Retry-After"),
            "request_id": response.headers.get("X-SR-Request-Id"),
            "tier": response.headers.get("X-SR-Tier"),
            "model": response.headers.get("X-SR-Model"),
            "body": response.text[:800],
            **context,
        }
        self.records.append(rec)
        if self.path:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if len(self.records) <= 3:
            print(f"[load] LỖI ĐẦU TIÊN #{len(self.records)}: {json.dumps(rec, ensure_ascii=False)}", flush=True)
        return code


def error_code(response) -> str:
    """Mã lỗi trong error envelope; fallback về status khi body không phải envelope.

    502/504 của Render trả HTML chứ không phải envelope — nhánh except là đường đi
    thật, không phải phòng hờ.
    """
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return f"http_{response.status_code}"
    if not isinstance(payload, dict):
        return f"http_{response.status_code}"
    code = (payload.get("error") or {}).get("code")
    return code or f"http_{response.status_code}"


DIAG = _Diagnostics()
TIER_COUNTS: dict[str, int] = {}
ROUTER_FALLBACKS = {"count": 0}
# Tín hiệu tỉnh táo, KHÔNG phải eval: eval thật chạy ở `src/evals/`. Ở đây chỉ để
# phát hiện "định tuyến đổi hành vi khi có tải" — một kiểu hỏng khác hẳn chậm/lỗi.
TIER_MATCH = {"match": 0, "total": 0}
CONVERSATIONS_DONE = {"complete": 0, "aborted": 0}

_PROMPTS: list = []
_CONVERSATIONS: list = []
# Trần rpm (middleware) và trần token/ngày (quota) đều khoá theo api_key_id, nên phát
# mỗi user ảo một khoá là nhân hạn mức lên đúng bấy nhiêu lần — cách duy nhất chạm mức
# 5 user mà không phải đổi cấu hình môi trường chung.
_API_KEYS: list[str] = [""]
_KEY_CURSOR = itertools.count()
# Số lượt trung bình mỗi hội thoại trong multiturn_30.jsonl (49 lượt / 18 hội thoại).
_AVG_TURNS = 2.7


@events.init.add_listener
def _on_init(environment, **_kwargs):
    global _PROMPTS, _CONVERSATIONS
    opts = environment.parsed_options
    DIAG.configure(opts.sr_diag_file, opts.sr_diag_limit)

    _PROMPTS = load_single_turn()
    if opts.sr_mix == "prd":
        _PROMPTS = resample_to_prd_mix(_PROMPTS)
    _CONVERSATIONS = load_conversations()
    print(f"[load] corpus: {describe(_PROMPTS, _CONVERSATIONS)}", flush=True)

    # Gán vào LỚP, không phải instance — xem chú thích ở ChatUser.wait_time.
    ChatUser.wait_time = constant_throughput(opts.sr_throughput)
    SessionUser.wait_time = constant_throughput(opts.sr_throughput / _AVG_TURNS)

    # Trọng số quyết định tỉ lệ user ảo mỗi loại. Vì nhịp của SessionUser đã chia cho
    # số lượt trung bình, mỗi user của cả hai loại đều sinh ~sr_throughput request/giây
    # -> trọng số ánh xạ thẳng sang tỉ lệ REQUEST, không chỉ tỉ lệ user.
    session_pct = max(0, min(100, opts.sr_session_pct))
    SessionUser.weight = session_pct
    ChatUser.weight = 100 - session_pct
    print(f"[load] tỉ lệ: {100 - session_pct}% câu lẻ / {session_pct}% hội thoại", flush=True)

    global _API_KEYS
    _API_KEYS = [k.strip() for k in opts.sr_api_key.split(",") if k.strip()] or [""]
    if _API_KEYS == [""]:
        print("[load] CẢNH BÁO: chưa có --sr-api-key. Staging đặt API_AUTH_REQUIRED=true nên sẽ 401 toàn bộ.")
    elif len(_API_KEYS) > 1:
        print(f"[load] {len(_API_KEYS)} khoá, phát xoay vòng cho từng user — hạn mức nhân {len(_API_KEYS)} lần.", flush=True)


@events.request.add_listener
def _abort_on_error_rate(request_type, response_time, exception, context, **_kwargs):
    """Chốt an toàn: vượt ngưỡng lỗi thì dừng, không đốt tiếp môi trường chung.

    Chỉ đếm request HTTP; metric ROUTER là số phái sinh, tính vào sẽ pha loãng tỉ lệ.
    """
    env = (context or {}).get("environment")
    if env is None or request_type == "ROUTER":
        return
    opts = env.parsed_options
    if not opts.sr_abort_error_rate:
        return
    stats = env.stats.total
    if stats.num_requests < opts.sr_abort_min_requests:
        return
    if stats.fail_ratio > opts.sr_abort_error_rate:
        print(
            f"[load] DỪNG AN TOÀN: tỉ lệ lỗi {stats.fail_ratio:.2%} vượt ngưỡng "
            f"{opts.sr_abort_error_rate:.2%} sau {stats.num_requests} request "
            f"(đang ở {env.runner.user_count} user).",
            flush=True,
        )
        env.runner.quit()


@events.quitting.add_listener
def _on_quitting(environment, **_kwargs):
    print("\n[load] ---- Tổng kết định tuyến ----")
    total_tiers = sum(TIER_COUNTS.values())
    for tier in ("T1", "T2", "T3"):
        n = TIER_COUNTS.get(tier, 0)
        pct = (n / total_tiers * 100) if total_tiers else 0.0
        print(f"[load] {tier}: {n} ({pct:.1f}%)")
    print(f"[load] request có fallback: {ROUTER_FALLBACKS['count']}")

    if TIER_MATCH["total"]:
        pct = TIER_MATCH["match"] / TIER_MATCH["total"] * 100
        print(
            f"[load] tier khớp nhãn kỳ vọng: {TIER_MATCH['match']}/{TIER_MATCH['total']} ({pct:.1f}%)"
            " — tín hiệu tỉnh táo, KHÔNG phải kết quả eval"
        )
    print(
        f"[load] hội thoại: {CONVERSATIONS_DONE['complete']} trọn vẹn, "
        f"{CONVERSATIONS_DONE['aborted']} bỏ dở vì lỗi"
    )

    if DIAG.by_code:
        print("[load] ---- Lỗi theo mã ----")
        for code, n in sorted(DIAG.by_code.items(), key=lambda kv: -kv[1]):
            print(f"[load] {code}: {n}")
        if DIAG.path:
            print(f"[load] chi tiết: {DIAG.path}")
    else:
        print("[load] không có lỗi HTTP nào.")


# --- Phần dùng chung giữa hai loại user --------------------------------------


class _GatewayMixin:
    """Header, gửi request, và bóc metric từ body — chung cho cả hai loại user."""

    def on_start(self):
        opts = self.environment.parsed_options
        self._api_key = _API_KEYS[next(_KEY_CURSOR) % len(_API_KEYS)]
        self.client.headers.update(
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            }
        )
        self._policy = opts.sr_policy
        self._classifier = opts.sr_classifier

    def _smartroute_options(self, session_id: str | None = None) -> dict:
        options: dict = {"policy": self._policy}
        if self._classifier:
            options["classifier_version"] = self._classifier
        if session_id:
            options["session_id"] = session_id
        return options

    def _send(self, messages: list[dict], name: str, smartroute: dict, **diag_context):
        """Gửi một lượt. Trả (body, None) khi thành công, (None, mã lỗi) khi hỏng."""
        payload = {
            "model": "auto",
            "messages": messages,
            "stream": False,
            "smartroute": smartroute,
        }
        with self.client.post(
            "/v1/chat/completions",
            json=payload,
            name=name,
            catch_response=True,
            context={"environment": self.environment},
        ) as response:
            if response.status_code != 200:
                code = DIAG.record(response, **diag_context)
                response.failure(f"HTTP {response.status_code} ({code})")
                return None, code
            try:
                body = response.json()
                meta = body["smartroute"]
            except Exception as exc:  # noqa: BLE001
                response.failure(f"body 200 nhưng không đọc được smartroute: {exc}")
                return None, "bad_body"
            response.success()
            self._record_routing(meta)
            return body, None

    def _record_routing(self, meta: dict) -> None:
        tier = meta.get("tier_effective") or meta.get("tier")
        if tier:
            TIER_COUNTS[tier] = TIER_COUNTS.get(tier, 0) + 1
        if meta.get("fallback_count"):
            ROUTER_FALLBACKS["count"] += 1

        router_ms = meta.get("latency_router_ms")
        if router_ms is None:
            return
        self.environment.events.request.fire(
            request_type="ROUTER",
            name="routing decision",
            response_time=router_ms,
            response_length=0,
            exception=None,
            context={"environment": self.environment},
        )

    @staticmethod
    def _note_expected_tier(meta: dict, expected_tier: str) -> None:
        if not expected_tier:
            return
        TIER_MATCH["total"] += 1
        actual = meta.get("tier_effective") or meta.get("tier")
        if actual == expected_tier:
            TIER_MATCH["match"] += 1


# --- User: câu hỏi một lượt --------------------------------------------------


class ChatUser(_GatewayMixin, HttpUser):
    """Người dùng hỏi một câu rồi thôi — không session, không lịch sử."""

    weight = 7
    # wait_time gán ở _on_init: constant_throughput trả hàm nhận `self`, gán vào
    # INSTANCE thì không bind, gọi ra là TypeError và greenlet chết ngay sau lượt đầu.
    # Phải gán vào LỚP mới thành method.
    wait_time = constant_throughput(0.5)

    @task
    def chat(self):
        prompt = random.choice(_PROMPTS)
        body, _err = self._send(
            [{"role": "user", "content": prompt.text}],
            name="/v1/chat/completions",
            smartroute=self._smartroute_options(),
            prompt_id=prompt.id,
            difficulty=prompt.difficulty,
        )
        if body:
            self._note_expected_tier(body["smartroute"], prompt.expected_tier)


# --- User: hội thoại nhiều lượt ----------------------------------------------


class SessionUser(_GatewayMixin, HttpUser):
    """Người dùng hội thoại 2–4 lượt trên cùng một session_id.

    Đây là đường đi thật của SessionRouter: mỗi lượt đọc `routing_state` từ cơ sở
    dữ liệu, tính EMA/hysteresis/failure-boost, rồi ghi lại. Đo tải mà chỉ bắn câu
    lẻ là bỏ qua đúng phần tốn kém nhất.

    `session_id` là UUID sinh tại chỗ — gateway tự tạo bản ghi session ở lượt đầu,
    không cần gọi `POST /v1/sessions` trước.
    """

    weight = 60  # ghi đè ở _on_init theo --sr-session-pct
    # Một "task" ở đây là CẢ hội thoại (2–4 request), nên nhịp chia cho số lượt trung
    # bình để tổng request/giây/user khớp ChatUser. Gán lại ở _on_init theo --sr-throughput.
    wait_time = constant_throughput(0.5 / _AVG_TURNS)

    @task
    def conversation(self):
        conv = random.choice(_CONVERSATIONS)
        session_id = str(uuid.uuid4())
        messages: list[dict] = []

        for index, (text, expected_tier) in enumerate(conv.turns, start=1):
            messages.append({"role": "user", "content": text})
            body, _err = self._send(
                messages,
                name="/v1/chat/completions (session)",
                smartroute=self._smartroute_options(session_id=session_id),
                conversation_id=conv.id,
                scenario=conv.scenario,
                turn=index,
            )
            if body is None:
                # Lượt hỏng thì lịch sử không còn hợp lệ — bỏ cả hội thoại, đếm riêng.
                CONVERSATIONS_DONE["aborted"] += 1
                return

            self._note_expected_tier(body["smartroute"], expected_tier)
            messages.append(
                {"role": "assistant", "content": body["choices"][0]["message"]["content"]}
            )

            if index < len(conv.turns):
                # Thời gian người thật đọc câu trả lời rồi mới gõ tiếp.
                gevent.sleep(random.uniform(1.0, 3.0))

        CONVERSATIONS_DONE["complete"] += 1


# --- Hình dạng tải -----------------------------------------------------------


class GatewayShape(LoadTestShape):
    """Hai kịch bản, chọn bằng `--sr-shape`.

    Locust ưu tiên LoadTestShape hơn `-u/-r/-t` ngay khi file có một lớp shape, nên
    lớp này phải tự trả lại quyền cho các cờ đó khi không chọn kịch bản nào —
    `use_common_options = True` cho phép đọc `parsed_options.num_users`/`spawn_rate`.
    """

    use_common_options = True

    # (giây tích luỹ, số user, tên chặng) — kiểm "có đổ không" ở mức tải bản demo.
    acceptance_stages = (
        (5 * 60, 1, "warmup_users_1"),
        (20 * 60, 1, "baseline_users_1"),
        (35 * 60, 3, "required_users_3"),
        (50 * 60, 5, "prd_max_users_5"),
    )

    def __init__(self):
        super().__init__()
        self._announced: str | None = None

    def tick(self):
        opts = getattr(self.runner.environment, "parsed_options", None)
        shape = getattr(opts, "sr_shape", "")
        run_time = self.get_run_time()

        if shape == "acceptance":
            return self._acceptance(run_time)
        if shape == "ramp":
            return self._ramp(run_time, opts)

        limit = getattr(opts, "run_time", None)
        if limit and run_time > limit:
            return None
        return getattr(opts, "num_users", None) or 1, getattr(opts, "spawn_rate", None) or 1

    def _acceptance(self, run_time: float):
        for end_s, users, label in self.acceptance_stages:
            if run_time < end_s:
                self._announce(f"chặng {label}: {users} user")
                return users, users
        return None

    def _ramp(self, run_time: float, opts):
        """Tăng dần cho tới khi gãy.

        Không có điều kiện "đã gãy" ở đây: cái dừng thật là `--sr-abort-error-rate`
        trong `_abort_on_error_rate`, vì nó nhìn tỉ lệ lỗi thật chứ không đoán theo
        thời gian. `--sr-ramp-max` chỉ là chốt cứng phòng khi hệ thống không gãy
        trong ngân sách của phép đo.
        """
        step = max(1, opts.sr_ramp_step)
        hold = max(10, opts.sr_ramp_hold)
        ceiling = max(step, opts.sr_ramp_max)

        users = step * (1 + int(run_time // hold))
        if users > ceiling:
            self._announce(f"chạm trần {ceiling} user mà chưa gãy — dừng")
            return None
        self._announce(f"ramp: {users} user")
        return users, step

    def _announce(self, message: str) -> None:
        if self._announced != message:
            self._announced = message
            print(f"[load] ==== {message} ====", flush=True)
