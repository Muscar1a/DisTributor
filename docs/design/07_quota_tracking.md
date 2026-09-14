# Quota Tracking — SmartRoute Gateway
**v1.0 · 2026-08-19 · File: `docs/design/07_quota_tracking.md`**

---

## 1. Bối cảnh

OpenAI giới hạn token theo nhóm model mỗi ngày (UTC):

| Nhóm | Models | Giới hạn/ngày |
|------|--------|--------------|
| `premium` | gpt-5.4, gpt-5.2, gpt-5.1, gpt-5, gpt-4.1, gpt-4o, o1, o3 | 250 000 token |
| `standard` | gpt-5.4-mini, gpt-5.4-nano, gpt-5-mini, gpt-5-nano, gpt-4.1-mini, gpt-4.1-nano, gpt-4o-mini, o3-mini, o4-mini | 2 500 000 token |

Gateway đã lưu `prompt_tokens` + `completion_tokens` + `model` + `ts` vào bảng `requests`. Tính năng này tổng hợp dữ liệu đó và phơi ra qua API — **không thêm bảng mới, không gọi OpenAI API**.

---

## 2. API Contract

### `GET /admin/usage/quota`

**Auth:** `X-Admin-Key: <ADMIN_KEY>`

**Query params:**

| Param | Mặc định | Mô tả |
|-------|----------|-------|
| `date` | Hôm nay (UTC) | Ngày cần xem, định dạng `YYYY-MM-DD` |

**Response 200:**
```json
{
  "date": "2026-08-19",
  "quotas": [
    {
      "group": "premium",
      "limit_tokens": 250000,
      "used_tokens": 87400,
      "remaining_tokens": 162600,
      "used_pct": 34.96,
      "models": ["gpt-5.4", "gpt-5.2", "gpt-5.1", "gpt-5", "gpt-4.1", "gpt-4o", "o1", "o3"],
      "breakdown": {
        "gpt-5.4": 50000,
        "gpt-4o": 37400
      }
    },
    {
      "group": "standard",
      "limit_tokens": 2500000,
      "used_tokens": 310000,
      "remaining_tokens": 2190000,
      "used_pct": 12.4,
      "models": ["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5-mini", "gpt-5-nano",
                 "gpt-4.1-mini", "gpt-4.1-nano", "gpt-4o-mini", "o3-mini", "o4-mini"],
      "breakdown": {
        "gpt-5-mini": 190000,
        "gpt-4o-mini": 120000
      }
    }
  ]
}
```

**`breakdown`** chỉ liệt kê model có `used_tokens > 0`.

**Response 400** — `date` sai định dạng:
```json
{ "error": { "message": "date phải có định dạng YYYY-MM-DD", "type": "invalid_request_error", "code": "invalid_param" } }
```

---

## 3. Thiết kế

### 3.1 Query DB

```sql
SELECT model,
       COALESCE(SUM(prompt_tokens), 0) + COALESCE(SUM(completion_tokens), 0) AS total_tokens
FROM requests
WHERE ts >= :day_start          -- 00:00:00 UTC của ngày cần xem
  AND ts <  :day_end            -- 00:00:00 UTC ngày kế tiếp
  AND model = ANY(:openai_models)
  AND status = 'success'
GROUP BY model
```

`prompt_tokens`/`completion_tokens` có thể NULL (request lỗi trước khi gọi provider) → dùng `COALESCE`.

### 3.2 Cấu hình quota

Khai báo trong `src/gateway/app/config/quota.yaml` (schema D — chỉnh không cần sửa code):

```yaml
openai_quotas:
  - group: premium
    limit_tokens: 250000
    models:
      - gpt-5.4
      - gpt-5.2
      - gpt-5.1
      - gpt-5
      - gpt-4.1
      - gpt-4o
      - o1
      - o3
  - group: standard
    limit_tokens: 2500000
    models:
      - gpt-5.4-mini
      - gpt-5.4-nano
      - gpt-5-mini
      - gpt-5-nano
      - gpt-4.1-mini
      - gpt-4.1-nano
      - gpt-4o-mini
      - o3-mini
      - o4-mini
```

### 3.3 Luồng xử lý

```
GET /admin/usage/quota?date=2026-08-19
  │
  ├─ parse & validate date param
  ├─ load quota.yaml (cached, hot-reload không cần)
  ├─ query DB: SUM tokens per model trong [day_start, day_end)
  └─ group kết quả theo quota.yaml → trả response
```

---

## 4. Files cần sửa / tạo

| File | Hành động |
|------|-----------|
| `src/gateway/app/config/quota.yaml` | Tạo mới — khai báo nhóm & giới hạn |
| `src/gateway/app/api/admin.py` | Thêm endpoint `GET /admin/usage/quota` |
| `src/gateway/tests/test_quota.py` | Tạo mới — unit test endpoint |

---

## 5. Acceptance Criteria

| ID | Tiêu chí |
|----|---------|
| AC-1 | `GET /admin/usage/quota` không truyền `date` → trả usage ngày hiện tại (UTC) |
| AC-2 | Truyền `date=YYYY-MM-DD` → trả đúng ngày đó |
| AC-3 | `used_tokens` = tổng `prompt_tokens + completion_tokens` của các request `status='success'` có model thuộc nhóm trong ngày |
| AC-4 | `breakdown` chỉ chứa model có `used_tokens > 0` |
| AC-5 | `date` sai định dạng → 400 |
| AC-6 | Không có request nào → `used_tokens: 0`, `breakdown: {}` |
| AC-7 | Endpoint yêu cầu `X-Admin-Key` — thiếu/sai → 401 |
