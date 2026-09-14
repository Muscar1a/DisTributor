# 🎬 Kịch Bản Video Demo — SmartRoute AI Gateway (Bản Đầy Đủ: Playground, AI Logs & Dashboard)

> **Sự kiện:** Demo Day — VinUni AI20K Build Phase (Cohort 3)
> **Dự án:** SmartRoute AI Gateway (Team 156 — P-156)
> **Thời lượng mục tiêu:** 3 phút 45 giây – 4 phút (Độ phân giải 1080p HD)
> **Đáp ứng 100% Checklist BTC:** Giới thiệu Team, Live Demo Playground, AI Logs Telemetry, Admin Dashboard & API Keys, Bằng chứng Evals.

---

## ⏱️ Timeline & Phân Đoạn Kịch Bản

```
[00:00 - 00:30]  Phần 1: Giới thiệu Team 156 & Vấn đề thực tế (Problem Statement)
[00:30 - 01:25]  Phần 2: Live Demo Playground — Định tuyến tự động (T1 → T3) & Force Tier
[01:25 - 02:00]  Phần 3: Trình diễn AI Logs — Two-Phase Logging & Truy vết Request ID
[02:00 - 02:45]  Phần 4: Trình diễn Admin Dashboard — Giám sát KPIs Chi phí & Quản trị API Keys
[02:45 - 03:25]  Phần 5: Bằng chứng Đánh giá Evals (1,084 tasks · 98.7% số câu đúng của GPT-4o)
[03:25 - 03:50]  Phần 6: Tổng kết Kiến trúc Hạ tầng & Outro
```

---

### PHẦN 1: Giới thiệu & Vấn đề (00:00 – 00:30)

* **Màn hình quay:** Slide Title của Team 156 hoặc camera giới thiệu nhóm.
* **Lời thoại (Voice-over):**
  > *"Xin chào Ban Giám Khảo, chúng tôi là **Team 156** với sản phẩm **SmartRoute AI Gateway**.*
  > *Hiện nay, các doanh nghiệp thường lãng phí hơn 70% chi phí khi phải gọi các mô hình Frontier đắt đỏ cho những câu hỏi đơn giản, đồng thời đối mặt với rủi ro nghẽn Rate Limit và gián đoạn dịch vụ. Hôm nay, chúng tôi xin trình diễn SmartRoute — cổng định tuyến thông minh chuẩn OpenAI API, giúp tiết kiệm hơn 80% chi phí trong lần benchmark hoàn tất gần nhất, đồng thời duy trì chất lượng gần mức model cao cấp."*

---

### PHẦN 2: Live Demo Playground — Định Tuyến Tự Động & Force Tier (00:30 – 01:25)

* **Màn hình quay:** Giao diện **Playground** trên React Dashboard (kết nối trực tiếp với Gateway).

#### 📍 Thao tác 1 (Prompt đơn giản → Kích hoạt Tier 1):
* **Hành động:** Nhập câu hỏi: `"Chào SmartRoute, giải thích ngắn gọn 3 lợi ích của API Gateway."` → Bấm **Send request**.
* **Quan sát:** Phản hồi tức thì, Routing metadata hiển thị: `Tier: T1 (Easy)`, `Model: gemini-flash` / `gpt-5.4-nano`, `Router Latency: 0.50 ms`, `Cost: $0.000008`.
* **Lời thoại:**
  > *"Tại Playground, với câu hỏi thông thường, bộ phân loại Classifier v1.5 nhận diện tín hiệu Fast-path trong đúng 0.5 mili-giây và điều phối tới mô hình Tier 1 Gemini Flash với chi phí gần như bằng 0."*

#### 📍 Thao tác 2 (Prompt khó & Tính năng Force Tier Override):
* **Hành động:** Nhập bài toán lập trình đa luồng: `"Viết class TokenBucketRateLimiter bằng Python thread-safe và 3 unit tests pytest."` → Cho thấy hệ thống tự động nhảy lên `Tier: T3`, gọi `gpt-4o`/`gpt-5.4`.
  *Thao tác thêm:* Đổi dropdown **Force tier** sang `T2` để chứng minh khả năng can thiệp thủ công của lập trình viên.
* **Lời thoại:**
  > *"Với bài toán code phức tạp, hệ thống tự động đẩy lên Tier 3 sử dụng Frontier Model mạnh nhất. Lập trình viên cũng có thể chủ động dùng tính năng Force Tier hoặc đổi chính sách Balanced / Cost-first tùy theo nhu cầu."*

---

### PHẦN 3: Trình Diễn AI Logs — Two-Phase Telemetry & Truy Vết (01:25 – 02:00)

* **Màn hình quay:** Màn hình **Terminal Backend Logs** hoặc tab hiển thị chi tiết **Routing Metadata & Request ID** (`/v1/usage/{request_id}`).
* **Hành động:**
  - Copy `request_id` từ kết quả Playground vừa chạy (ví dụ: `3b2e7527-...`).
  - Mở Terminal / log server: Chỉ vào dòng log JSON-lines có chứa `request_id`, `difficulty_score`, `signals: ["code", "length"]`, `actual_cost_usd`, `latency_router_ms: 0.5ms`.
  - Giải thích cơ chế: Ghi đồng bộ bản ghi `pending` trước khi trả kết quả, sau đó cập nhật token và chi phí ngầm ở background (Two-Phase Logging).
* **Lời thoại:**
  > *"Mọi quyết định định tuyến đều được minh bạch hóa 100% qua hệ thống **AI Logs**. Mỗi request được cấp một `request_id` duy nhất. Nhờ cơ chế Two-Phase Logging, hệ thống ghi nhận bản ghi tức thì mà không làm nghẽn luồng stream, sau đó tự động cập nhật chính xác số lượng token, chi phí thực tế và các tín hiệu phân loại trong cơ sở dữ liệu."*

---

### PHẦN 4: Trình Diễn Admin Dashboard — Giám Sát Chi Phí & Quản Trị API Keys (02:00 – 02:45)

* **Màn hình quay:** Chuyển sang các tab quản trị trên Dashboard.

#### 📍 Thao tác 1 (Giám sát KPIs & Biểu đồ Chi phí):
* **Hành động:** Mở trang **Analytics / Stats**:
  - Chỉ chuột vào các thẻ chỉ số: **Total Requests**, **Total Cost Saved ($)**, **Savings % (ví dụ: 86.7%)**, và **Average Router Latency (0.50 ms)**.
  - Xem biểu đồ phân bố lưu lượng theo Tier (T1 vs T2 vs T3) và theo Provider.
* **Lời thoại:**
  > *"Trên giao diện Admin Dashboard, nhà quản lý có cái nhìn toàn cảnh về tổng số tiền tiết kiệm được theo thời gian thực, tỷ lệ phân bổ giữa các mô hình và độ trễ trung bình của toàn hệ thống."*

#### 📍 Thao tác 2 (Quản trị & Cấp phát API Keys):
* **Hành động:** Chuyển sang tab **API keys**:
  - Tạo key mới: Nhập tên `production-app`, đặt hạn ngạch Rate Limit `RPM: 60` → Bấm **Create key**.
  - Xem **Key Reveal Banner** (bảo mật hiển thị đúng 1 lần duy nhất).
  - Bấm **Revoke** một key cũ → Chuyển sang trạng thái `Revoked` (màu đỏ).
* **Lời thoại:**
  > *"Tại tab Quản trị API Keys, quản trị viên dễ dàng cấp phát key cho từng ứng dụng, thiết lập hạn ngạch Rate Limit (RPM) độc lập và thu hồi quyền truy cập tức thì với chuẩn bảo mật Zero-retrieval."*

---

### PHẦN 5: Minh Chứng Chất Lượng Evals Quốc Tế (02:45 – 03:25)

* **Màn hình quay:** Chiếu bảng kết quả thực nghiệm chuẩn quốc tế (**MMLU-Pro, HumanEval+ & MATH-500**).
* **Lời thoại (Voice-over):**
  > *"Trong lần kiểm chuẩn answer-quality hoàn tất gần nhất trên **1,084 bài toán MMLU-Pro, HumanEval+ và MATH-500**, SmartRoute trả lời đúng **631 câu so với 639 câu của GPT-4o** — tương đương **98.7% số câu đúng** — trong khi giảm chi phí từ **3.065 đô xuống 0.430 đô, tiết kiệm 85.96%**.*
  > *Trên HumanEval+ và MATH-500, SmartRoute đạt điểm ước lượng lần lượt **87.20%** và **64.80%**. Chúng tôi trình bày đây là kết quả cạnh tranh về chất lượng ở chi phí thấp hơn, không khẳng định ưu thế thống kê tuyệt đối so với GPT-4o.*
  > *Router thế hệ mới tiếp tục giảm under-routing, latency và router cost; full answer-quality rerun là bước xác nhận tiếp theo trước khi cập nhật tuyên bố sản phẩm."*

---

### PHẦN 6: Tổng Kết Kiến Trúc & Outro (03:25 – 03:50)

* **Màn hình quay:** Sơ đồ kiến trúc hệ thống và link GitHub của Team 156.
* **Lời thoại (Voice-over):**
  > *"Hệ thống hiện đã được Docker hóa hoàn chỉnh, kết nối Supabase Postgres và triển khai sẵn sàng trên Vercel và Render. Toàn bộ mã nguồn, tài liệu ADR và bộ Eval Harness đã sẵn sàng tại GitHub.*
  > *SmartRoute — Tối ưu chi phí, nâng tầm tin cậy cho ứng dụng AI của bạn. Cảm ơn Ban Giám Khảo và các bạn đã lắng nghe!"*

---

### 📋 Checklist quay video nghiệm thu:
- [ ] Thời lượng video từ **3 phút 30 giây đến 4 phút**.
- [ ] Có đầy đủ cả 5 phần: **Playground → AI Logs → Admin Dashboard & Keys → Evals Evidence → Outro**.
- [ ] Âm thanh rõ ràng, video độ phân giải **1080p (Full HD)**.
- [ ] Upload video lên **YouTube** (chế độ *Unlisted* hoặc *Public*) và gắn link vào `README.md`.
