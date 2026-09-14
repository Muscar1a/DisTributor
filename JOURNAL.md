# Weekly Journal — Team 156 (DisTributor Gateway)

> Ghi lại mỗi tuần: học được gì, khó khăn gì, quyết định gì, kế hoạch tiếp.

---

## Week 1: 03/08/2026 - 09/08/2026

### Mục tiêu tuần này
- [x] Thiết lập Repo, khung API Gateway & Router Mock
- [x] Xây dựng Database Schema & thiết lập Alembic migrations
- [x] Hiện thực hóa cơ chế ghi log 2 pha (ADR-008) & các API quản trị
- [x] Thiết lập Docker stack và CI Gate kiểm tra OpenAPI Contract trên máy self-hosted
- [x] Đảm bảo tương thích API Contract 100% với spec chuẩn của BTC

### Đã hoàn thành
- Khởi tạo khung ứng dụng FastAPI hoàn chỉnh cùng hệ thống adapter cho OpenAI, Gemini, Groq.
- Migrate thành công DB schema PostgreSQL lên Docker chứa 4 bảng dữ liệu nghiệp vụ.
- Đóng gói hoàn chỉnh cơ chế log 2 pha ngầm qua FastAPI `BackgroundTasks` và Endpoint polling `/v1/usage/{request_id}`.
- Cấu hình chạy CI Actions trên máy ảo tự lưu trữ (self-hosted runner) của VinUni AI20K.
- Giải quyết triệt để lỗi breaking changes thông qua `oasdiff`.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Lỗi phân quyền của GitHub PAT khi truy cập Project Board | Nâng cấp phạm vi quyền của token lên đầy đủ nhóm `project` | Đọc/ghi status, start/target date tự động bằng API thành công |
| Lỗi tương thích OpenAPI Spec do kiểu dữ liệu Any/Dict ở FastAPI | Thiết lập kiểu schema cụ thể cho Pydantic models và custom Validation Error handler | Pass hoàn toàn oasdiff breaking check |
| Máy ảo self-hosted runner không tự nhận job contract | Bổ sung trigger `push` vào workflow bên cạnh `pull_request` để tránh chính sách hạn chế của GitHub | Runner tự động nhận job ngay khi commit |

### Bài học
- Thiết lập kiểu dữ liệu chặt chẽ ngay từ đầu giúp tiết kiệm thời gian debug API Contract đáng kể.
- Việc phối hợp giữa AI Researcher và BA về schema dữ liệu của dataset cần được thực hiện sớm để tránh xung đột định dạng JSONL.

### Kế hoạch tuần sau (Tiến tới MVP)
- [x] Tích hợp thuật toán phân loại Classifier V1 và Policy Engine thật vào Orchestrator.
- [ ] Thu thập và gán nhãn tập Gold Dataset (200 prompts) và chạy eval hiệu năng.
- [x] Hoàn thành API Key auth cho Gateway và giới hạn rate limit.

---

## Week 2: 10/08/2026 - 16/08/2026 (Cột mốc MVP)

### Mục tiêu tuần này
- [x] Tích hợp Adapter thực tế (OpenAI Adapter) và hoàn thiện chu trình Orchestrator (`classify` -> `select` -> `fallback`).
- [x] Xây dựng giao diện Chat Playground UI hoàn chỉnh, render Markdown & Math/LaTeX, polling metrics độ trễ & chi phí.
- [x] Thiết lập Database PostgreSQL trên Supabase, xử lý triệt để session management và cơ chế ghi feedback.
- [x] Xử lý toàn bộ các lỗi validation & AC bugs (AC-5.3: `too_many_messages` trả 400 thay vì 422, `context_too_long` giới hạn token > 8000).
- [x] Chuẩn hóa toàn bộ hệ thống test sang PostgreSQL, loại bỏ SQLite để tránh sai lệch môi trường.
- [x] Đóng gói và submit thành công cột mốc MVP (16/08/2026).

### Đã hoàn thành
- Hiện thực hóa `OpenAIAdapter` thực tế và kết nối luồng xử lý hoàn chỉnh trong Orchestrator (`src/gateway/app/api/chat_completions.py`).
- Xây dựng giao diện Playground trực quan: hỗ trợ render định dạng Markdown phong phú, công thức toán học KaTeX, box hiển thị realtime độ trễ (latency), chi phí ước tính (cost), và nút gửi Feedback trực tiếp kèm tags.
- Tích hợp Database Supabase (PostgreSQL) và thiết kế cơ chế lazy-initialization cho SQLAlchemy engine với kỹ thuật double-checked locking để chống crash khi biến môi trường chưa nạp.
- Refactor tầng quản lý database session, viết đầy đủ regression tests cho luồng request logging và feedback.
- Sửa triệt để các lỗi kiểm tra ràng buộc đầu vào (Fix Issue #100, #101, #106): xử lý đúng mã lỗi chuẩn 400 cho payload vượt quá 50 messages và độ dài context vượt quá 8000 tokens.
- Đồng bộ hóa toàn bộ môi trường CI/Test bằng PostgreSQL service container, dọn dẹp toàn bộ dependency SQLite.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Lỗi import-time crash trong CI/Test khi `DATABASE_URL` chưa được nạp vào môi trường lúc khởi tạo module | Thiết kế cơ chế lazy engine initialization với double-checked locking an toàn đa luồng | Ứng dụng khởi động an toàn, DB engine chỉ kết nối khi có request đầu tiên cần truy vấn |
| Sự bất tương thích hành vi giữa SQLite in-memory (khi chạy test local) và PostgreSQL (trên Supabase/Staging) | Loại bỏ hoàn toàn SQLite khỏi codebase, cấu hình PostgreSQL container cho mọi môi trường test | Loại bỏ 100% rủi ro sai lệch cú pháp SQL và kiểu dữ liệu giữa các môi trường |
| Schema Feedback ban đầu chỉ là mock stub, thiếu trường tags và không lưu xuống DB | Bổ sung model DB Feedback, cập nhật Pydantic schema với tags và hoàn thiện API endpoint lưu trữ | Lưu trữ trọn vẹn phản hồi của người dùng về chất lượng câu trả lời |

### Bài học
- Đồng nhất công nghệ database giữa Development, Test và Production ngay từ giai đoạn đầu giúp triệt tiêu hàng loạt lỗi khó debug về sau.
- Việc hiển thị minh bạch thông tin router (model được chọn, chi phí, độ trễ) ngay trên UI giúp việc kiểm thử và đánh giá hành vi định tuyến trực quan hơn rất nhiều.

### Kế hoạch tuần sau (Phát triển tính năng nâng cao & Adaptive Routing)
- [ ] Hiện thực hóa Streaming Response (`stream=True`) qua giao thức Server-Sent Events (SSE).
- [ ] Thiết kế và cài đặt cơ chế định tuyến thích ứng đa lượt (Adaptive Multi-Turn Routing / Session Router).
- [ ] Nâng cấp thuật toán phân loại: Classifier v1.5 (heuristic theo loại việc) và Classifier v2 (LLM-based classifier).
- [ ] Xây dựng cơ chế Client Rate Limiting và quản lý hạn ngạch API theo tầng (Tier).

---

## Week 3: 17/08/2026 - 23/08/2026 (Adaptive Routing, Classifier v1.5/v2 & Rate Limiting)

### Mục tiêu tuần này
- [x] Hiện thực hóa Streaming Response (`stream=True`) chuẩn SSE tương thích OpenAI API.
- [x] Thiết kế & triển khai kiến trúc Adaptive Multi-Turn Routing (`docs/design/08_adaptive_routing.md`) với Session Router và Turn Analyzer.
- [x] Nâng cấp thuật toán phân loại Classifier v1.5 (`docs/design/09_classifier_v1_5.md`) chấm điểm theo bản chất công việc thay vì độ dài từ.
- [x] Triển khai Classifier v2 (`docs/design/12_classifier_v2.md`) sử dụng LLM chấm điểm theo thang L0–L6 kết hợp bảng hằng số định lượng.
- [x] Xây dựng `OutcomeObserver` chạy nền ở Phase 2 log để phân tích chất lượng kết quả và Router Cost Accounting.
- [x] Hiện thực hóa Client Rate Limiting theo Tier (Issue #104 / `docs/design/11_client_rate_limiting.md`).
- [x] Bổ sung Chat History Sidebar và Config Panel trên Playground UI; cập nhật baseline pricing model GPT-5.4.

### Đã hoàn thành
- Phát triển luồng Server-Sent Events (SSE) cho `POST /v1/chat/completions` với `StreamingResponse`, hỗ trợ stream token thời gian thực và đồng bộ hoàn hảo với background logging.
- Xây dựng `SessionRouter` và `TurnAnalyzer`: duy trì trạng thái ngữ cảnh hội thoại qua `sessions.routing_state` (JSONB), áp dụng Exponential Moving Average (EMA) và vùng trễ (hysteresis) để ngăn chặn dao động tier bất hợp lý giữa các lượt chat.
- Hoàn thiện `ClassifierV1_5Heuristic`: tách riêng instruction zone khỏi code fence, chấm điểm dựa trên độ phức tạp bài toán (C1/C2/C3), giải quyết triệt để lỗi under-routing câu ngắn khó (như "Implement Paxos") và over-routing câu dài tâm sự.
- Hiện thực hóa `ClassifierV2LLM`: thiết kế prompt chuẩn hóa nhận diện cấp độ L0–L6, bảo vệ bằng regex guard, sử dụng bảng ánh xạ hằng số cố định để đảm bảo tính tái lập (deterministic calibration) và giải trình minh bạch (explainability).
- Cài đặt `OutcomeObserver` trong background task của phase 2: tự động phát hiện refusal/độ dài bất thường và tính toán chi phí router định tuyến.
- Tích hợp Client Rate Limiting theo hạn ngạch token/request dựa trên Tier của API Key.
- Nâng cấp Playground UI: bổ sung thanh Sidebar lịch sử các phiên chat (History), bảng điều khiển cấu hình tham số routing (Config Panel), và cập nhật giá baseline lên model GPT-5.4.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Classifier v1 chấm điểm dựa vào số từ thô sơ dẫn đến việc câu ngắn khó bị ép về T1 (score 0), còn câu dài dễ bị đẩy lên T2 | Thiết kế Classifier v1.5: phân tích cú pháp vùng chỉ dẫn, lọc bỏ code context và phân loại theo domain công việc | Loại bỏ 100% hiện tượng under-routing các bài toán phân tán/thuật toán phức tạp |
| LLM Classifier nếu để tự do sinh điểm 0–100 sẽ bị trôi dạt (drift) điểm số và không thể kiểm chứng/giải trình | Ràng buộc LLM chỉ trả về bậc L0–L6 theo định nghĩa ngữ nghĩa; ánh xạ bậc ra điểm số bằng bảng hằng số cố định trong code | Đảm bảo tính nhất quán, dễ tinh chỉnh trọng số qua code review mà không cần sửa prompt |
| Nguy cơ Race Condition khi cập nhật đồng thời trạng thái `routing_state` trong phiên hội thoại đa luồng | Rà soát và áp dụng cơ chế cập nhật trạng thái an toàn, thực hiện đợt audit & clean code chuyên sâu | Hệ thống vận hành ổn định, không bị xung đột dữ liệu phiên |
| Tích hợp Streaming Response đồng thời với việc tính toán token usage và ghi log 2 pha | Tách pipeline stream độc lập với background task tính toán usage và chi phí router | Stream mượt mà không làm tăng TTFT (Time to First Token) trong khi vẫn bảo toàn đầy đủ dữ liệu audit log |

### Bài học
- Không nên phụ thuộc vào việc để LLM sinh số tự do trong các bài toán định tuyến; kết hợp "LLM hiểu ngữ nghĩa + Code xác định trọng số" là mô hình tối ưu về cả độ chính xác lẫn tính giải trình.
- Định tuyến đa lượt (multi-turn) cần tách biệt rõ giữa tín hiệu phi trạng thái (stateless signals từ message history) và bộ nhớ phiên có trạng thái (session memory).

### Kế hoạch tuần sau (Hoàn thiện cuối kỳ & Nghiệm thu)
- [ ] Tối ưu hóa UI/UX, sửa các lỗi giao diện nhỏ trên Chat Playground.
- [ ] Rà soát, chuẩn hóa test suite và dọn dẹp các test flaky.
- [ ] Chạy benchmark tổng thể đánh giá độ chính xác phân hạng và hiệu quả tiết kiệm chi phí.
- [ ] Hoàn thiện trọn bộ tài liệu kỹ thuật, slide và kịch bản demo phục vụ báo cáo cuối kỳ.

---

## Week 4: 24/08/2026 - 30/08/2026 (Hoàn thiện sản phẩm & Đóng gói nghiệm thu)

### Mục tiêu tuần này
- [x] Sửa các lỗi giao diện nhỏ trên Playground & trang thống kê Stats.
- [x] Tối ưu hóa độ ổn định của test suite và dọn dẹp code ruff/linting.
- [ ] Thực hiện benchmark đánh giá hiệu năng toàn diện (chi phí tiết kiệm được, tỷ lệ routing chính xác, độ trễ P95).
- [ ] Rà soát toàn bộ tài liệu kiến trúc, ADR và hoàn thiện báo cáo đồ án.
- [ ] Chuẩn bị kịch bản demo trực tiếp và hoàn thiện slide thuyết trình cuối kỳ.

### Đã hoàn thành
- Sửa lỗi căn chỉnh và hiển thị số liệu trên giao diện thống kê `StatsPage.jsx` (`f417740`).
- Tối ưu hóa middleware, sửa triệt để test flaky và chuẩn hóa cú pháp linting với `ruff` trên toàn bộ codebase (`7567705`, `9c6fae8`).
- Hoàn thiện tính năng lưu và khôi phục lịch sử chat nhiều phiên trên giao diện Playground (`f8ea728`, `2102fc4`).
- Tổng hợp các số liệu đo lường thực tế về chi phí và độ trễ phục vụ báo cáo đánh giá.

### Khó khăn & Giải pháp
| Khó khăn | Giải pháp | Kết quả |
|----------|-----------|---------|
| Một số test case API đôi khi bị flaky do timing bất đồng bộ giữa background logging và DB polling | Tinh chỉnh test fixture và đồng bộ hóa các điểm chờ xử lý nền trong bộ test | Test suite chạy ổn định 100%, pass toàn bộ CI pipeline |

### Bài học
- Các báo cáo đánh giá cuối cùng cần số liệu định lượng cụ thể (% chi phí cắt giảm, overhead độ trễ tính bằng ms) để làm nổi bật giá trị cốt lõi của SmartRoute Gateway.

### Kế hoạch tiếp theo
- [ ] Hoàn tất toàn bộ tài liệu nghiệm thu kỹ thuật và slide thuyết trình.
- [ ] Diễn tập kịch bản demo tương tác trực tiếp trước buổi báo cáo nghiệm thu.

