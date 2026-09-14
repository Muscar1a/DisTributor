# DisTributor — Mô tả Dự án

## 1. Bài toán (Problem)

* **Chi phí AI quá đắt nếu dùng sai model:** Model AI cao cấp (GPT-5.4, GPT-4o) đắt gấp **10–50 lần** model nhỏ. Nhưng hơn 70% câu hỏi hàng ngày chỉ là việc đơn giản — dùng model đắt cho chúng là lãng phí tiền.

* **Dùng model rẻ cho mọi thứ thì chất lượng kém:** Model nhỏ không xử lý nổi bài toán phức tạp — sai logic, sinh bug, hallucination.

* **Phụ thuộc một nhà cung cấp là rủi ro:** Khi nhà cung cấp sập hoặc hết quota, toàn bộ ứng dụng ngừng hoạt động.

---

## 2. Giải pháp kỹ thuật (Technical Solution)

**DisTributor** là cổng trung gian thông minh, tự động chọn model AI phù hợp cho từng câu hỏi:

* **Không cần sửa code:** Chỉ đổi một dòng địa chỉ server — mọi ứng dụng đang dùng OpenAI API hoạt động ngay với DisTributor.

* **Tự động phân loại độ khó trong <1ms, chi phí $0:**
  * **Dễ (T1):** Tra cú pháp, viết docstring, hello world → gửi tới model rẻ nhất ($0.05–$0.25/1M tokens).
  * **Trung bình (T2):** Viết unit test, refactor, debug lỗi thông thường → gửi tới model tầm trung ($0.25–$1.10/1M tokens).
  * **Khó (T3):** Xử lý đồng thời, giải thuật phức tạp, thiết kế kiến trúc → gửi tới model cao cấp ($1.25–$2.50/1M tokens).

* **3 chế độ tuỳ chỉnh:** `cost_first` (tiết kiệm tối đa), `balanced` (cân bằng, mặc định), `quality_first` (ưu tiên chất lượng).

* **Tự phục hồi khi sự cố:** Kết nối 3 nhà cung cấp (OpenAI, Google Gemini, Groq) — khi một bên gặp lỗi, tự động chuyển sang bên khác trong mili-giây, người dùng không nhận ra gián đoạn.

* **Theo dõi hội thoại nhiều lượt:** Nhận biết khi cuộc trò chuyện chuyển từ câu hỏi đơn giản sang phức tạp, tự động nâng model phù hợp.

---

## 3. Hướng phát triển (Future Roadmap)

1. **Chạy lại benchmark chất lượng** với bộ phân loại mới trên 1,084 bài toán chuẩn quốc tế (kết quả trước: đạt 98.7% chất lượng GPT-4o với chỉ 14% chi phí).
2. **Thêm nhà cung cấp:** DeepSeek, Qwen, Claude — hạ tầng đã sẵn sàng, chỉ cần bổ sung kết nối.
3. **Hỗ trợ hình ảnh và tài liệu** ngoài văn bản thuần.
4. **Plugin cho IDE** (VS Code, Cursor) để lập trình viên theo dõi tiết kiệm chi phí trực tiếp trong trình soạn code.
