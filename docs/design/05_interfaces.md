# Interface Contracts — SmartRoute Gateway
**Gate 1 · v1.4 · 01/09/2026 · File: `docs/design/05_interfaces.md`**

> **Nguyên tắc contract-first:** ai tích hợp với phần của bạn chỉ cần đọc contract — không cần đọc code. Mọi thay đổi interface phải qua PR sửa file này (label `interface-change`, bump version ở đầu file) và được cả team ack trước khi sửa code.
>
> **Phạm vi sở hữu** (phân quyền source of truth — chi tiết ở đầu `02_prd.md`): file này là nguồn sự thật cho **lớp B, C, D** và các bề mặt HTTP **chưa có OpenAPI** (admin, feedback, keys). Riêng bề mặt HTTP của **Feature F1** (`/v1/chat/completions`, `/v1/models`, `/v1/usage/{id}`, `/healthz`, `/readyz`) do **`v1_f1.yaml`** sở hữu — phần tương ứng trong §A là tóm tắt kèm giải thích, khi lệch nhau thì OpenAPI thắng.

**4 lớp interface trong dự án:**

| Lớp | Giữa ai với ai | Mục | Cho phép làm song song |
|---|---|---|---|
| A | FE (dashboard) ↔ BE (gateway) | HTTP API | FE code bằng mock/fixtures từ ví dụ JSON bên dưới, không đợi BE |
| B | BE ↔ AI-core (cùng codebase) | Abstract class Python | BE viết orchestration với `MockAdapter`/stub classifier; AI-core implement sau |
| C | Dev ↔ DevOps | Env vars, ports, health, image | DevOps dựng compose/CI trước khi code xong |
| D | Admin/AI ↔ Runtime | Schema file config YAML | Chỉnh hành vi routing không sửa code |

(UI/UX — interface người dùng ↔ hệ thống — đã đặc tả ở `03_wireframe_ui_flow.html`; mục A.9 bổ sung bảng ánh xạ màn hình → API.)

---

## A. Interface FE ↔ BE (HTTP API)

### A.0 Quy ước chung
| Hạng mục | Quy ước |
|---|---|
| Base URL | dev: `http://localhost:8000` — FE đọc từ `VITE_API_BASE_URL` |
| Định dạng | JSON, UTF-8, field **snake_case** |
| Thời gian | ISO 8601 UTC, ví dụ `"2026-08-02T13:40:00Z"` |
| Tiền | USD, kiểu number, tối đa 6 chữ số thập phân (DB lưu Decimal) |
| Auth client API (`/v1/*`) | Header `Authorization: Bearer sr-xxxx` (gateway key) |
| Auth admin API (`/admin/*`) | Header `X-Admin-Key: <ADMIN_KEY>` |
| Phân trang | Query `page` (từ 1), `page_size` (mặc định 50, max 200) → response `{items, page, page_size, total}` |
| ID request | UUID v4, trả trong body và header chuẩn `X-Request-Id`; giữ `X-SR-Request-Id` làm alias tương thích ngược |

**Error envelope thống nhất (mọi endpoint, tương thích OpenAI):**
```json
{ "error": { "message": "Mô tả lỗi đọc được", "type": "invalid_request_error", "param": "messages", "code": "missing_messages", "request_id": "uuid", "details": {} } }
```
`type` ∈ `invalid_request_error` (400/422) · `authentication_error` (401) · `not_found_error` (404) · `rate_limit_error` (429) · `provider_error` (502 — mọi provider trong chain đều fail) · `internal_error` (500).

Các `code` chuẩn hóa cho lỗi tương thích (chi tiết kịch bản: PRD §1.5): `unsupported_parameter` · `unsupported_capability` · `context_too_long` · `too_many_messages` · `unknown_model`.

### A.1 `POST /v1/chat/completions` — endpoint chính (FR-01)
**Request:**
```json
{
  "model": "auto",
  "messages": [
    { "role": "system", "content": "Bạn là trợ lý..." },
    { "role": "user", "content": "Viết hàm Python kiểm tra số nguyên tố" }
  ],
  "temperature": 0.7,
  "max_tokens": 1024,
  "stream": false,
  "smartroute": {
    "policy": "balanced",
    "force_model": null,
    "force_tier": null,
    "session_id": null
  }
}
```
| Trường | Kiểu | Bắt buộc | Ghi chú |
|---|---|---|---|
| `model` | string | ✗ (mặc định `"auto"`) | Chỉ là gợi ý; gateway quyết định trừ khi có `force_model` |
| `messages[]` | array | ✔ | `role` ∈ `system\|user\|assistant`; `content` string |
| `temperature` | number 0–2 | ✗ | Pass-through xuống provider |
| `max_tokens` | int | ✗ | Pass-through |
| `stream` | bool | ✗ (false) | true → SSE (A.2) |
| `smartroute.policy` | enum | ✗ | `cost_first \| balanced \| quality_first`; bỏ trống → policy mặc định trong config |
| `smartroute.force_model` | string\|null | ✗ | Bỏ qua classifier, dùng đúng model này (phải có trong `GET /v1/models`) |
| `smartroute.force_tier` | enum\|null | ✗ | `T1\|T2\|T3` — bỏ qua classifier nhưng vẫn qua policy engine |
| `smartroute.session_id` | uuid\|null | ✗ | Gắn request vào session (từ `POST /v1/sessions`); bỏ trống nếu không dùng session |

**Whitelist MVP & giới hạn input** — gateway là *text-only OpenAI-compatible subset* (đặc tả: PRD §1.5):

| Ngoài các trường ở bảng trên, client gửi… | Gateway trả |
|---|---|
| `tools` / `tool_choice`, `response_format`, `n>1`, `logprobs`, `seed`, `content` dạng mảng (ảnh/audio/file parts) | 400 `unsupported_parameter` — message nêu đúng tên trường |
| `stream=true` trước khi mốc M3 hoàn thành | 400 `unsupported_parameter` |
| > `MAX_MESSAGES` (50) messages | 400 `too_many_messages` |
| > `MAX_INPUT_TOKENS` (8.000) tổng input tokens | 400 `context_too_long` |
| Body > 1 MB | 413 |
| `max_tokens` > 8.192 | Clamp về 8.192 + header `X-SR-Clamped: max_tokens` |

Tham số trong whitelist nhưng provider đích không hỗ trợ → adapter **drop** (không fail request) + header `X-SR-Dropped-Params: top_p,stop` + log.

**Response 200 (non-stream):**
```json
{
  "id": "chatcmpl-8f3a...",
  "object": "chat.completion",
  "created": 1785675600,
  "model": "claude-sonnet",
  "choices": [
    { "index": 0,
      "message": { "role": "assistant", "content": "def is_prime(n): ..." },
      "finish_reason": "stop" }
  ],
  "usage": { "prompt_tokens": 42, "completion_tokens": 380, "total_tokens": 422 },
  "smartroute": {
    "request_id": "0b1c2d3e-....",
    "difficulty_score": 72,
    "tier": "T3",
    "signals": [ { "name": "code", "points": 22 }, { "name": "multi_step", "points": 15 } ],
    "policy": "balanced",
    "model_used": "claude-sonnet",
    "provider": "anthropic",
    "cost_usd": 0.00342,
    "router_cost_usd": 0.0,
    "outcome_evidence": null,
    "latency_total_ms": 2400,
    "latency_router_ms": 41,
    "fallback_count": 0
  }
}
```
**Response headers:** `X-SR-Request-Id`, `X-SR-Score`, `X-SR-Tier`, `X-SR-Model`, `X-SR-Provider` (có ngay khi bắt đầu trả); `X-SR-Cost-USD` (chỉ non-stream).
**Lỗi:** 401 sai key · 422 body sai schema (kèm `code` chỉ rõ trường) · 429 vượt rate limit của key · 502 `provider_error` khi toàn bộ chain fail (body kèm `smartroute.chain_attempted`).

### A.1b Ma trận tương thích theo provider
Ma trận này là **một phần contract của adapter**: ✔ = adapter phải hỗ trợ và có test; *drop* = adapter loại tham số + báo `X-SR-Dropped-Params`. Nguồn khai báo trong code: `model_capabilities` (§B.4). Thêm provider mới = thêm 1 cột và cập nhật bảng này trong cùng PR.

| Capability / tham số | google | groq | mock | openai (M2) | anthropic (M2) | ollama (sau) |
|---|---|---|---|---|---|---|
| Text chat + system prompt | ✔ | ✔ | ✔ | ✔ | ✔ (map sang trường `system` riêng — adapter lo) | ✔ |
| `temperature` / `max_tokens` | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| `top_p` | ✔ | ✔ | drop | ✔ | ✔ | ✔ |
| `stop` | ✔ | ✔ | drop | ✔ | ✔ (`stop_sequences`) | tùy model → drop |
| `stream` (bật ở M3) | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| tools / vision / JSON mode | — ngoài MVP: gateway chặn 400 **trước khi** tới adapter (PRD §1.5) | | | | | |

### A.2 Streaming (SSE) — FR-15
- `stream: true` → `Content-Type: text/event-stream`. Mỗi event là chunk **chuẩn OpenAI**, kết thúc bằng `data: [DONE]`:
```
data: {"id":"chatcmpl-8f3a","object":"chat.completion.chunk","created":1785675600,"model":"claude-sonnet","choices":[{"index":0,"delta":{"content":"def"},"finish_reason":null}]}

data: {"id":"chatcmpl-8f3a","object":"chat.completion.chunk","created":1785675600,"model":"claude-sonnet","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

data: [DONE]
```
- **Hợp đồng metadata khi stream:** chunk giữ nguyên format OpenAI để không phá SDK. Routing decision đọc từ **headers** (đã có trước khi stream); `cost_usd`/`latency` chốt sau khi stream xong → FE lấy qua `GET /v1/usage/{request_id}` (A.4). Playground bắt buộc dùng cơ chế này để hiện badge chi phí.

### A.3 `GET /v1/models`
Response 200:
```json
{ "object": "list", "data": [
  { "id": "gemini-flash-lite", "object": "model", "provider": "google", "default_tier": "T1", "capabilities": ["text", "stream"], "enabled": true },
  { "id": "claude-sonnet", "object": "model", "provider": "anthropic", "default_tier": "T3", "capabilities": ["text", "stream"], "enabled": true }
] }
```
`capabilities` lấy từ `model_capabilities` của adapter (§B.4) — FE dùng để ẩn model không phù hợp (vd model không stream khi playground bật chế độ stream). `enabled=false` khi provider thiếu API key hoặc circuit đang OPEN. FE dùng list này cho dropdown Override (Plate 01) và Config (Plate 03).

### A.4 `GET /v1/usage/{request_id}`
Auth: gateway key **đã tạo request đó**. Response 200:
```json
{ "status": "complete", "smartroute": { "...": "đúng object smartroute như A.1" } }
```
- `status="pending"`: bản ghi nền chưa cập nhật xong (hiếm, thường <1s) — các trường `cost_usd`/`latency_*` là `null`; client (Playground) poll tối đa 5 lần × 1s rồi hiển thị "đang tính".
- **Không bao giờ 404 với id đã cấp** — nhờ ghi log 2 pha: bản ghi tối thiểu được insert *đồng bộ trước khi* response trả về (ADR-008, `06_architecture.md`). 404 chỉ khi id không tồn tại hoặc không thuộc key.

### A.5 `POST /v1/feedback` — FR-17
Request `{ "request_id": "uuid", "tags": ["Nên dùng model mạnh hơn", "Chậm"], "note": "câu này cần suy luận nhiều bước" }` (`tags` array string tùy chọn từ tập cố định, `note` ≤ 500 ký tự tùy chọn; ít nhất một trong hai phải có giá trị) → 201 `{ "ok": true }`. 404 nếu `request_id` không tồn tại; 409 nếu đã feedback trước đó.

Tập `tags` cố định cho feedback per-request: `Nên dùng model mạnh hơn` · `Nên dùng model nhỏ hơn` · `Chất lượng kém` · `Chậm` · `Khác`.

### A.5b `POST /v1/sessions`
Tạo session mới để nhóm các request trong cùng một cuộc hội thoại. Playground gọi khi user bắt đầu chat mới.
Request: `{}` (body rỗng). Response 201:
```json
{ "session_id": "a1b2c3d4-...", "started_at": "2026-08-16T10:00:00Z" }
```
`session_id` sau đó truyền vào `smartroute.session_id` của `POST /v1/chat/completions` (A.1).

### A.5c `POST /v1/session-feedback`
Feedback tổng thể cho cả cuộc hội thoại (tối đa một lần/session).
Request:
```json
{ "session_id": "a1b2c3d4-...", "tags": ["Chất lượng kém"], "note": "routing không nhất quán giữa các lượt" }
```
Ràng buộc: ít nhất `tags` hoặc `note` phải có giá trị; `note` ≤ 500 ký tự. Response: 201 `{ "ok": true }`. 404 nếu `session_id` không tồn tại; 409 nếu đã feedback.

Tập `tags` cố định cho session feedback: `Routing tốt, tiết kiệm chi phí` · `Routing không nhất quán` · `Nên dùng model mạnh hơn` · `Nên dùng model nhỏ hơn` · `Khác`. `note` dùng để viết đánh giá/nhận xét tổng quan về cả session.

### A.6 Admin — thống kê & log (FR-05, FR-13)
**`GET /admin/stats?from=2026-08-01T00:00:00Z&to=...`** → nuôi toàn bộ Plate 02:
```json
{
  "from": "2026-08-01T00:00:00Z", "to": "2026-08-08T00:00:00Z",
  "totals": {
    "requests": 1284, "cost_usd": 3.41,
    "router_cost_usd": 0.02, "net_cost_usd": 3.43,
    "baseline_premium_cost_usd": 7.42, "savings_pct": 53.8,
    "avg_latency_ms": 1900, "avg_router_latency_ms": 38, "success_rate": 0.996
  },
  "by_tier": [ { "tier": "T1", "requests": 712, "cost_usd": 0.31 },
               { "tier": "T2", "requests": 391, "cost_usd": 0.86 },
               { "tier": "T3", "requests": 181, "cost_usd": 2.24 } ],
  "by_provider": [ { "provider": "google", "requests": 803, "cost_usd": 0.94 } ],
  "series": [ { "date": "2026-08-01", "requests": 210, "cost_usd": 0.52, "baseline_premium_cost_usd": 1.13 } ]
}
```
`baseline_premium_cost_usd` = tính lại token log theo giá model premium trong `pricing.yaml` (định nghĩa "savings" của cả đề tài — FE chỉ hiển thị, không tự tính). `savings_pct` tính **net** theo `08_adaptive_routing.md` §9.1: `(baseline − net_cost) / baseline`, với `net_cost = cost_usd + router_cost_usd` — chi phí của chính router (classifier v2) cũng là chi phí, nếu không savings là số ảo. `success_rate` tính theo measurement protocol PRD §9.4: denominator là request đã được cấp `request_id`, loại trừ 4xx lỗi phía client; failure = 502/500/`incomplete`.

Mọi endpoint admin nhận `from`/`to` (`/admin/stats`, `/admin/requests`, `/admin/logs`) dùng cùng khoảng nửa mở **`[from, to)`**: `from` bao gồm, `to` loại trừ. Offset ISO-8601 được đổi sang UTC; timestamp không có offset được hiểu là UTC. `from == to` hợp lệ và trả tập rỗng. `from > to` trả 400 với `code: invalid_time_range` và `details.fields: ["from", "to"]`. KPI/breakdown/chart đếm mọi request trong khoảng; chi phí, token và baseline chỉ tính request `status=ok`.

**`GET /admin/requests`** — filter: `page, page_size, from, to, tier, provider, status (ok|error), min_fallback, q (request_id)`. Item:
```json
{ "id": "0b1c...", "ts": "2026-08-02T14:01:47Z", "api_key_name": "app-web",
  "difficulty_score": 72, "tier": "T3", "policy": "balanced",
  "model": "claude-sonnet", "provider": "anthropic",
  "prompt_tokens": 42, "completion_tokens": 380, "cost_usd": 0.00342,
  "latency_total_ms": 2400, "latency_router_ms": 41,
  "fallback_count": 0, "status": "ok", "stream": false }
```
**`GET /admin/requests/{id}`** — item trên **+**:
```json
{ "signals": [ { "name": "code", "points": 22 } ],
  "chain_attempted": [ { "model": "claude-sonnet", "provider": "anthropic", "status": "ok", "error": null } ],
  "classifier_version": "heuristic-v1",
  "error": null,
  "prompt_preview": null, "response_preview": null }
```
(`*_preview` chỉ khác null khi `LOG_CONTENT=true`, cắt 500 ký tự.)

### A.7 Admin — config (FR-14)
**`GET /admin/config`** / **`PUT /admin/config`** (cùng schema, PUT validate rồi áp dụng nóng):
```json
{
  "tier_thresholds": { "t1_max": 30, "t2_max": 60 },
  "default_policy": "balanced",
  "tiers": {
    "T1": { "primary": { "model": "gemini-flash-lite", "provider": "google" },
            "fallbacks": [ { "model": "gpt-mini", "provider": "openai" } ] },
    "T2": { "primary": { "model": "gpt-mini", "provider": "openai" }, "fallbacks": [] },
    "T3": { "primary": { "model": "claude-sonnet", "provider": "anthropic" }, "fallbacks": [] }
  }
}
```
Ràng buộc PUT: `0 < t1_max < t2_max < 100`; mọi model phải tồn tại & `enabled`. Sai → 422 với danh sách `{path, message}`. Thành công → 200 `{ "ok": true, "applied_at": "..." }`.

### A.8 Admin — keys (FR-16) & health
- `GET /admin/keys` → `{ "items": [ { "id": 1, "name": "app-web", "key_masked": "sr-****9f2c", "rate_limit_per_min": 60, "created_at": "...", "active": true } ] }`
- `POST /admin/keys` req `{ "name": "app-web", "rate_limit_per_min": 60 }` → 201 `{ "id", "name", "key": "sr-<hiện đầy đủ duy nhất 1 lần>", ... }`
- Tên key được trim trước khi validate, phải còn 1–255 ký tự và là duy nhất không phân biệt hoa/thường (`Production` và `production` xung đột). Cách viết hoa/thường ban đầu vẫn được lưu để hiển thị.
- `rate_limit_per_min` phải nằm trong khoảng `1..1000`; mức trần 1.000 RPM giới hạn bộ nhớ/CPU của rate limiter trong khi vẫn hỗ trợ lưu lượng gateway cao.
- Tên trùng trả `409` với `code: duplicate_api_key_name`, `details.field: name`; tên hoặc RPM không hợp lệ trả `422 validation_error` với trường lỗi trong `details.loc`.
- `DELETE /admin/keys/{id}` → 200 `{ "ok": true }` (thu hồi = `active:false`)
- `GET /healthz` (không auth, liveness — luôn 200 nếu process sống):
```json
{ "status": "degraded", "version": "0.1.0", "db": "ok",
  "providers": [ { "provider": "openai", "status": "unhealthy", "configured": true, "available": false,
                   "circuit": "open", "consecutive_errors": 7, "open_until": "2026-08-02T14:12:00Z" },
                 { "provider": "google", "status": "available", "configured": true, "available": true,
                   "circuit": "closed", "consecutive_errors": 0, "open_until": null } ] }
```
- Provider `status`: `available` khi probe và circuit đều tốt; `disabled` khi thiếu runtime adapter/credential; `unavailable` khi probe thất bại; `unhealthy` khi circuit không đóng. Không trường nào chứa credential.
- `/v1/models`, `/healthz` và `/readyz` dùng chung snapshot runtime cache. Model chỉ có `enabled:true` khi provider probe thành công và circuit của model không OPEN.
- `GET /readyz` — 200 khi DB + config tốt và còn ít nhất một model khả dụng (`checks.providers` là `ok` hoặc `degraded`); 503 khi toàn bộ provider/model không khả dụng (`checks.providers: unavailable`).

### A.9 Ánh xạ màn hình → API (nối wireframe với contract)
| Màn hình (Plate) | Endpoint sử dụng |
|---|---|
| 01 Playground | `POST /v1/chat/completions` (+SSE), `GET /v1/models`, `GET /v1/usage/{id}`, `POST /v1/sessions`, `POST /v1/feedback`, `POST /v1/session-feedback` |
| 02 Dashboard | `GET /admin/stats` |
| 03 Config | `GET/PUT /admin/config`, `GET /v1/models` |
| 04 Logs | `GET /admin/requests`, `GET /admin/requests/{id}` |
| 05 Settings | `GET/POST/DELETE /admin/keys`, `GET /healthz` |

**Mock cho FE:** copy nguyên các JSON ví dụ ở trên làm fixtures (MSW/json-server). BE bật `USE_MOCK_PROVIDERS=true` là FE gọi API thật với response giả lập — hai đường đều không phụ thuộc BE viết xong logic.

---

## B. Interface BE ↔ AI-core (abstract class trong codebase)

> BE (orchestration, API layer) **không cần biết** classifier/adapter làm gì bên trong — chỉ gọi đúng chữ ký dưới đây. AI-core được đổi thuật toán thoải mái miễn giữ nguyên contract. File: `gateway/app/core/interfaces.py` (dataclass + ABC, copy nguyên khối này làm code khởi tạo).

### B.1 Kiểu dữ liệu chung
```python
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from decimal import Decimal

class Tier(str, Enum):
    T1 = "T1"; T2 = "T2"; T3 = "T3"

@dataclass
class Message:
    role: str          # "system" | "user" | "assistant"
    content: str

@dataclass
class Signal:
    name: str          # vd "code", "multi_step", "classifier_error"
    points: int

@dataclass
class ModelRef:
    model_id: str      # vd "gemini-flash-lite"
    provider: str      # vd "google"

@dataclass
class Usage:
    prompt_tokens: int
    completion_tokens: int
```

### B.2 Classifier — hợp đồng chấm độ khó (FR-02, FR-12)
```python
@dataclass
class ClassificationResult:
    score: int                 # 0..100
    tier: Tier
    signals: list[Signal]      # giải thích được (NFR-05)
    classifier_version: str    # "heuristic-v1" | "llm-v2" | "embed-v2"
    latency_ms: int
    cost_usd: Decimal = Decimal("0")   # chi phí của chính lần phân loại; 0 với heuristic (§9.1)

class BaseClassifier(ABC):
    @abstractmethod
    async def classify(self, messages: list[Message]) -> ClassificationResult: ...
```
**Cam kết hành vi (phần của contract):**
1. **Không bao giờ raise.** Lỗi nội bộ/timeout → trả `tier=T2, score=45, signals=[Signal("classifier_error", 0)]` (an toàn giữa).
2. Tự giới hạn thời gian ≤ `ROUTER_TIMEOUT_MS` (env, mặc định 800ms).
3. Thuần chức năng: không ghi DB, không đọc config ngoài constructor → dễ test, dễ thay v1↔v2.

### B.3 Policy Engine — hợp đồng chọn model (FR-11, FR-04)
```python
@dataclass
class RoutingPlan:
    chain: list[ModelRef]      # thứ tự thử; phần tử 0 là primary
    tier_effective: Tier       # tier sau khi áp tier_shift của policy / force_tier
    policy_applied: str

class BasePolicyEngine(ABC):
    @abstractmethod
    def select(
        self,
        classification: ClassificationResult,
        policy: Optional[str] = None,          # None -> default_policy trong config
        force_model: Optional[str] = None,
        force_tier: Optional[Tier] = None,
        required_capabilities: frozenset[str] = frozenset({"text"}),  # vd thêm "stream"
        exclude: frozenset[tuple[str, str]] = frozenset(),  # (model_id, provider) đang bị circuit OPEN
    ) -> RoutingPlan: ...
```
Cam kết: `chain` không rỗng, không chứa phần tử trong `exclude`, và **mọi model trong chain đều có đủ `required_capabilities`** (tra `model_capabilities` — B.4); tier rỗng sau lọc → dùng chain của tier liền kề cao hơn; toàn hệ thống không còn model phù hợp → raise `NoCapableModelError` (API layer map thành 400 `unsupported_capability`); `force_model` hợp lệ → chain một phần tử.

**Cross-tier fallback:**
- **Lên (T1→T2→T3):** đã hoạt động — policy-time, khi tier hiện tại hết model khả dụng sau lọc circuit/capability thì tự dùng tier cao hơn.
- **Xuống (T3→T2→T1):** chưa có — khi toàn bộ provider cùng tier lỗi tại runtime, hiện trả 502 thay vì thử tier thấp hơn. Mở rộng theo #130: orchestrator retry tier thấp hơn khi client opt-in (`allow_tier_downgrade`), response phân biệt `tier_requested` vs `tier_effective`.

### B.4 Adapter — hợp đồng gọi provider (FR-03)
```python
@dataclass
class CompletionParams:
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    extra: dict = field(default_factory=dict)   # pass-through, adapter tự lọc field hỗ trợ

@dataclass
class CompletionResult:
    content: str
    finish_reason: str            # "stop" | "length" | "content_filter"
    usage: Usage                  # BẮT BUỘC chính xác — nguồn tính cost; provider trả thiếu -> adapter tự ước lượng + usage_estimated=True
    provider_latency_ms: int
    usage_estimated: bool = False
    dropped_params: list[str] = field(default_factory=list)  # tham số bị drop vì provider không hỗ trợ (A.1b)

@dataclass
class StreamChunk:
    delta: str
    finish_reason: Optional[str] = None
    usage: Optional[Usage] = None  # chỉ khác None ở chunk cuối

class BaseAdapter(ABC):
    provider: str                  # định danh duy nhất, vd "google"
    models: list[str]              # model_id adapter này phục vụ
    model_capabilities: dict[str, frozenset[str]]  # vd {"gemini-flash-lite": frozenset({"text","stream"})} — nguồn cho A.1b & lọc B.3

    @abstractmethod
    async def complete(self, model_id: str, messages: list[Message],
                       params: CompletionParams) -> CompletionResult: ...

    @abstractmethod
    def stream(self, model_id: str, messages: list[Message],
               params: CompletionParams) -> AsyncIterator[StreamChunk]: ...

    @abstractmethod
    async def health(self) -> bool: ...
```

### B.5 Taxonomy lỗi — điều khiển fallback (FR-09) *(phần quan trọng nhất của contract B)*
```python
class ProviderError(Exception):
    retryable: bool = False       # gateway CHỈ fallback khi retryable=True

class RateLimitError(ProviderError):      retryable = True   # 429
class ProviderUnavailable(ProviderError): retryable = True   # 5xx / network
class ProviderTimeout(ProviderError):     retryable = True   # quá REQUEST_TIMEOUT_S
class ContentFilteredError(ProviderError):retryable = False  # trả lỗi cho client
class BadRequestToProvider(ProviderError):retryable = False  # bug mapping, log + trả 500
```
**Nghĩa vụ của mỗi adapter:** bắt mọi lỗi thô của SDK/HTTP provider và **map về đúng taxonomy trên** — BE tuyệt đối không xử lý lỗi riêng của từng provider. Circuit breaker đếm trên `retryable=True`.

### B.6 Cost & Mock
```python
class CostCalculator:
    def calc(self, model_id: str, usage: Usage) -> Decimal:
        """Đọc pricing.yaml; model không có giá -> ConfigError NGAY LÚC STARTUP (fail fast)."""

class MockAdapter(BaseAdapter):
    """provider='mock'. Trả response tất định theo prompt (echo + độ dài giả lập),
    usage giả, độ trễ giả 200ms; hỗ trợ ép lỗi qua prompt chứa '#force_429' / '#force_500'
    -> dùng test fallback & demo circuit breaker mà không tốn API."""
```
`USE_MOCK_PROVIDERS=true` → registry chỉ nạp MockAdapter (3 model giả `mock-cheap/mid/premium` gắn 3 tier). Đây là cách BE, FE, CI chạy đủ luồng với chi phí 0.

### B.7 Luồng gọi chuẩn của BE (pseudo — để thấy các contract khớp nhau)
```python
cls = await classifier.classify(msgs)                       # B.2 — không bao giờ raise
plan = policy_engine.select(cls, policy, force_model,
                            force_tier, exclude=circuit.open_set())   # B.3
for ref in plan.chain:                                      # B.4/B.5
    try:
        result = await adapters[ref.provider].complete(ref.model_id, msgs, params)
        break
    except ProviderError as e:
        circuit.record_error(ref)
        if not e.retryable: raise
cost = cost_calc.calc(ref.model_id, result.usage)           # B.6
log_request(...)                                            # ghi DB theo schema PRD §8
```

---

## C. Interface Dev ↔ DevOps

### C.1 Biến môi trường — **gateway** (image `smartroute/gateway`, context `./gateway`)
| Biến | Bắt buộc | Secret | Default | Mô tả |
|---|---|---|---|---|
| `DATABASE_URL` | ✔ | ✔ | `postgresql+psycopg2://sr:smartroute@localhost:5432/smartroute` (dev Docker) | Render/Supabase: `postgresql://postgres.PROJECT:PASSWORD@POOLER:6543/postgres?sslmode=require` |
| `ADMIN_KEY` | ✔ | ✔ | — | Auth `/admin/*` và đăng nhập dashboard |
| `GEMINI_API_KEY` | ✗ | ✔ | — | Thiếu → adapter google **tự disable** (model `enabled=false`), không crash |
| `GROQ_API_KEY` | ✗ | ✔ | — | Như trên |
| `OPENAI_API_KEY` | ✗ | ✔ | — | Như trên |
| `ANTHROPIC_API_KEY` | ✗ | ✔ | — | Như trên |
| `OLLAMA_BASE_URL` | ✗ | ✗ | `http://localhost:11434` | Adapter local |
| `USE_MOCK_PROVIDERS` | ✗ | ✗ | `false` | `true` → chỉ MockAdapter (CI, FE dev) |
| `LOG_CONTENT` | ✗ | ✗ | `false` | `true` mới lưu preview prompt/response (NFR-03) |
| `LOG_LEVEL` | ✗ | ✗ | `info` | Log JSON-lines ra **stdout**: `{ts, level, msg, request_id?}` |
| `PORT` | ✗ | ✗ | `8000` | |
| `CONFIG_DIR` | ✗ | ✗ | `./app/config` | Chứa 3 file YAML (mục D) |
| `REQUEST_TIMEOUT_S` | ✗ | ✗ | `60` | Timeout mỗi lần gọi provider |
| `ROUTER_TIMEOUT_MS` | ✗ | ✗ | `800` | Trần thời gian classifier |
| `MAX_INPUT_TOKENS` | ✗ | ✗ | `8000` | Vượt → 400 `context_too_long` (PRD §1.5) |
| `MAX_MESSAGES` | ✗ | ✗ | `50` | Vượt → 400 `too_many_messages` |
| `CB_ERROR_THRESHOLD` | ✗ | ✗ | `5` | Số lỗi liên tiếp mở circuit |
| `CB_OPEN_SECONDS` | ✗ | ✗ | `300` | Thời gian mở circuit |
| `CLASSIFIER_V2_ENABLED` | ✗ | ✗ | `false` | M3 (nếu M1–M2 ổn) |
| `CLASSIFIER_V2_MODEL` | ✗ | ✗ | — | model_id dùng cho LLM-classifier |

### C.2 Biến môi trường — **dashboard** (image `smartroute/dashboard`, context `./dashboard`) & **db**
| Component | Biến | Bắt buộc | Ghi chú |
|---|---|---|---|
| dashboard | `VITE_API_BASE_URL` | ✔ | Build-time; dev `http://localhost:8000` |
| db (postgres:16) | `POSTGRES_USER=sr`, `POSTGRES_PASSWORD` (secret), `POSTGRES_DB=smartroute` | ✔ | Volume `pgdata:/var/lib/postgresql/data` |

### C.3 Port, probe, thứ tự khởi động
| Component | Port | Liveness | Readiness | Phụ thuộc |
|---|---|---|---|---|
| gateway | 8000 | `GET /healthz` (luôn 200 nếu sống) | `GET /readyz` (200 khi DB+config OK, ngược lại 503) | db healthy |
| dashboard | 5173 dev / 80 build | `GET /` 200 | — | gateway ready (chỉ để trải nghiệm, không hard-block) |
| db | 5432 | `pg_isready` | — | — |

- **Migration:** entrypoint gateway chạy `alembic upgrade head` trước khi start app (idempotent) — DevOps không cần bước riêng.
- **CI (`.github/workflows/ci.yml`):** `ruff check` + `pytest` với `USE_MOCK_PROVIDERS=true`, Postgres service container trong GitHub Actions — `DATABASE_URL` trỏ đến service.
- DevOps có thể dựng toàn bộ compose ngay hôm nay: gateway ở mock mode + FE fixtures là hệ thống đã chạy end-to-end trước khi có bất kỳ logic AI nào.

---

## D. Interface cấu hình (schema 3 file YAML trong `CONFIG_DIR`)

Validate bằng pydantic **lúc startup, fail fast** — sai schema là không boot (lỗi in rõ path).

```yaml
# models.yaml — ánh xạ tier -> model (đồng bộ 1-1 với /admin/config §A.7)
tiers:
  T1: { primary: {model: gemini-flash-lite, provider: google},
        fallbacks: [{model: mock-cheap, provider: mock}] }
  T2: { primary: {model: gpt-mini, provider: openai}, fallbacks: [] }
  T3: { primary: {model: claude-sonnet, provider: anthropic}, fallbacks: [] }
thresholds: { t1_max: 30, t2_max: 60 }
default_policy: balanced
```
```yaml
# pricing.yaml — nguồn duy nhất để tính cost & baseline premium
premium_baseline_model: claude-sonnet     # dùng tính baseline_premium_cost_usd
models:
  gemini-flash-lite: { provider: google, input_per_1m_usd: 0.10, output_per_1m_usd: 0.40, quality_rank: 3 }
  claude-sonnet:     { provider: anthropic, input_per_1m_usd: 3.00, output_per_1m_usd: 15.00, quality_rank: 9 }
# LƯU Ý: số liệu trên là placeholder — cập nhật theo snapshot bảng giá chính thức tại M1 (PRD §1.1, H2).
```
```yaml
# policies.yaml
policies:
  cost_first:    { tier_shift: -10, order_by: cost_asc }
  balanced:      { tier_shift: 0,   order_by: quality_then_cost }
  quality_first: { tier_shift: 10,  order_by: quality_desc }
```
Ràng buộc chéo (validator): mọi `model` trong `models.yaml` phải có giá trong `pricing.yaml`; `provider` phải có adapter đăng ký; `quality_rank` (1–10) là khóa sắp xếp cho `order_by`.

---

## E. Quy trình thay đổi interface
1. Mở PR sửa `docs/05_interfaces.md` (label `interface-change`), mô tả breaking hay non-breaking.
2. Cả team ack trong PR (FE + BE + AI + DevOps nếu liên quan) → merge → mới được sửa code hai phía.
3. FastAPI tự sinh Swagger tại `/docs` — **phải khớp** tài liệu này; lệch = bug, ưu tiên sửa theo tài liệu.
4. Bump version đầu file (v1.0 → v1.1 non-breaking, v2.0 breaking) + 1 dòng changelog cuối file.

**Changelog**
- v1.4 (01/09/2026) — chuẩn hóa khoảng thời gian admin thành UTC `[from, to)`, từ chối khoảng đảo và đồng bộ số request giữa KPI, breakdown, chart. Non-breaking.
- v1.3 (22/08/2026) — hạch toán chi phí router (`08_adaptive_routing.md` §9.1) + OutcomeObserver (§9): `ClassificationResult.cost_usd` (mặc định 0, non-breaking cho mọi classifier hiện có); `router_cost_usd` + `outcome_evidence` trong `smartroute` metadata của A.1/A.4; `/admin/stats` thêm `router_cost_usd`/`net_cost_usd` và `savings_pct` chuyển sang net. Non-breaking.
- v1.2 (07/08/2026) — phản hồi review mentor lần 2: khai báo phạm vi sở hữu ở header (bề mặt HTTP F1 do `v1_f1.yaml` sở hữu, file này giữ lớp B/C/D + HTTP chưa có OpenAPI); sửa path file header về `docs/design/`; định nghĩa cách tính `success_rate` trong A.6 theo protocol PRD §9.4. Non-breaking.
- v1.1 (05/08/2026) — theo review mentor: whitelist tham số MVP + giới hạn input (A.1); ma trận tương thích theo provider (A.1b); `capabilities` trong `/v1/models` (A.3); `/v1/usage` hai trạng thái `pending|complete`, không còn race 404 (A.4); chuẩn hóa error codes tương thích (A.0); lọc `required_capabilities` trong PolicyEngine (B.3); `model_capabilities` + `dropped_params` trong adapter contract (B.4); env `MAX_INPUT_TOKENS`/`MAX_MESSAGES` (C.1); đổi nhãn Gate → mốc M. Non-breaking.
- v1.0 (02/08/2026): bản đầu — 4 lớp interface A/B/C/D.
