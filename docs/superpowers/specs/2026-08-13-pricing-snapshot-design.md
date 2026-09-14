# Thiết kế pricing snapshot tháng 08/2026

## Mục tiêu

Hoàn thành phần tài liệu của issue #47 để reviewer có thể truy xuất nguồn gốc các mức giá đang được dùng trong `src/gateway/app/config/pricing.yaml`. Snapshot phải giúp đối chiếu chi phí trong báo cáo eval mà không thay đổi hành vi runtime của gateway.

## Phạm vi

Thay đổi chỉ gồm tài liệu:

- Thêm `src/evals/pricing_snapshot_202608.md`.
- Cập nhật `docs/guide/cost-management.md` để liên kết snapshot và mô tả quy trình cập nhật.
- Không sửa `pricing.yaml`, `models.yaml`, adapter, routing, cost calculator hoặc test runtime.

## Nội dung snapshot

Snapshot dùng ngày thu thập `2026-08-13` và bao phủ mọi model non-mock hiện có trong `pricing.yaml`. Bảng đối chiếu chính có các cột sau:

1. ID model nội bộ.
2. Nhà cung cấp.
3. Model ID/alias thực tế được adapter gửi tới provider.
4. Model/version được dùng làm mốc giá.
5. Giá input và output theo USD trên 1 triệu token.
6. Chế độ giá được ghi vào YAML.
7. Trạng thái hỗ trợ tại ngày thu thập.
8. URL nguồn chính thức.
9. Ngày thu thập.

Các ánh xạ cần ghi nhận:

| Internal ID | Provider API ID hiện tại | Mốc giá |
|---|---|---|
| `gemini-flash-lite` | `gemini-flash-lite-latest` | `gemini-3.1-flash-lite` |
| `gemini-flash` | `gemini-flash-latest` | `gemini-3.5-flash` |
| `gemini-pro` | `gemini-pro-latest` | `gemini-2.5-pro`, ngưỡng prompt không quá 200K token |
| `llama-3.3-70b` | `llama-3.3-70b-versatile` | cùng model ID |
| `deepseek-r1-distill-llama-70b` | `deepseek-r1-distill-llama-70b` | giá trị lịch sử đang được giữ trong YAML |
| `gpt-4o-mini` | `gpt-4o-mini` | cùng model ID |
| `gpt-4o` | `gpt-4o` | cùng model ID |

Snapshot phải nói rõ các alias Gemini có hậu tố `-latest` là alias động. Vì phạm vi này không sửa adapter, snapshot ghi cả alias runtime và model/version làm mốc giá để reviewer nhìn thấy giới hạn tái lập thay vì hiểu nhầm alias là version cố định.

## Quy ước và giá có điều kiện

`pricing.yaml` biểu diễn một cặp giá scalar cho mỗi model. Snapshot định nghĩa các scalar này là giá paid-tier, standard/on-demand, text-token, USD trên 1 triệu token. Giá batch, flex, priority, cached input, cache storage, audio, image, grounding và free tier không được dùng bởi `CostCalculator`; chúng được ghi chú riêng để tránh nhầm lẫn.

Đối với `gemini-2.5-pro`, YAML dùng mức standard dành cho prompt không quá 200K token: `$1.25` input và `$10.00` output. Snapshot phải ghi thêm mức trên 200K token là `$2.50` input và `$15.00` output, đồng thời nêu rõ cost calculator hiện không tự chuyển mức giá theo độ dài context.

Đối với model Groq đã hoặc sắp ngừng cung cấp, snapshot vẫn hiển thị đúng giá trị trong YAML để thỏa điều kiện đối chiếu, nhưng gắn trạng thái rõ ràng:

- `deepseek-r1-distill-llama-70b` đã ngừng cung cấp; không gọi giá trong YAML là giá hiện hành.
- `llama-3.3-70b-versatile` dự kiến ngừng ngày `2026-08-16` cho free/developer tier; snapshot liên kết trang deprecation chính thức.

## Nguồn dữ liệu

Chỉ sử dụng trang chính thức của nhà cung cấp:

- Google AI for Developers: trang Gemini API pricing.
- GroqDocs: Supported Models và Model Deprecation.
- OpenAI Developers: trang model `gpt-4o-mini` và `gpt-4o`.

Mỗi hàng trong bảng phải có URL trực tiếp tới trang hỗ trợ mức giá hoặc trạng thái model. Không dùng blog, bài tổng hợp hoặc kết quả tìm kiếm làm nguồn.

## Owner và quy trình cập nhật

Owner của snapshot là Member 2, hiện tại là Trung Hiếu. Owner thực hiện rà soát vào tuần đầu mỗi tháng và rà soát ngoài lịch khi provider gửi thông báo đổi giá/deprecation hoặc trước khi chốt một báo cáo eval.

Quy trình cập nhật:

1. Mở từng URL chính thức và ghi ngày kiểm tra mới.
2. So sánh model ID/alias trong adapter và `models.yaml` với snapshot.
3. So sánh mọi model non-mock và hai trường giá trong `pricing.yaml` với bảng snapshot.
4. Cập nhật ghi chú tier/threshold, batch/cache và deprecation.
5. Chạy kiểm tra đối chiếu tài liệu với YAML.
6. Ghi thay đổi giá/model trong pull request và yêu cầu một reviewer xác nhận nguồn.

## Xác minh

Việc nghiệm thu tài liệu gồm:

- Tập internal ID non-mock trong snapshot bằng đúng tập internal ID non-mock trong `pricing.yaml`.
- Giá input/output của từng hàng bằng đúng giá trị YAML.
- Mỗi hàng có provider, API ID, mốc model/version, đơn vị, URL chính thức và ngày thu thập.
- Các điều kiện giá của Gemini 2.5 Pro và trạng thái deprecation của Groq được nêu rõ.
- Guide có liên kết tương đối hợp lệ tới snapshot và có checklist cập nhật.

Không thực hiện request thật tới provider và không phát sinh chi phí API trong quá trình xác minh.
