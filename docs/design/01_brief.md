# Project Brief — DisTributor Gateway
**AI Agent Gateway định tuyến đa nhà cung cấp theo độ khó của yêu cầu, tối ưu chi phí & chất lượng**

| | |
|---|---|
| **Phiên bản** | v1.1 — Gate 1 (cập nhật theo review mentor) |
| **Ngày** | 05/08/2026 |

## 1. Vấn đề
Chi phí API giữa model rẻ và model cao cấp chênh lệch **20–100 lần** (theo bảng giá công bố của các provider). Trong thực tế, phần lớn request của người dùng là câu hỏi đơn giản (chào hỏi, tra cứu, tóm tắt ngắn) — không cần model đắt nhất. Hai chiến lược phổ biến đều kém tối ưu:
- **Dùng model cao cấp cho mọi request** → lãng phí chi phí nghiêm trọng.
- **Dùng model rẻ cho mọi request** → chất lượng sụt giảm ở các tác vụ khó (code, toán, suy luận đa bước).

Ngoài ra, phụ thuộc một nhà cung cấp duy nhất gây rủi ro: quá tải, đổi giá, downtime.

> Hai con số trên là **giả thuyết (H1: tỉ lệ request dễ/trung bình, H2: mức chênh giá)**. H2 đã có bằng chứng sơ bộ từ khảo sát bảng giá 08/2026 (model rẻ ~$0.10–0.14/1M input vs frontier $5/1M input, $25–30/1M output); H1 sẽ được kiểm chứng ở M1 bằng log ≥200 request thật + phỏng vấn 3–5 developer. Chi tiết & kế hoạch kiểm chứng: PRD §1.1.

## 2. Giải pháp
**DisTributor Gateway** — một gateway trung gian giữa ứng dụng và các LLM provider:
1. **Tương thích tập con text-only của API OpenAI** (`/v1/chat/completions`) → tích hợp chỉ bằng cách đổi `base_url`, không sửa code client; phạm vi tham số hỗ trợ khai báo rõ (PRD §1.5).
2. **Phân loại độ khó** mỗi request (v1: heuristic scoring; v2: classifier LLM/embedding) thành 3 tier: Easy / Medium / Hard.
3. **Định tuyến theo policy** (cost-first / quality-first / balanced) đến model phù hợp của từng tier, trên **2 provider thật (Gemini, Groq) + 1 mock ở MVP** — mở rộng ≥3 (OpenAI/Anthropic/Ollama) sau khi vertical slice ổn định.
4. **Fallback tự động** khi provider lỗi/quá tải; ghi log đầy đủ chi phí, độ trễ, quyết định routing.
5. **Dashboard** theo dõi chi phí tiết kiệm, phân bố tier, và cấu hình routing.

## 3. Mục tiêu & chỉ số thành công (đo trên bộ eval ~200 prompt hỗn hợp)
| Chỉ số | Mục tiêu | Cách đo |
|---|---|---|
| Tiết kiệm chi phí | **≥ 40%** so với baseline all-premium | Tổng cost eval set: router vs all-premium |
| Giữ chất lượng | **QR ≥ 0.95** | Công thức Quality Retention (accuracy + LLM-as-judge có trọng số), kèm guard riêng QR_hard ≥ 0.90 — PRD §9.3 |
| Overhead định tuyến | **p95 < 300ms** (heuristic) | Đo latency riêng khâu classify + route |
| Độ tin cậy | ≥ 99% request thành công | Fallback đa provider; measurement protocol (denominator, loại lỗi được tính): PRD §9.4 |

## 4. Phạm vi
- **Trong phạm vi:** Gateway API (text-only subset), classifier độ khó, policy engine, 2 adapter thật + 1 mock (mở rộng ≥3), fallback, logging + tính cost, playground test, dashboard, bộ eval + báo cáo.
- **Ngoài phạm vi:** fine-tune model lớn, hệ thống billing/thanh toán thật, multi-tenant enterprise, SLA production; tool calling, đầu vào đa phương thức (ảnh/audio), structured output — ngoài MVP (PRD §1.5).

## 5. Người dùng mục tiêu
- **Developer/startup** tích hợp LLM muốn giảm chi phí mà không đổi code.
- **Admin/PM** cần quan sát chi phí và kiểm soát chất lượng theo policy.

## 6. Giải pháp kỹ thuật (tóm tắt)
Python **FastAPI** + PostgreSQL + React dashboard + Docker. Tham khảo hướng nghiên cứu RouteLLM (LMSYS) cho router học máy ở v2.


## 7. Rủi ro chính
(1) Classifier route sai task khó vào model rẻ → ngưỡng bảo thủ + cơ chế escalation. (2) Quota/thay đổi API provider → dùng free tier (Groq, Gemini), Ollama local, mock adapter. (3) Chi phí chạy eval → giới hạn eval set, cache, free tier.

*Chi tiết đầy đủ: xem `02_prd.md`.*
