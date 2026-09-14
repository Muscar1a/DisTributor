# 13 — Math genre routing (design note)

Trạng thái: đề xuất. Nguồn động lực: PR #179 (`eval/cheap-baseline-comparison`).
Bổ sung cho doc 09 (classifier v1.5) và doc 10 (input domains §4 — CP genre).

## §1 Vấn đề

Trên MATH-500, Classifier v1.5 **bị all-nano thống trị**: kém hơn (63.6% vs 64.6%)
đồng thời đắt hơn 41%. Đây không phải đánh đổi hợp lý mà là lỗi định tuyến.

Bằng chứng từ `evals/math500_full_500_three_arm_metrics.json`:

| Arm | acc | phân phối model |
|-----|-----|-----------------|
| all_nano | 64.6% | nano ×500 |
| classifier_v1_5 | 63.6% | nano ×405, **mini ×95, gpt-5.4 ×0** |
| all_strong | 74.4% | gpt-5.4 ×500 |

Hai sự thật:

1. **Router đẩy 0/500 câu lên T3.** Strong hơn nano thật 10 điểm (p≈7e-12) → có
   headroom, nhưng không câu nào chạm tier bắt được nó.
2. **Escalate lên mini là net âm.** McNemar v1.5 vs nano: `v1_5_only=29`,
   `nano_only=34` → 95 lần lên mini mất 34, được 29 = **−5**. Mini vô ích ở math.

Level 5 (n=134): nano 68, v1.5 **69**, strong **91** — router gần như bằng nano
đúng chỗ strong hơn 23 câu.

### §1.1 Căn nguyên

Bài toán thuần đi vào nhánh `_score_non_coding`. Điểm tối đa thực tế:

```
math (20, phẳng) + multi_step (15) + output_constraint (10) = 45
```

Prompt MATH ngắn nên `length = 0`. Ngưỡng `t2_max = 60` → **về mặt cấu trúc, một
bài toán thuần không bao giờ đạt T3.** Thêm nữa, `_math_points_v15` trả 20 phẳng
cho cả "2+2" lẫn tích phân — **không có gradient độ khó** để phân biệt Level 1 với
Level 5. Cap cứng + tín hiệu phẳng, không phải chuyện calibration.

## §2 Đề xuất: genre branch cho math, sao đúng khuôn CP

CP đã có `_detect_genre_cp` → `_score_cp` với floor C2 + 5 luật escalate C3
(doc 10 §4). Math xứng đáng y hệt. Tái dùng cơ chế band/floor sẵn có, **không thêm
dependency, không đụng nhánh coding.**

### §2.1 Nhận diện genre (`_detect_genre_math`)

Kích hoạt khi prompt là bài toán thuần chứ không phải hỏi khái niệm. Điều kiện:
có tín hiệu math (`_MATH_KEYWORD_RE` / `_MATH_EXPR_RE` / `_MATH_SYMBOL_RE`) **và**
có yêu cầu ra đáp số (ví dụ `\boxed`, "final answer", "tính", "compute", "solve for").

Đặt check này trong `_score` **ngay sau `_detect_genre_cp`, trước `_is_coding`** —
để bài toán không bị nhánh coding hoặc non-coding nuốt.

```
def _score(...):
    if self._detect_genre_cp(prompt):   return self._score_cp(...)
    if self._detect_genre_math(prompt): return self._score_math(...)   # MỚI
    is_coding = ...
```

### §2.2 Chấm điểm (`_score_math`) — mirror `_score_cp`

- **Floor = T2**, không phải T1. Base `_BAND_C2_BASE` (32), floor `_BAND_C2_FLOOR`
  (30). Lý do: kể cả bài dễ, để nano làm là rẻ nhưng đây là floor phòng thủ; nếu
  muốn giữ bài số học tầm thường ở T1 thì thêm 1 guard "arithmetic-only" hạ về base
  thấp (xem §4, câu hỏi mở).
- **Escalate T3** (base `_BAND_C3_BASE` = 62, vượt `t2_max` = 60) khi có **≥1**
  marker khó. Đích là T3 **thẳng**, bỏ qua mini — vì §1 cho thấy mini net-âm.

### §2.3 Marker escalate T3 (phác regex, cần tinh chỉnh khi implement)

| Mã | Ý nghĩa | Phác |
|----|---------|------|
| MH1 | Ký hiệu giải tích/đại số cao cấp | `\int`, `\sum`, `\prod`, `\lim`, `\oint`, `matrix`, `\begin{...matrix}` |
| MH2 | Yêu cầu chứng minh | `\bprove that\b`, `chứng minh`, `show that` |
| MH3 | Số học modular / tổ hợp lớn | `\pmod`, `mod \d`, `binomial`, `\binom`, `số dư` |
| MH4 | Cấu trúc lồng sâu | phân số lồng (`\frac{...\frac`), căn lồng, đa lớp `\boxed` |
| MH5 | Từ khoá cạnh tranh/khó | `olympiad`, `competition`, `AIME`, `IMO`, `Putnam` |

Giữ số marker nhỏ và có ceiling: `# ponytail: regex heuristic, thay bằng graded
score nếu discrimination vẫn thấp sau đo`.

## §3 Test cần có (không framework, thêm vào `test_classifier_v1_5.py`)

1. `test_math_genre_hard_routes_t3` — prompt có `\int`/`prove that` → tier T3.
2. `test_math_genre_easy_floors_t2` — bài số học nhiều bước, không marker → T2, **không** T3.
3. `test_math_genre_not_hijacked_by_coding` — bài toán có nhắc "function f(x)"
   vẫn vào nhánh math, không rơi vào `_is_coding`.
4. `test_math_genre_detect_requires_answer_intent` — câu hỏi khái niệm thuần
   ("what is a derivative") **không** kích hoạt genre → giữ non-coding.
5. Regression: chạy lại `grade_math_three_arm` offline trên generation đã cache
   (nếu còn) hoặc chỉ cần re-route để xác nhận phân phối model dịch về T3 > 0.

## §4 Tiêu chí thành công & câu hỏi mở

**Thành công tối thiểu:** phân phối model trên MATH-500 có T3 > 0 và đường cong về
"trả nhiều hơn → được nhiều hơn" (acc ≥ nano khi cost ≥ nano). Không còn bị nano
thống trị.

**Thành công tốt:** thu hồi phần lớn 23 câu Level-5 mà strong đúng còn nano sai,
với chi phí < all_strong.

**Câu hỏi mở cho team:**

- Floor T2 cho *mọi* bài toán có làm tăng cost quá tay trên traffic thật (nhiều số
  học vặt) không? Nếu có, cần guard "arithmetic-only → T1". Đo trên traffic hỗn hợp
  trước khi chốt floor.
- Benchmark thuần-MATH vốn thiên vị all-strong; giá trị router nằm ở traffic hỗn
  hợp. Fix này nhắm mục tiêu **không bị dominated**, không phải thắng single-benchmark.
- Dài hạn: thay heuristic bằng graded difficulty (đếm bước, độ sâu ký hiệu) hoặc
  mở rộng classifier_v2 (doc 12) sang math — nhưng chỉ khi §3 chứng minh heuristic
  chạm trần.
