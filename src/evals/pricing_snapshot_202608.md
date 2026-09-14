# Pricing snapshot — 08/2026

Snapshot này lưu nguồn gốc dữ liệu giá mà SmartRoute Gateway dùng để tính request cost và premium baseline trong [`pricing.yaml`](../gateway/app/config/pricing.yaml). Đây là bằng chứng đầu vào cho báo cáo eval của US-12; kết quả quality được đánh giá riêng trong các báo cáo eval.

- Ngày thu thập: `2026-08-13`
- Đơn vị: USD trên 1.000.000 token
- Mức giá được ghi vào YAML: paid tier, standard/on-demand, text input và text output
- Owner: **Member 2 — Trung Hiếu**

## Đối chiếu model và giá

Các giá trị input/output dưới đây khớp với `input_per_1m_usd` và `output_per_1m_usd` trong `pricing.yaml` tại ngày thu thập.

| Internal ID | Provider | Provider API ID được adapter gửi | Model/version làm mốc giá | Input | Output | Chế độ giá trong YAML | Trạng thái tại ngày thu thập | Ngày thu thập |
|---|---|---|---|---:|---:|---|---|---|
| `gemini-flash-lite` | google | `gemini-flash-lite-latest` | [`gemini-3.1-flash-lite`](https://ai.google.dev/gemini-api/docs/pricing) | $0.25 | $1.50 | Paid, standard, text | Mốc giá đang được Google niêm yết; API ID runtime là alias động | 2026-08-13 |
| `gemini-flash` | google | `gemini-flash-latest` | [`gemini-3.5-flash`](https://ai.google.dev/gemini-api/docs/pricing) | $1.50 | $9.00 | Paid, standard, text | Mốc giá đang được Google niêm yết; API ID runtime là alias động | 2026-08-13 |
| `gemini-pro` | google | `gemini-pro-latest` | [`gemini-2.5-pro`](https://ai.google.dev/gemini-api/docs/pricing), prompt ≤ 200K token | $1.25 | $10.00 | Paid, standard, text, prompt ≤ 200K | Mốc giá đang được Google niêm yết; API ID runtime là alias động | 2026-08-13 |
| `llama-3.3-70b` | groq | `llama-3.3-70b-versatile` | [`llama-3.3-70b-versatile`](https://console.groq.com/docs/models) | $0.59 | $0.79 | Developer plan, on-demand, text | [Dự kiến shutdown 2026-08-16](https://console.groq.com/docs/deprecations) trên free/developer tier | 2026-08-13 |
| `deepseek-r1-distill-llama-70b` | groq | `deepseek-r1-distill-llama-70b` | Giá trị lịch sử đang giữ trong YAML | $0.59 | $0.79 | Historical configured scalar; không phải báo giá hiện hành | [Đã shutdown 2025-10-02](https://console.groq.com/docs/deprecations) | 2026-08-13 |
| `gpt-4o-mini` | openai | `gpt-4o-mini` | [`gpt-4o-mini`](https://developers.openai.com/api/docs/models/gpt-4o-mini) | $0.15 | $0.60 | Paid, standard, text | Model alias và giá được OpenAI Developers niêm yết | 2026-08-13 |
| `gpt-4o` | openai | `gpt-4o` | [`gpt-4o`](https://developers.openai.com/api/docs/models/gpt-4o) | $2.50 | $10.00 | Paid, standard, text | Model alias và giá được OpenAI Developers niêm yết | 2026-08-13 |

### Giới hạn của alias động

Ba Gemini adapter hiện gửi alias có hậu tố `-latest`. Bảng trên ghi đúng API ID runtime và đồng thời ghi model/version được dùng làm mốc giá trong `pricing.yaml`. Alias `-latest` có thể được Google chuyển sang version khác sau ngày thu thập, nên snapshot này không khẳng định alias đó là một version cố định có thể tái lập vĩnh viễn.

### Model Groq đã hoặc sắp ngừng

- Groq đã shutdown `deepseek-r1-distill-llama-70b` ngày `2025-10-02`. Vì provider không còn niêm yết báo giá hiện hành cho model này, `$0.59/$0.79` chỉ là giá trị lịch sử đang tồn tại trong `pricing.yaml`.
- Groq thông báo `llama-3.3-70b-versatile` shutdown ngày `2026-08-16` đối với free/developer tier và khuyến nghị `openai/gpt-oss-120b` hoặc `qwen/qwen3.6-27b`. Enterprise committed-spend không thuộc đợt shutdown này.
- Phạm vi của snapshot chỉ ghi nhận hiện trạng; việc thay model runtime cần một issue thay đổi cấu hình riêng.

## Giá có điều kiện và giả định

`CostCalculator` hiện chỉ nhận một scalar input và một scalar output cho mỗi internal model. Vì vậy nó không tự chọn lại mức giá theo context length, request mode, cache hay modality.

### Google Gemini

- `gemini-2.5-pro` standard có hai ngưỡng theo tổng độ dài prompt:
  - Prompt ≤ 200K token: `$1.25` input và `$10.00` output — đây là mức đang lưu trong YAML.
  - Prompt > 200K token: `$2.50` input và `$15.00` output.
- Với `gemini-2.5-pro`, batch/flex lần lượt là `$0.625/$5.00` khi prompt ≤ 200K và `$1.25/$7.50` khi prompt > 200K. Priority lần lượt là `$2.25/$18.00` và `$4.50/$27.00` cho hai ngưỡng trên.
- Google còn niêm yết mức riêng cho cached input, cache storage, audio, image, grounding, batch, flex, priority và free tier. Các mức đó không được biểu diễn trong `pricing.yaml` và không được áp dụng bởi cost calculator hiện tại.
- `gemini-3.1-flash-lite` có input audio `$0.50`, khác input text/image/video `$0.25` đang lưu trong YAML.

### OpenAI

- Trang model niêm yết cached input của `gpt-4o-mini` là `$0.075` và của `gpt-4o` là `$1.25` trên 1 triệu token.
- YAML dùng standard input, không dùng cached input hoặc Batch API discount. Output đang được tính theo standard text output.

### Groq

- Bảng Supported Models niêm yết giá on-demand theo 1 triệu token. Rate limit của developer plan là giới hạn lưu lượng, không phải một tier giá khác được gateway tính tự động.
- Điều kiện free/developer so với enterprise committed-spend ảnh hưởng lịch shutdown của `llama-3.3-70b-versatile`, không làm thay đổi scalar đang lưu trong snapshot.

## Nguồn chính thức

| Provider | Nguồn giá | Nguồn trạng thái/deprecation | Ngày truy cập |
|---|---|---|---|
| Google | [Gemini Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing) | Cùng trang giá/model | 2026-08-13 |
| Groq | [Supported Models](https://console.groq.com/docs/models) | [Model Deprecation](https://console.groq.com/docs/deprecations) | 2026-08-13 |
| OpenAI | [GPT-4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini), [GPT-4o](https://developers.openai.com/api/docs/models/gpt-4o) | Trạng thái model trên từng trang model | 2026-08-13 |

## Owner và chu kỳ rà soát

**Owner:** Member 2 — Trung Hiếu.

Owner rà soát snapshot vào **tuần đầu mỗi tháng**. Ngoài lịch định kỳ, phải rà soát khi provider thông báo thay đổi giá/deprecation hoặc trước khi chốt một báo cáo eval dùng dữ liệu cost.

Quy trình cập nhật:

1. Mở từng URL chính thức và ghi ngày truy cập mới; không dùng blog, bài tổng hợp hoặc kết quả tìm kiếm làm nguồn.
2. So sánh internal ID trong `models.yaml` và provider API ID trong các adapter với bảng snapshot.
3. So sánh mọi model non-mock cùng `input_per_1m_usd` và `output_per_1m_usd` trong `pricing.yaml` với snapshot.
4. Cập nhật ghi chú về context threshold, request mode, cache, modality và deprecation.
5. Chạy kiểm tra đối chiếu tập model/giá và kiểm tra liên kết từ repository guide.
6. Mô tả mọi thay đổi giá/model trong pull request và yêu cầu ít nhất một reviewer xác nhận nguồn chính thức.
