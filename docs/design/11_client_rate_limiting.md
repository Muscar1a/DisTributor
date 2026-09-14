# Client Rate Limiting — SmartRoute Gateway
**v1.0 · 2026-08-22 · File: `docs/design/11_client_rate_limiting.md`**

---

## 1. Bối cảnh

Gateway cần bảo vệ chính mình khỏi một client đơn lẻ spam request. Đây là vấn đề khác so với hai cơ chế chi phí hiện có:

| Cơ chế | Bảo vệ cái gì | Hành động khi vượt | Tài liệu |
|--------|--------------|-------------------|----------|
| **QuotaGuard** | Tổng token OpenAI/ngày | Loại model khỏi chain | [`07_quota_tracking.md`](07_quota_tracking.md) |
| **TierRateLimiter** | Budget frontier (T3) toàn hệ thống | Downgrade tier | [`11_tier_rate_limiting.md`](11_tier_rate_limiting.md) |
| **Client Rate Limiter** *(tài liệu này)* | Băng thông hệ thống per-client | **429 Too Many Requests** |  |

**Vấn đề:** `api_keys.rate_limit` (mặc định 60 RPM) và `request.state.rate_limit` đã tồn tại trong DB và middleware từ trước — nhưng chưa bao giờ được enforce. Một client có thể gửi 10 000 request/phút mà gateway không ngăn được.

**Giải pháp:** Thêm sliding-window counter per-client vào middleware. Khi vượt limit → trả 429 ngay, không cho request đi vào orchestrator.

---

## 2. Identity của client

Client được nhận dạng theo thứ tự ưu tiên:

```
1. api_key_id (int)  ← authenticated request qua DB key
2. "dev:<GATEWAY_DEV_KEY hash>"  ← static dev key
3. "<client IP>"  ← open mode (không auth), fallback
```

Lý do dùng `api_key_id` thay vì raw key: ID là int nhỏ, phù hợp làm dict key; hash của dev key đảm bảo dev mode cũng bị throttle nếu cần.

> **Lưu ý implementation:** Middleware hiện tại set `api_key_id = None` cho cả dev key và open mode. Implementation cần set ID khác biệt (ví dụ `"dev:<hash>"`) cho dev key để hai loại client không chia chung bucket. Open mode dùng `request.client.host` làm client_id khi `api_key_id is None`.

---

## 3. Thiết kế

### 3.1 Sliding-window counter

Cùng thuật toán với `TierRateLimiter` — `deque[float]` lưu monotonic timestamps:

```
is_allowed(client_id, limit):
  1. Xóa timestamps cũ hơn (now - 60s)
  2. Nếu len(deque) >= limit → return False  (→ 429)
  3. Append now → return True
```

Window = 60 giây (1 phút), cố định, không cấu hình — "RPM" là đơn vị duy nhất được dùng trong codebase.

### 3.2 Nơi enforce

`AuthMiddleware.dispatch` (hoặc một `RateLimitMiddleware` riêng đặt ngay sau) — **sau khi auth pass**, trước khi request đến router:

```
Request
  │
  ├─ AuthMiddleware: xác thực → set request.state.api_key_id, request.state.rate_limit
  │
  ├─ [RateLimiter]: is_allowed(client_id, rate_limit) ?
  │     ├─ True  → call_next(request)
  │     └─ False → JSONResponse 429
  │
  └─ Router → Orchestrator
```

Lý do enforce sau auth (không phải trước): limit được lấy từ `request.state.rate_limit` vừa được set bởi auth step. Tách thành middleware riêng giữ `AuthMiddleware` không bị phình.

Rate limit middleware phải skip `_NO_AUTH_PATHS` (`/healthz`, `/readyz`, `/`) — nếu không, health check từ monitoring sẽ bị đếm vào bucket của IP nguồn.

### 3.3 Limit mặc định

| Client type | `rate_limit` nguồn |
|-------------|-------------------|
| DB API key | `api_keys.rate_limit` (default 60) |
| Dev key (`GATEWAY_DEV_KEY`) | Hardcode 60 trong middleware hiện tại |
| Open mode (no auth) | Hardcode 60 trong middleware hiện tại |

Giá trị 60 RPM đã được middleware set vào `request.state.rate_limit` — rate limiter chỉ đọc giá trị đó, không cần biết nguồn gốc.

### 3.4 Response khi vượt limit

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 60
X-SR-Request-Id: <uuid>
Content-Type: application/json

{
  "error": {
    "message": "Vượt giới hạn request. Thử lại sau 60 giây.",
    "type": "rate_limit_error",
    "code": "rate_limit_exceeded",
    "request_id": "<uuid>",
    "details": {
      "limit": 60,
      "window_seconds": 60
    }
  }
}
```

Header `Retry-After: 60` theo RFC 7231 — client SDK (bao gồm OpenAI SDK) tự động backoff khi thấy header này.

---

## 4. Luồng xử lý

```
POST /v1/chat/completions
  │
  ├─ AuthMiddleware
  │     ├─ validate Bearer key
  │     ├─ request.state.api_key_id = 42
  │     └─ request.state.rate_limit  = 60
  │
  ├─ RateLimitMiddleware
  │     ├─ client_id = request.state.api_key_id  (= 42)
  │     ├─ limit     = request.state.rate_limit   (= 60)
  │     ├─ limiter.is_allowed(42, 60) → False
  │     └─ return JSONResponse(429, Retry-After: 60)
  │
  [request không đến orchestrator]
```

---

## 5. Files cần tạo / sửa

| File | Hành động |
|------|-----------|
| `src/gateway/app/core/client_limiter.py` | Tạo mới — `ClientRateLimiter` class |
| `src/gateway/app/api/middleware.py` | Thêm `RateLimitMiddleware` (hoặc tích hợp vào `AuthMiddleware`) |
| `src/gateway/app/main.py` | Khởi tạo `ClientRateLimiter`, inject vào middleware |
| `src/gateway/tests/test_client_limiter.py` | Tạo mới — unit + integration tests |

---

## 6. Acceptance Criteria

| ID | Tiêu chí |
|----|---------|
| AC-1 | Client gửi > `rate_limit` request trong 60s → nhận 429 với body chuẩn và header `Retry-After: 60` |
| AC-2 | Client gửi đúng `rate_limit` request → tất cả 200 |
| AC-3 | Sau 60s window reset → client được phép gửi tiếp |
| AC-4 | Hai client khác nhau (khác `api_key_id`) không ảnh hưởng lẫn nhau |
| AC-5 | Open mode (không auth) bị throttle theo IP, không phải bypass hoàn toàn |
| AC-6 | `/healthz`, `/readyz`, `/` không bị throttle |
| AC-7 | `rate_limit` per-key từ DB được dùng đúng (key A limit 30, key B limit 120 — độc lập) |

---

## 7. Ceiling & upgrade path

- **In-memory, single instance** — cùng ràng buộc với `TierRateLimiter` (ADR-006). Scale ngang → mỗi replica có counter riêng → effective limit = `rate_limit × replicas`.
- **Upgrade:** thay `deque` bằng Redis `INCR` + `EXPIRE` — đổi implementation, không đổi interface middleware.
- **`Retry-After` chính xác hơn:** hiện hardcode 60s; có thể tính `ceil(deque[0] + 60 - now)` để trả thời gian chờ thực tế — upgrade khi client cần retry nhanh hơn.
- **Lock strategy:** global `asyncio.Lock` (như `TierRateLimiter`) đơn giản nhất; per-client lock hoặc lockless (mỗi key chỉ có 1 writer trong async event loop) giảm contention nếu cần.
- **IP fallback (open mode):** không chính xác sau reverse-proxy nếu `X-Forwarded-For` không được set đúng — chấp nhận được ở phạm vi đồ án (1 instance, không có load balancer).

---

## 8. Quan hệ với các tài liệu khác

- [`06_architecture.md`](06_architecture.md) §ADR-006 — in-memory state, upgrade path Redis
- [`11_tier_rate_limiting.md`](11_tier_rate_limiting.md) — rate limit toàn hệ thống theo tier (khác: per-tier global, downgrade thay vì block)
- [`07_quota_tracking.md`](07_quota_tracking.md) — kiểm soát chi phí token/ngày
- `src/gateway/app/db/models.py:18` — `APIKey.rate_limit` column (default 60)
- `src/gateway/app/api/middleware.py:88,100,108` — nơi `request.state.rate_limit` được set
