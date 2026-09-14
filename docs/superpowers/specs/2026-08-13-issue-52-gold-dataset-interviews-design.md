# Thiết kế Gold Dataset và phỏng vấn developer cho issue #52

## Mục tiêu

Tạo bộ 200 prompt thực tế, song ngữ Việt–Anh, có provenance và nhãn độ khó để phục vụ kiểm chứng H1, đồng thời chuẩn bị quy trình phỏng vấn 3–5 developer để kiểm chứng H3 và nhu cầu routing logs. Thiết kế phải hỗ trợ handoff trực tiếp sang mini-eval của issue #49 mà không tạo hai schema khác nhau.

Không được gọi dữ liệu AI hỗ trợ là “gold” hoặc tuyên bố H3 đã được kiểm chứng trước khi có xác nhận của người thật.

## Phạm vi và trạng thái hoàn thành

Phần có thể hoàn thành ngay:

- Thay bộ dữ liệu mẫu hai dòng bằng 200 prompt thực, 100 tiếng Việt và 100 tiếng Anh.
- Lưu nguồn, revision, giấy phép và record ID cho từng prompt.
- Gán nhãn đề xuất Easy/Medium/Hard theo rubric độc lập với classifier runtime.
- Tạo validator, tài liệu nguồn, tài liệu schema và bảng review nhãn.
- Tạo interview guide cùng file nhập phản hồi ẩn danh.
- Cập nhật `src/evals/report.md` với thống kê H1 sơ bộ và trạng thái H3.
- Gửi schema đề xuất cho Member 1 tại issue #49 để thực hiện critical sync.

Hai điều kiện bên ngoài còn bắt buộc:

1. Một người phải duyệt đủ 200 nhãn và chuyển trạng thái từng dòng sang `human_verified` hoặc `human_revised`. Trước đó dataset chỉ là bản nháp AI-assisted, chưa phải Gold Dataset hoàn chỉnh theo AC-1.
2. Phải có tối thiểu ba phản hồi developer có consent. Trước đó AC-2 và phần H3 của AC-3 vẫn ở trạng thái chờ; không được tạo dữ liệu phỏng vấn giả.

## Lựa chọn nguồn dữ liệu

### Nguồn được chọn

Sử dụng `allenai/WildChat-1M` trên Hugging Face, ghim revision:

```text
7d6490e462285cf85d91eabea0f9a954fbddcd1f
```

Lý do:

- Là hội thoại giữa người dùng thật và ChatGPT, phù hợp hơn dataset instruction tổng hợp để khảo sát phân bố request.
- Có tiếng Việt và tiếng Anh; kiểm tra thử 5.000 record đầu tìm thấy 14 hội thoại tiếng Việt.
- Dataset card công bố phiên bản này đã loại hội thoại độc hại, loại các hội thoại PII/sensitive đã được phát hiện, và dữ liệu đã được de-identify.
- Giấy phép `ODC-BY`, cho phép tạo và phân phối derivative database khi giữ attribution/license notice.
- Nguồn không yêu cầu chấp nhận điều khoản gated như LMSYS-Chat-1M.

URL chính thức:

- Dataset: `https://huggingface.co/datasets/allenai/WildChat-1M`
- License: `https://opendatacommons.org/licenses/by/1-0/`

### Nguồn đã khảo sát nhưng không đưa vào mẫu H1

- LMSYS Chatbot Arena trên Hugging Face/Kaggle: dữ liệu thực và đã khử PII, nhưng bản canonical cần chấp nhận điều khoản riêng; điều khoản LMSYS cấm chuyển dataset cho bên thứ ba. Không dùng mirror để lách điều khoản.
- Databricks Dolly 15K: human-generated, giấy phép rõ, nhưng là instruction được nhân viên chủ động sáng tác và chỉ có tiếng Anh; không đại diện traffic thực.
- Google Natural Questions: query tìm kiếm thực có đáp án, nhưng chỉ phản ánh QA tiếng Anh.
- UIT-ViQuAD 2.0: QA tiếng Việt do annotator tạo từ Wikipedia; phù hợp full eval có ground truth, không phù hợp đo phân bố request thực.
- GSM8K và MBPP: có đáp án/test tốt cho toán và code, nhưng là benchmark được crowdsource, không phải traffic ứng dụng.

Các nguồn trên được ghi trong tài liệu provenance để Member 1 có thể dùng ở giai đoạn mở rộng nhóm chấm tự động, nhưng không trộn vào mẫu kiểm chứng H1.

## Thiết kế lấy mẫu

Script lấy mẫu đọc WildChat ở chế độ streaming với revision cố định và seed `52`. Không commit cache hoặc dữ liệu nguồn đầy đủ.

Điều kiện ứng viên:

1. `language` là `English` hoặc `Vietnamese`.
2. `toxic == false`.
3. Lấy nội dung ở user turn đầu tiên để prompt không phụ thuộc lịch sử hội thoại bị thiếu.
4. Prompt sau khi trim không rỗng và không vượt giới hạn 16.000 token ước lượng của gateway.
5. Loại prompt trùng nhau sau khi normalize whitespace và Unicode.
6. Loại prompt chứa email, số điện thoại, địa chỉ IP, private key hoặc credential rõ ràng; sau lọc tự động vẫn phải review bằng mắt.
7. Loại request phụ thuộc ảnh/audio/file không có trong bản ghi, vì gateway MVP là text-only.

Để giảm bias thứ tự mà không phải tải toàn bộ 3,36 GB, script thu 200 ứng viên hợp lệ cho mỗi ngôn ngữ từ stream đã ghim, sau đó dùng `random.Random(52).sample(..., 100)`. Báo cáo phải ghi rõ đây là mẫu phân tầng 50/50 theo ngôn ngữ; kết quả H1 chỉ áp dụng cho quần thể eval song ngữ cân bằng này, không đại diện tỷ lệ ngôn ngữ tự nhiên của WildChat hay traffic production.

## Schema JSONL dùng chung

Mỗi dòng trong `src/evals/datasets/mixed_200.jsonl` là một JSON object với các field bắt buộc:

```json
{
  "id": "wc-vi-001",
  "prompt": "...",
  "language": "vi",
  "category": "factual_qa",
  "difficulty": "easy",
  "expected_tier": "T1",
  "source_dataset": "allenai/WildChat-1M",
  "source_revision": "7d6490e462285cf85d91eabea0f9a954fbddcd1f",
  "source_record_id": "<conversation_hash>:<turn_identifier>",
  "source_url": "https://huggingface.co/datasets/allenai/WildChat-1M",
  "license": "ODC-BY-1.0",
  "pii_review_status": "pending_human_review",
  "annotation_status": "ai_assisted_pending_human_review",
  "annotator": "codex-draft",
  "annotation_notes": ""
}
```

Quy ước:

- `language`: `vi | en`.
- `difficulty`: `easy | medium | hard`.
- `expected_tier`: ánh xạ cố định `easy -> T1`, `medium -> T2`, `hard -> T3`.
- `category`: `chitchat`, `factual_qa`, `explanation`, `translation`, `summarization`, `information_extraction`, `writing`, `coding`, `math_reasoning`, `analysis_planning`, hoặc `other`.
- `pii_review_status`: `pending_human_review | human_verified`.
- `annotation_status`: `ai_assisted_pending_human_review | human_verified | human_revised`.
- `annotator`: alias không chứa tên hoặc email cá nhân. Khi human review, dùng alias reviewer đã thống nhất.
- `annotation_notes`: bắt buộc có lý do ngắn khi status là `human_revised`; trường hợp khác có thể rỗng.

Các field cốt lõi `prompt`, `expected_tier`, `category` đáp ứng schema tối thiểu được issue #49 đề xuất; field bổ sung phục vụ provenance và gold-review. Member 1 có thể đọc thừa field mà không ảnh hưởng runner.

## Rubric gán nhãn

Rubric đo năng lực cần để trả lời tốt, không bắt chước điểm số của `ClassifierV1Heuristic`:

- **Easy / T1:** chitchat; lệnh ngắn; fact đơn giản; rewrite/translation/extraction trực tiếp; không cần suy luận nhiều bước hoặc kiến thức chuyên sâu.
- **Medium / T2:** giải thích có cấu trúc; viết nội dung mức vừa; tóm tắt; phân tích một bước; code/math cơ bản; một vài ràng buộc đầu ra.
- **Hard / T3:** suy luận nhiều bước; debug/thiết kế code không tầm thường; toán phức tạp; phân tích chuyên môn; prompt dài hoặc nhiều ràng buộc phụ thuộc nhau.

Khi phân vân giữa hai mức, chọn mức cao hơn để bảo vệ quality. Nhãn do Codex tạo chỉ là đề xuất. Human reviewer đọc prompt và rubric, giữ hoặc sửa difficulty/category, cập nhật `expected_tier`, rồi đặt status tương ứng.

## Validator và review workflow

Thêm `src/evals/validate_dataset.py` dùng Python standard library, không thêm dependency. Validator kiểm tra:

- JSON hợp lệ, đúng 200 dòng, ID và source record duy nhất.
- Đúng 100 `vi` và 100 `en`.
- Enum/schema hợp lệ và mapping difficulty-tier chính xác.
- Mọi dòng cùng source/revision/license đã ghim.
- Không có prompt rỗng/trùng và không khớp các pattern PII/secret cơ bản.
- Thống kê phân bố difficulty/category/language.

Chế độ mặc định cho phép trạng thái review đang chờ nhưng in số lượng pending. Flag `--require-gold` phải fail cho đến khi cả `pii_review_status` và `annotation_status` đã được người thật xác nhận. Đây là bằng chứng không thể vô tình gọi bản nháp là gold.

Tạo `src/evals/datasets/annotation_review.md` hướng dẫn review theo batch, kèm lệnh validator sau mỗi batch. Không sao chép 200 prompt sang file thứ hai để tránh drift.

## Phỏng vấn developer

Tạo `src/evals/interviews/developer_interview_guide.md` gồm:

- Script xin consent và cam kết chỉ lưu dữ liệu tổng hợp/ẩn danh.
- Thông tin nền ở dạng band: vai trò, số năm kinh nghiệm, tần suất tích hợp LLM.
- Ngưỡng routing overhead chấp nhận: `<100`, `100–300`, `301–500`, `501–1000`, `>1000` ms.
- Câu hỏi về latency end-to-end hiện tại, tình huống nhạy latency và trade-off cost/quality.
- Danh sách routing log mong muốn: request ID, timestamp, tier, score, signals/reason, policy, selected model/provider, fallback chain, latency, token, cost, error, content redaction.
- Câu hỏi mở về nỗi lo privacy/debugging.

Tạo `src/evals/interviews/responses.csv` chỉ có header, tuyệt đối không thêm dòng giả. Dùng `participant_id` dạng `DEV-01`; không lưu tên, email, công ty hoặc raw transcript. Chỉ ghi dòng khi người tham gia đồng ý cho tổng hợp ẩn danh.

Khi có ít nhất ba phản hồi hợp lệ, báo cáo H3 công bố median/mode band và số người chấp nhận overhead `<300ms`, cùng top log fields. Với mẫu nhỏ, chỉ mô tả định tính; không suy rộng thống kê ra toàn bộ developer.

## Báo cáo H1/H3

`src/evals/report.md` có các phần:

1. Dataset provenance và sampling limitations.
2. Phân bố difficulty tổng và tách theo ngôn ngữ.
3. Tỷ lệ `easy + medium` so với giả thuyết H1 `60–70%`.
4. Trạng thái human review; trước khi review xong, kết luận ghi “preliminary, chưa đủ để xác nhận H1”.
5. Số người phỏng vấn, phân bố latency threshold và routing-log preferences.
6. Trước khi đủ ba người, H3 ghi “not tested”; không dùng dữ liệu rỗng để kết luận.
7. Limitations và next steps cho issue #49/full eval.

## Đồng bộ với Member 1

Trước khi coi schema là khóa, đăng một bình luận tại issue #49, tag `@hungtranvg62`, gồm:

- Link tới design spec.
- Danh sách field và enum.
- Mapping difficulty-tier.
- Quy tắc `mixed_50.jsonl` phải là subset theo `id`, không copy/rewrite prompt.
- Đề nghị Member 1 xác nhận hoặc nêu thay đổi schema.

Nếu Member 1 yêu cầu thay đổi breaking, cập nhật spec/schema trước khi tạo `mixed_50.jsonl`. Việc tạo runner và subset 50 thuộc issue #49, không nằm trong phạm vi triển khai issue #52.

## File tạo và sửa

- Replace: `src/evals/datasets/mixed_200.jsonl`
- Create: `src/evals/datasets/schema.json`
- Create: `src/evals/datasets/sources.md`
- Create: `src/evals/datasets/annotation_review.md`
- Create: `src/evals/build_mixed_200.py`
- Create: `src/evals/validate_dataset.py`
- Create: `src/evals/tests/test_dataset_tools.py`
- Create: `src/evals/interviews/developer_interview_guide.md`
- Create: `src/evals/interviews/responses.csv`
- Modify: `src/evals/report.md`

Không sửa classifier, adapter, gateway runtime, pricing hoặc file thuộc issue #49.

## Kiểm thử và tiêu chí bàn giao

Kiểm tra tự động:

- Unit test cho normalize/filter, deterministic sampling metadata, PII patterns và validator schema.
- Build script tạo đúng 200 record từ revision đã ghim khi có network.
- Validator thường pass và báo chính xác số pending.
- `--require-gold` fail trước human review, sau đó phải pass khi toàn bộ nhãn được người thật duyệt.
- Responses validator/report không được coi AC-2 đạt khi có dưới ba consented participants.

Trạng thái issue chỉ được gọi hoàn thành khi đồng thời:

1. Dataset có 200 prompt và strict gold validation pass.
2. Có tối thiểu ba phản hồi phỏng vấn thật.
3. Report cập nhật H1/H3 từ dữ liệu đã xác minh.
4. Member 1 đã nhận schema/handoff trên issue #49.

Trước các điều kiện này, bàn giao phải ghi rõ phần đã hoàn tất và phần đang chờ con người, không đóng issue #52.
