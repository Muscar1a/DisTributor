# Đo tải môi trường thử nghiệm — 28/08/2026

Mục tiêu: `https://p-156-staging.onrender.com`
Bản triển khai: commit `2dca654fa1c86b39162f940889da28865d93f5b0` (nhánh `dev`)
Công cụ: [`tests/load/`](../../../tests/load/) — Locust 2.46

## Kết luận trong một câu

Ở mức tải mà tài liệu kiến trúc đặt ra cho phạm vi đồ án (1–5 người dùng đồng
thời), gateway **đạt cả hai ngưỡng đã cam kết**: không có lỗi nào trong 1.925
request, và phần định tuyến tốn 76 mili-giây ở phân vị 95 — bằng một phần tư
ngưỡng 300 mili-giây.

---

## 1. Số đo được

Mỗi mức chạy **3 lần độc lập, mỗi lần 5 phút**, số dưới đây là trung bình; trong
ngoặc là khoảng dao động giữa ba lần.

| Người dùng | Tổng request | Request/giây | Lỗi | **Định tuyến p95** | Chờ trung vị |
|---:|---:|---:|---:|---:|---:|
| 1 | 104 | 0,35 | **0** | **79 ms** (78–82) | 1.533 ms |
| 3 | 265 | 0,88 | **0** | **76 ms** (75–76) | 2.667 ms |
| 5 | 273 | 0,91 | **0** | **76 ms** (75–77) | 5.067 ms |

### Chi tiết theo từng loại request

| Mức | Loại | Request | Trung vị | p95 | p99 |
|---:|---|---:|---:|---:|---:|
| 1 | hội thoại nhiều lượt | 104 | 1.533 ms | 2.033 ms | 2.900 ms |
| 1 | *phần định tuyến* | 104 | 73 ms | 79 ms | 497 ms |
| 3 | câu hỏi lẻ | 115 | 2.467 ms | 3.600 ms | 3.833 ms |
| 3 | hội thoại nhiều lượt | 150 | 2.667 ms | 3.733 ms | 4.033 ms |
| 3 | *phần định tuyến* | 265 | 72 ms | 76 ms | 343 ms |
| 5 | câu hỏi lẻ | 120 | 5.067 ms | 6.100 ms | 6.333 ms |
| 5 | hội thoại nhiều lượt | 152 | 4.500 ms | 6.067 ms | 6.567 ms |
| 5 | *phần định tuyến* | 273 | 72 ms | 76 ms | 343 ms |

### Đối chiếu với ngưỡng cam kết

| Chỉ số | Ngưỡng | Đo được | |
|---|---|---|---|
| Tỉ lệ lỗi | dưới 1% | **0%** | Đạt |
| Định tuyến p95 (chấm điểm bằng công thức) | dưới 300 ms | **76 ms** | Đạt |
| Chạy hết chặng đã hoạch định | không dừng giữa chừng | 9/9 lần trọn vẹn | Đạt |

Nguồn ngưỡng: [`02_prd.md`](../../design/02_prd.md) mục NFR-01 và NFR-02.

---

## 2. Ba phát hiện

### 2.1 Phần định tuyến không phải nút thắt

Khi tăng từ 3 lên 5 người, tổng thời gian chờ **tăng gần gấp đôi** (2.667 → 5.067
mili-giây) nhưng phần định tuyến **đứng yên ở 76 mili-giây**.

Nghĩa là thời gian tăng thêm nằm ở chỗ khác — nhiều khả năng là các truy vấn cơ sở
dữ liệu đồng bộ trong đường đi của request (xác thực khoá, kiểm hạn mức, ghi nhật
ký hai pha) chạy trên máy chỉ có 0,1 CPU.

Đây là kết luận về kiến trúc, không phụ thuộc phần cứng: tỉ lệ giữa hai phần vẫn
giữ nguyên khi đổi máy mạnh hơn.

### 2.2 Máy chủ bão hoà ở khoảng 0,9 request mỗi giây

```
3 người → 5 người:   số việc làm được  +3%   (0,88 → 0,91 request/giây)
                     thời gian chờ    +90%   (2.667 → 5.067 ms)
```

Thêm người không làm được thêm việc, chỉ làm hàng đợi dài ra. Đây là trần thực tế
của cấu hình hiện tại, đo được mà không cần đẩy tải tới lúc hệ thống gãy.

### 2.3 Hội thoại nhiều lượt tốn hơn câu hỏi lẻ khoảng 36 lần ở khâu định tuyến

Câu hỏi lẻ tốn khoảng 2 mili-giây cho khâu định tuyến; mỗi lượt trong hội thoại tốn
khoảng 74 mili-giây.

*Nguồn số:* hai con số này lấy từ hai lần chạy tách riêng từng loại trước đó
(một lần chỉ câu lẻ, một lần chỉ hội thoại), không phải từ bộ 9 lần chạy ở mục 1 —
bộ đó gộp chung hai loại vào một dòng chỉ số nên không tách được. Bộ 9 lần chạy
xác nhận gián tiếp: trung vị định tuyến đứng ở 72 mili-giây, tức nằm trong nhóm
hội thoại, đúng như dự đoán khi hội thoại chiếm 57% số lượt.

Nguyên nhân nằm trong code: khoảng đo của `latency_router_ms` chạy từ
[`chat_completions.py:245`](../../../src/gateway/app/api/chat_completions.py#L245)
tới dòng 370, và bao trọn lệnh đọc trạng thái phiên từ cơ sở dữ liệu ở dòng 319.
Câu hỏi lẻ không có mã phiên nên bỏ qua nhánh này.

Khoảng cách 36 lần là hệ quả của vị trí đặt truy vấn đó, không phải do máy yếu.

---

## 3. Cách đo

### Tải mô phỏng

Hai loại người dùng ảo chạy song song:

| Loại | Tỉ lệ | Hành vi |
|---|---:|---|
| Hỏi câu lẻ | 40% | gửi một câu rồi thôi, không có mã phiên |
| Hội thoại nhiều lượt | 60% | 2–4 lượt trên cùng một mã phiên, mang theo toàn bộ lịch sử, nghỉ 1–3 giây giữa các lượt |

Tỉ lệ nghiêng về hội thoại vì đây là sản phẩm trợ lý hội thoại — người dùng thật
hiếm khi hỏi đúng một câu rồi đóng trang, và hội thoại là đường tốn kém nhất.

Nhịp gửi: 0,5 request mỗi giây trên mỗi người dùng ảo, tức khoảng 2 giây một câu.

### Nội dung câu hỏi

Lấy từ hai bộ dữ liệu đã gán nhãn của nhóm, không tự viết thêm:

| Bộ | Nội dung |
|---|---|
| [`mixed_200.jsonl`](../../../src/evals/datasets/mixed_200.jsonl) | 200 câu hỏi một lượt, nửa tiếng Việt nửa tiếng Anh, gán nhãn dễ/vừa/khó |
| [`multiturn_30.jsonl`](../../../src/evals/datasets/multiturn_30.jsonl) | 18 hội thoại 2–4 lượt, mỗi lượt có bậc kỳ vọng |

Bốc ngẫu nhiên mỗi lượt. Câu vượt trần 8.000 token của gateway bị lọc bỏ khi nạp.

### Hạn mức khoá

Mỗi lần chạy dùng **một khoá gateway mới**, thu hồi ngay sau khi chạy xong. Lý do:
trần token theo ngày tính riêng cho từng khoá, dùng lại khoá cũ sẽ cộng dồn và
chạm trần giữa chừng, làm hỏng phép đo.

### Chốt an toàn

Locust tự dừng khi tỉ lệ lỗi vượt 5%. Không lần nào trong 9 lần chạy phải dùng đến
chốt này.

### Lệnh chạy lại

```powershell
$env:SR_HOST = "https://p-156-staging.onrender.com"
$env:SR_ADMIN_KEY = "<khoá quản trị>"
.venv\Scripts\python.exe tests\load\run_suite.py --users 1 3 5 --repeats 3 --duration 5m
```

Hướng dẫn đầy đủ: [`tests/load/README.md`](../../../tests/load/README.md)

---

## 4. Giới hạn của phép đo

Đọc phần này trước khi trích số đi nơi khác.

### 4.1 Chạy trên bộ giả lập, không phải mô hình thật

Xác nhận qua số liệu máy chủ lấy lúc 03:39 giờ UTC cùng ngày, trên cửa sổ 3 giờ
gồm 1.299 request: `by_provider` chỉ có `mock`, tổng chi phí bằng 0.

Bộ giả lập trả lời sau đúng 200 mili-giây. Mô hình thật mất 1–3 giây. Nên **con số
thời gian chờ trong báo cáo này chỉ mô tả phần gateway**, không mô tả trải nghiệm
người dùng cuối. Ghép mô hình thật vào thì cộng thêm 1–3 giây nữa.

Hệ quả kèm theo: mọi con số tiết kiệm chi phí đo trong lần chạy này đều vô nghĩa,
vì bộ giả lập miễn phí nên so với bất kỳ mốc nào cũng ra gần 100%.

### 4.2 Trần chính sách chặn trước trần kỹ thuật

Mỗi khoá gateway có trần **50.000 token mỗi ngày**, đặt qua biến môi trường
`DAILY_TOKEN_BUDGET` và **áp chung cho mọi khoá**, không đặt riêng từng khoá được.

Quy ra số câu hỏi:

| Chế độ | Token mỗi câu | Số câu mỗi khoá mỗi ngày |
|---|---:|---:|
| Bộ giả lập | ~123 | ~406 |
| Mô hình thật | ~600 | **~83** |

Giao diện web nhúng sẵn **một khoá duy nhất** trong gói JavaScript
([`api.js:20`](../../../src/dashboard/src/api.js#L20)), nên mọi người truy cập đều
chia chung túi hạn mức đó.

**Với mô hình thật, cả nhóm người dùng chỉ gửi được khoảng 83 câu hỏi mỗi ngày
trước khi bị chặn** — trong khi máy chủ về mặt kỹ thuật vẫn phục vụ được 5 người
đồng thời không lỗi. Trần chính sách bóp nghẹt trước khi trần kỹ thuật lên tiếng.

### 4.3 Phép đo dùng nhiều khoá, thực tế chỉ có một

Mỗi lần chạy dùng một khoá riêng để hạn mức không thành nút thắt giả. Đó là điều
kiện phòng thí nghiệm, không phải cảnh thật. Con số trong báo cáo trả lời câu *"máy
chủ làm được bao nhiêu"*, không trả lời câu *"một khách hàng được phép làm bao
nhiêu"*.

### 4.4 Phần cứng là gói miễn phí

Render gói miễn phí: 0,1 CPU, 512 MB, một máy, một tiến trình `uvicorn` (không có
`--workers`). Kết quả là **cận dưới** của sức chứa, không phải giới hạn của kiến trúc.

Máy chủ còn tự tắt khi không ai gọi. Đo được: lần gọi đầu sau khi ngủ mất **18,5
giây**, lần sau **0,46 giây**. Mọi phép đo đều đánh thức máy trước.

### 4.5 Mức 1 người chỉ có hội thoại

Một người dùng ảo duy nhất bốc theo tỉ lệ 40/60, và cả ba lần đều rơi vào hội thoại
nhiều lượt. Nên con số ở mức 1 người là của đường hội thoại, **không so ngang được**
với hai mức còn lại vốn trộn cả hai loại.

### 4.6 Bộ chấm điểm dùng bản v1

Toàn bộ phép đo chạy với bộ chấm điểm bằng công thức (bản mặc định của máy chủ).
Ngưỡng *"dưới 1 giây khi chấm điểm bằng mô hình"* trong NFR-01 **chưa có số** — bản
đó cần mô hình thật, mà môi trường thử nghiệm đang chạy bộ giả lập.

Bản v1 giống hệt nhau giữa nhánh `dev` và `main` trên toàn bộ đường đi của request
(đã kiểm: `classifier_v1.py`, `policy.py`, `chat_completions.py`, `middleware.py`,
`crud.py` đều không khác), nên số liệu này dùng được cho cả hai nhánh.

### 4.7 Bắn từ máy cá nhân qua Internet

Đường truyền và máy chạy Locust được tính vào số đo. Con số phản ánh *"người dùng ở
Việt Nam thấy thế nào"*, không phải *"máy chủ nhanh thế nào"*.

---

## 5. Việc cần làm tiếp

| # | Việc | Vì sao | Mức khẩn |
|---|---|---|---|
| 1 | Nâng `DAILY_TOKEN_BUDGET` trên bản chính thức | Ngày trình diễn cả nhóm khách dùng chung một khoá, với mô hình thật chỉ được ~83 câu hỏi cho cả buổi | **Trước 01/09** |
| 2 | Đo lại trên môi trường có mô hình thật | Số hiện tại chỉ mô tả gateway, không mô tả trải nghiệm | Cao |
| 3 | Đo bản chấm điểm bằng mô hình | Ngưỡng "dưới 1 giây" trong NFR-01 đang trống số | Trung bình |
| 4 | Chuyển truy vấn cơ sở dữ liệu ra khỏi vòng lặp sự kiện | Nguồn gốc của phần thời gian tăng theo tải (mục 2.1) | Sau Demo Day |
| 5 | Đưa trần token xuống thành thuộc tính của từng khoá | Hiện là biến chung, không phân biệt được gói miễn phí và gói trả phí | Sau Demo Day |
| 6 | Chuyển bộ đếm hạn mức ra kho dùng chung | Bộ đếm nằm trong bộ nhớ một tiến trình; thêm tiến trình là hạn mức nhân lên theo số tiến trình | Điều kiện chặn khi mở rộng ngang |

---

## 6. Dữ liệu thô

- [`summary.json`](summary.json) — số liệu đã gộp, kèm khoảng dao động từng chỉ số
- [`raw/`](raw/) — 9 file thống kê của 9 lần chạy, đặt tên `u<số người>-r<lần>`

File lịch sử theo giây và báo cáo HTML cố ý không lưu vì dung lượng lớn.
