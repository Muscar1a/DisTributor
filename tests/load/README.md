# Đo tải SmartRoute Gateway bằng Locust

Bắn tải vào môi trường chung bằng **chính bộ dữ liệu đã gán nhãn của team**, đo
riêng độ trễ phần định tuyến, và ghi lại bằng chứng của mọi lỗi.

Mục tiêu mặc định: `https://p-156-staging.onrender.com`.

## Hai câu hỏi khác nhau, hai kịch bản khác nhau

| Câu hỏi | Kịch bản | Lệnh |
|---|---|---|
| "Ở mức tải của bản demo, hệ thống có đổ không?" | 4 chặng cố định 1/1/3/5 người | `--sr-shape acceptance` |
| "Hệ thống chịu được bao nhiêu người?" | Tăng dần tới khi gãy | `--sr-shape ramp` |

Đừng lẫn hai cái. Kịch bản thứ nhất **đạt/không đạt**; kịch bản thứ hai cho ra
**một con số trần** và con số đó chỉ đúng cho đúng cấu hình máy chủ hôm đó.

## Ngưỡng đạt (cho kịch bản nghiệm thu)

| Chỉ số | Ngưỡng | Nguồn |
|---|---|---|
| Tỉ lệ lỗi | dưới 1% | DoD milestone |
| Độ trễ định tuyến p95, chấm điểm bằng công thức | dưới 300 mili-giây | [02_prd.md:199](../../docs/design/02_prd.md#L199) |
| Độ trễ định tuyến p95, chấm điểm bằng mô hình (có nhớ đệm) | dưới 1 giây | như trên |
| Chạy hết chặng đã hoạch định | không dừng giữa chừng | — |

Lỗi 429 do chính gateway sinh ra **không** tính vào tỉ lệ lỗi sản phẩm, nhưng vẫn
làm hỏng phép đo: tải dự kiến phải nằm dưới hạn mức của khoá, nếu không con số đo
được là hạn mức chứ không phải sức chứa.

---

## Dữ liệu bắn đi lấy từ đâu

[`prompts.py`](prompts.py) **không tự viết prompt**. Nó nạp hai bộ dữ liệu có sẵn
trong repo:

| Bộ | Nội dung | Dùng cho |
|---|---|---|
| [`src/evals/datasets/mixed_200.jsonl`](../../src/evals/datasets/mixed_200.jsonl) | 200 câu một lượt, gán nhãn dễ/vừa/khó + tier kỳ vọng, nửa tiếng Việt nửa tiếng Anh | `ChatUser` |
| [`src/evals/datasets/multiturn_30.jsonl`](../../src/evals/datasets/multiturn_30.jsonl) | 18 hội thoại 2–4 lượt, mỗi lượt có ý định và tier kỳ vọng | `SessionUser` |

Hai điều cần biết về hai bộ này:

* **Phân bố thật của bộ 200 câu là 46 dễ / 65 vừa / 89 khó (≈23/33/45)**, không
  phải 40/35/25 như tài liệu yêu cầu đặt ra làm mục tiêu. Mặc định harness dùng
  phân bố thật; thêm `--sr-mix prd` nếu muốn ép về đúng tỉ lệ tài liệu để so sánh.
* **Cả hai bộ đang ở trạng thái chờ người rà soát** (`pending_human_review`, cổng
  nghiệm thu của issue #122 chưa qua). Với đo tải thì không sao — ta cần *hình dạng*
  của lưu lượng, không cần nhãn đúng. Nhưng đừng lấy con số ở đây làm bằng chứng
  chất lượng; eval thật nằm ở `src/evals/`.

Prompt quá dài (vượt trần 8000 token của gateway) và prompt chứa chuỗi kích hoạt
lỗi giả của bộ giả lập đều bị lọc bỏ khi nạp.

## Hai loại người dùng ảo

**`ChatUser`** (trọng số 7) — hỏi một câu rồi thôi, không phiên, không lịch sử.

**`SessionUser`** (trọng số 3) — hội thoại 2–4 lượt trên cùng một `session_id`,
mỗi lượt mang theo toàn bộ lịch sử. **Đây mới là đường đi qua bộ định tuyến phiên**:
mỗi lượt phải đọc trạng thái định tuyến từ cơ sở dữ liệu, tính EMA / trễ đổi bậc /
cộng điểm khi thất bại, rồi ghi lại. Đo tải mà chỉ bắn câu lẻ là bỏ qua đúng phần
tốn kém nhất. Giữa các lượt có nghỉ 1–3 giây, mô phỏng người thật đọc câu trả lời.

Chạy riêng một loại bằng cách nêu tên lớp ở cuối lệnh:

```powershell
... -m locust -f locustfile.py ... SessionUser
```

---

## 0. Cài đặt (một lần)

```powershell
uv pip install -r tests/load/requirements-load.txt
```

`locust` để riêng, **không** thêm vào `requirements.txt` — `Dockerfile` cài file đó
vào ảnh chạy thật, không cần công cụ đo tải trong đó.

### Khoá quản trị đặt ở đâu

Giá trị lấy từ **trang Environment của service trên Render**, biến `ADMIN_KEY`. Nó
không nằm trong repo và không bao giờ được commit.

`loadkey.py` tìm khoá theo thứ tự, dừng ở nguồn đầu tiên có giá trị, và **luôn in
ra nguồn nào được dùng**:

| Thứ tự | Nguồn | Khi nào dùng |
|---|---|---|
| 1 | cờ `--admin-key` | chạy một phát rồi thôi |
| 2 | biến `SR_ADMIN_KEY` | **nên dùng** cho một buổi đo |
| 3 | biến `ADMIN_KEY` | nếu shell đã có sẵn từ việc khác |
| 4 | dòng `ADMIN_KEY=` trong `.env` ở gốc repo | khoá **local**, không phải khoá môi trường chung |

Cách nên dùng — đặt trong phiên PowerShell hiện tại, mất khi đóng cửa sổ:

```powershell
$env:SR_ADMIN_KEY = "<khoá lấy từ Render>"
$env:SR_HOST      = "https://p-156-staging.onrender.com"
```

Đừng gõ khoá thẳng vào lệnh `loadkey.py --admin-key ...` trừ khi chạy một lần —
nó vào lịch sử lệnh của PowerShell và nằm đó rất lâu.

**Đừng dùng `setx`** để đặt vĩnh viễn. Biến môi trường mức user trên Windows che
mất `.env` (thư viện đọc `.env` không ghi đè biến đã tồn tại), nên vài tuần sau
sẽ có người bắn nhầm khoá mà không hiểu vì sao. Đây là bẫy đã gặp trong dự án này
rồi. Dòng `[loadkey] ... nguồn=...` in ra ở mỗi lệnh là để bắt đúng tình huống đó
— đọc nó trước khi tin kết quả.

`.env` nằm trong `.gitignore` nên an toàn để chứa khoá local, nhưng nhớ nó là khoá
của máy mình, không phải của môi trường chung.

---

## 1. Kiểm tra trước khi bắn

```powershell
cd tests\load\scripts
..\..\..\.venv\Scripts\python.exe loadkey.py preflight
```

Xác nhận `/healthz` và `/readyz` trả 200, khoá quản trị đúng, và **hạn mức token
của nhà cung cấp còn lại trong ngày** đủ cho số request định bắn. Nếu `/admin/keys`
trả 401 thì khoá sai; trả 503 thì máy chủ chưa cấu hình `ADMIN_KEY`.

### Máy chủ ngủ đông

Gói miễn phí của Render **tắt máy chủ khi không có ai gọi**. Đo thật:

```
lần gọi đầu sau khi ngủ:  18,5 giây
lần gọi sau đó:            0,46 giây
```

Nên **luôn gọi `/healthz` một lần để đánh thức trước khi bấm chạy**, nếu không
toàn bộ chặng đầu là số liệu của việc khởi động máy chứ không phải của gateway.
Chặng warm-up 5 phút trong kịch bản nghiệm thu tồn tại chính vì lý do này.

---

## 2. Tạo khoá riêng cho lần đo

**Đừng dùng `GATEWAY_DEV_KEY` để đo tải.** Middleware gán cứng 60 request mỗi phút
cho khoá đó ([middleware.py:190](../../src/gateway/app/api/middleware.py#L190)), nên
3 người × 0,5 request/giây = 90 request/phút sẽ bị chính gateway chặn — đo ra hạn
mức, không phải sức chứa.

```powershell
..\..\..\.venv\Scripts\python.exe loadkey.py create --rpm 600 --name loadtest-2026-08-27
```

Khoá thật **chỉ hiện một lần**. Lệnh in sẵn dòng gán biến, chép nguyên:

```powershell
$env:SR_API_KEY = "sr-..."
```

Chọn `--rpm` cao hơn tải dự kiến ít nhất 2 lần. Với kịch bản tăng dần thì phải cao
hơn nhiều — 40 người × 0,5 = 1200 request/phút, nên đặt `--rpm 3000` để hạn mức
không trở thành cái gãy trước.

### Bẫy chặn đường: trần token theo ngày

`DAILY_TOKEN_BUDGET` (mặc định **50.000 token mỗi ngày mỗi khoá**,
[loader.py:214](../../src/gateway/app/config/loader.py#L214)) áp cho mọi khoá tạo qua
API quản trị, **không đặt riêng từng khoá được**, và chỉ đặt lại lúc 00:00 giờ UTC.
Vượt trần thì trả 429 mã `daily_token_budget_exceeded`.

Đo trên chính corpus này với bộ giả lập:

| | |
|---|---:|
| Token trung bình mỗi request | 140 |
| Chạm trần 50.000 sau | ~358 request |
| Kịch bản nghiệm thu đầy đủ cần | ~4.200 request (~586.000 token) |
| **Vỡ trần ở phút thứ** | **12, ngay trong chặng 1 người** |

Tức là **trần này chặn cả kịch bản nghiệm thu**, không riêng kịch bản tăng dần.
Không xử lý thì phép đo dừng trước cả khi chạm chặng 3 người. Chọn một trong ba:

| Cách | Đổi gì | Đánh đổi |
|---|---|---|
| Đặt `DAILY_TOKEN_BUDGET=0` trên Render | 1 biến môi trường, Render tự khởi động lại | Tắt hẳn trần trên môi trường chung — đúng chỗ để tắt, nhưng vẫn là đổi cấu hình |
| Chạy chặng 1–2 người bằng `GATEWAY_DEV_KEY` | không đổi gì | Trần token **không** áp cho dev key ([quota.py:23](../../src/gateway/app/core/quota.py#L23) — bỏ qua khi mã khoá không phải số nguyên), nhưng dev key bị chặn cứng 60 request/phút nên **tối đa 2 người** |
| Rút gọn phép đo xuống dưới ~350 request | không đổi gì | Quá ít mẫu: 1% của 350 là 3,5 request, không đo nổi ngưỡng lỗi 1%, phân vị p95 cũng chưa ổn định |

Cách 2 là cách duy nhất không đụng vào cấu hình môi trường chung, và đủ cho hai
chặng nền. Chặng 3 và 5 người bắt buộc cần khoá tạo qua API quản trị, nên cần cách 1.

Đây cũng là ứng viên hàng đầu cho loạt 429 chưa giải thích được ở lần đo 2026-08-27
(`docs/benchmarks/staging-load-20260827/README.md`), cùng với hạn mức 60 của khoá
lập trình. Harness này ghi mã lỗi nên lần chạy tới sẽ phân biệt được ngay.

---

## 3. Chạy thử 1 phút

```powershell
cd ..
..\..\.venv\Scripts\python.exe -m locust -f locustfile.py `
  --host $env:SR_HOST --headless -u 1 -r 1 -t 60s `
  --sr-diag-file ..\..\out\load\smoke-diag.jsonl
```

Phải thấy đủ ba dấu hiệu:

1. 0 lỗi;
2. phân bố T1/T2/T3 khác 0 — dồn hết vào một bậc là bộ chấm điểm đang hỏng;
3. dòng `hội thoại: N trọn vẹn, 0 bỏ dở` — nếu hội thoại nào cũng bỏ dở thì đường
   đi qua phiên đang lỗi.

---

## 4. Kịch bản nghiệm thu — "có đổ không"

Bốn chặng tự động: khởi động 1 người (5 phút) → nền 1 người (15 phút) → **3 người
(15 phút)** → 5 người, mức trần tài liệu (15 phút). Tổng 50 phút.

```powershell
..\..\.venv\Scripts\python.exe -m locust -f locustfile.py `
  --host $env:SR_HOST --headless `
  --sr-shape acceptance `
  --csv ..\..\out\load\acceptance --csv-full-history `
  --html ..\..\out\load\acceptance.html `
  --sr-diag-file ..\..\out\load\acceptance-diag.jsonl `
  --sr-abort-error-rate 0.05
```

## 5. Kịch bản tăng dần — "chịu được bao nhiêu người"

Bắt đầu 2 người, cứ 60 giây cộng thêm 2, cho tới khi tỉ lệ lỗi vượt ngưỡng thì tự
dừng. `--sr-ramp-max` là chốt cứng phòng khi hệ thống không gãy trong ngân sách.

```powershell
..\..\.venv\Scripts\python.exe -m locust -f locustfile.py `
  --host $env:SR_HOST --headless `
  --sr-shape ramp --sr-ramp-step 2 --sr-ramp-hold 60 --sr-ramp-max 40 `
  --csv ..\..\out\load\ramp --csv-full-history `
  --sr-diag-file ..\..\out\load\ramp-diag.jsonl `
  --sr-abort-error-rate 0.05
```

Khi dừng, dòng in ra ghi rõ **đang ở bao nhiêu người lúc gãy**. Nhưng con số đáng
báo cáo không phải chỗ gãy, mà là **bậc cuối cùng còn đạt cả hai ngưỡng lỗi và độ
trễ** — đọc từ `ramp_stats_history.csv`, tìm bậc mà độ trễ bắt đầu vọt lên trong
khi số request mỗi giây thôi không tăng nữa. Đó mới là trần dùng được.

## 6. Chạy một chặng lẻ

Bỏ `--sr-shape`, dùng `-u`/`-r`/`-t` như bình thường:

```powershell
..\..\.venv\Scripts\python.exe -m locust -f locustfile.py `
  --host $env:SR_HOST --headless -u 3 -r 1 -t 10m `
  --csv ..\..\out\load\users3 --sr-diag-file ..\..\out\load\users3-diag.jsonl
```

### Các cờ riêng của harness

| Cờ | Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|---|
| `--sr-api-key` | `SR_API_KEY` | — | Khoá gửi kèm mỗi request |
| `--sr-policy` | `SR_POLICY` | `balanced` | `cost_first` / `balanced` / `quality_first` |
| `--sr-classifier` | `SR_CLASSIFIER` | rỗng | rỗng = mặc định của máy chủ; `v1.5`; `v2` (gọi mô hình thật, **tốn tiền và chậm hơn**) |
| `--sr-mix` | `SR_MIX` | `dataset` | `dataset` = phân bố thật 46/65/89; `prd` = ép về 40/35/25 |
| `--sr-throughput` | `SR_THROUGHPUT` | `0.5` | request mỗi giây mỗi người |
| `--sr-shape` | `SR_SHAPE` | rỗng | `acceptance` hoặc `ramp` |
| `--sr-ramp-step` | `SR_RAMP_STEP` | `2` | mỗi bậc cộng thêm bấy nhiêu người |
| `--sr-ramp-hold` | `SR_RAMP_HOLD` | `60` | giữ mỗi bậc bấy nhiêu giây |
| `--sr-ramp-max` | `SR_RAMP_MAX` | `40` | trần số người, chốt an toàn cứng |
| `--sr-abort-error-rate` | `SR_ABORT_ERROR_RATE` | `0.10` | ngưỡng lỗi để tự dừng (0 = tắt) |
| `--sr-abort-min-requests` | `SR_ABORT_MIN_REQUESTS` | `50` | số request tối thiểu trước khi xét ngưỡng |
| `--sr-diag-file` | `SR_DIAG_FILE` | rỗng | tệp JSONL ghi chi tiết lỗi |
| `--sr-diag-limit` | `SR_DIAG_LIMIT` | `50` | số lỗi tối đa ghi chi tiết |

---

## 7. Đọc kết quả

Locust in ba dòng:

| Dòng | Nghĩa |
|---|---|
| `POST /v1/chat/completions` | câu một lượt, tổng thời gian chờ |
| `POST /v1/chat/completions (hội thoại)` | từng lượt trong hội thoại nhiều lượt |
| `ROUTER routing decision` | chỉ riêng phần định tuyến, lấy từ `latency_router_ms` trong thân trả lời |

**Cột 95% của dòng `ROUTER` là con số đem so với ngưỡng**, không phải cột của hai
dòng trên — phần còn lại là thời gian mô hình sinh chữ, không phải lỗi của bộ định
tuyến. Tên dòng này giữ nguyên như lần đo trước để hai lần so được với nhau.

So hai dòng `POST` với nhau cũng đáng nhìn: nếu dòng hội thoại chậm hơn hẳn thì
chi phí đọc-ghi trạng thái phiên vào cơ sở dữ liệu đang là nút thắt.

Cuối phiên harness in thêm:

* phân bố T1/T2/T3 và số request phải chuyển sang mô hình dự phòng;
* **tỉ lệ bậc khớp nhãn kỳ vọng** — đây là *tín hiệu tỉnh táo*, không phải kết quả
  đánh giá. Nếu tỉ lệ này tụt hẳn ở các bậc tải cao thì định tuyến đang đổi hành vi
  khi bị ép, một kiểu hỏng khác hẳn chậm hay lỗi;
* số hội thoại trọn vẹn và số bỏ dở;
* bảng lỗi theo mã (`rate_limit_exceeded` / `daily_token_budget_exceeded` / `http_502`…).

Tệp `--sr-diag-file` chứa thân trả lời, `Retry-After`, mã request, và với lỗi trong
hội thoại thì có cả mã hội thoại, tên kịch bản và số thứ tự lượt — đủ để tra ngược
trong `/admin/requests/{request_id}`.

Chụp số liệu phía máy chủ trong cùng khoảng thời gian:

```powershell
cd scripts
..\..\..\.venv\Scripts\python.exe loadkey.py stats --minutes 60 --out ..\..\..\out\load\admin-stats.json
```

---

## 8. Dọn dẹp

```powershell
..\..\..\.venv\Scripts\python.exe loadkey.py revoke --id <id>
```

Khoá đo tải để lại là một cửa hậu 600 request/phút không ai để ý. Thu hồi ngay.

---

## Giới hạn đã biết của môi trường chung

Đọc trước khi kết luận "gateway không chịu nổi tải":

1. **Gói miễn phí Render: 0,1 CPU / 512 MB, một máy.** Đây là trần thật của phép đo.
2. **Một tiến trình uvicorn** — `Dockerfile` chạy không có `--workers`. Toàn bộ tải
   đi qua một vòng lặp sự kiện.
3. **Truy vấn cơ sở dữ liệu đồng bộ nằm trong hàm bất đồng bộ** —
   `verify_db_api_key` ([middleware.py:194](../../src/gateway/app/api/middleware.py#L194)),
   kiểm tra trần token, đọc-ghi trạng thái phiên và ghi nhật ký đều dùng psycopg2
   đồng bộ, chạy thẳng trên vòng lặp sự kiện. Cơ sở dữ liệu chậm là vòng lặp tắc →
   kiểm tra sức khoẻ quá hạn → Render trả **502**. Thấy 502 trong kết quả thì thường
   là chuyện này, không phải hết bộ nhớ.
4. **Hạn mức và cầu dao chỉ đếm trong một tiến trình** — thêm tiến trình thì hạn mức
   thực tế nhân lên theo số tiến trình.
5. **Bắn từ máy cá nhân qua Internet** — đường truyền và máy của bạn được tính vào
   số đo. Con số là "người dùng ở Việt Nam thấy thế nào", không phải "máy chủ nhanh
   thế nào".

Kết quả đo trên gói miễn phí là **cận dưới** của sức chứa, không phải giới hạn của
kiến trúc.
