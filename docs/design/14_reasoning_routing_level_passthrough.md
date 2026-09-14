# 14 — Định tuyến prompt suy luận ngắn-mà-khó (phần còn lại của #194)

Trạng thái: đề xuất. Nguồn động lực: issue #194, tiếp nối PR #201 (math genre).
Bổ sung cho doc 09 (classifier v1.5), doc 10 (input domains — genre), doc 12
(classifier v2). Đây là **doc mô tả thay đổi cần làm**, không phải code.

## §1 Phần #194 mà #201 chưa đóng

#194 nói về length bias cho **prompt logic/thuật toán phức tạp nhưng ngắn**. PR #201
chỉ dựng nhánh cho **math** (`_detect_genre_math` → `_score_math`) và tự khai báo
`Refs #194`, **không** `Closes`. Ba mảng còn hở:

1. **Prompt suy luận không có keyword.** Bài toán logic/thuật toán phát biểu bằng
   lời, không chứa từ khoá coding (D1–D6, tech noun) lẫn từ khoá math → rơi vào
   `_score_non_coding`, chấm 0 → **T1**. Đây là lõi của length bias: khi không có
   marker nào, điểm chỉ còn phụ thuộc `length`.
2. **Root cause kiến trúc bị hoãn.** v2 đã có `level` L0–L6 do LLM chấm nhưng vứt đi
   ở nhánh `kind="other"` (`classifier_v2.py:305`). #201 đẩy việc này sang "mentor
   duty / design-freeze".
3. **Eval dataset chưa có cặp prompt tương đương-khác-độ-dài** như Expected Behavior
   §2 của issue yêu cầu. #201 chỉ thêm unit test vào `test_classifier_v1_5.py`.

Doc này tập trung (1) và (2) — (3) là việc data, tách riêng.

## §2 Căn nguyên — hai tầng

### §2.1 Tầng heuristic (v1.5): mù ngữ nghĩa theo thiết kế

`_score_non_coding` (`classifier_v1_5.py:592-617`) cộng điểm từ 6 tín hiệu, tất cả
đều là **regex marker**: `math`, `multi_step`, `output_constraint`, `long_creative`,
`length`, `long_context`. Một prompt khó nhưng phát biểu bằng lời thường **không
khớp regex nào** → điểm 0 → T1.

Ví dụ vết chạy (prompt suy luận thật, ngắn, không keyword):

> "Có 12 đồng xu, một đồng giả nặng hoặc nhẹ hơn. Tìm số lần cân tối thiểu trên cân
> thăng bằng để xác định đồng giả và biết nó nặng hay nhẹ."

| Bước | Kết quả |
|------|---------|
| `_detect_genre_cp` | ✗ (không có 2 CP marker) |
| `_detect_genre_math` (sau #201) | ✗ (không có `_MATH_KEYWORD_RE`/expr/symbol) |
| `_is_coding` (`:621`) | ✗ (không tech noun, không coding intent) |
| `_score_non_coding` | math 0 + multi_step 0 + length 0 = **0 → T1** |

Đây không phải lỗi calibration mà là **trần năng lực**: heuristic chỉ thấy cái nó có
regex. Prompt khó "im lặng" về từ khoá thì heuristic không có đường nào chấm cao.
Mở rộng marker cũng không cứu được lớp này — recall thấp, false-positive cao (mọi
"tìm số nhỏ nhất" đâu phải đều khó).

**Lưu ý về ví dụ trong #201/#194:** prompt `"design an O(log n) algorithm"` mà PR
nói còn under-score thì thực ra **đã lên T3** ở v1.5 — `_DRIVER_D2_RE`
(`:57-67`) khớp `O\s*\(\s*[nNlL]` và `complexity`, cho band C3. Còn ở v2, LLM chấm
đúng L3 (prompt scale coi "O(log) requirement" là L3 → anchor 32 → **T2**). Vậy ví
dụ đó không phải ca T1. Ca T1 thật là lớp **không keyword** ở trên. Nên khoanh vùng
lại cho đúng khi review.

### §2.2 Tầng kiến trúc (v2): LLM chấm đúng rồi bị vứt

Đây mới là mấu chốt. `_SYSTEM_PROMPT` (`classifier_v2.py:81-116`) yêu cầu LLM chấm
`level` L0–L6 **cho cả `kind="other"`** — thang có sẵn ô cho phi-code khó:

- L4 = "designing an algorithm like DP/pruning/invariants"
- L6 = "mathematical proof obligations ... proving correctness"

Nghĩa là với bài 12 đồng xu ở trên, LLM nhiều khả năng trả `kind="other",
level="L4"/"L5"`. Nhưng nhánh xử lý **ném `level` đi**:

```
# classifier_v2.py:290-307
if kind == "other":
    ...
    score, signals = self.fallback_classifier._score_non_coding(   # :305
        instruction, prompt_text, context_tokens, v15_started
    )
    ...
    self._log_why(why, kind, None)   # :311 — None: level đã bị bỏ
```

LLM đã hiểu ngữ nghĩa và chấm cao; code lại quay về đếm regex (mù). Đây là root cause
thật của phần còn lại #194 — và là chỗ duy nhất **có thể** sửa triệt để, vì chỉ LLM
mới "đọc hiểu" được prompt không keyword.

## §3 Đề xuất thay đổi

> **Định hướng:** mục tiêu là **tối ưu LLM router v2** — đó là sản phẩm. Heuristic
> v1.5 chỉ là fallback mang tính tương đối (khi LLM lỗi/timeout), không phải nơi đầu
> tư để giải #194. Vì vậy fix đặt trọn ở v2, và "triệt để" nghĩa là **để LLM làm
> nguồn sự thật duy nhất cho độ khó**, không pha trộn heuristic vào phán đoán của nó.

### §3.1 (Chính) v2 `kind="other"` dùng thẳng `level`, đối xứng với nhánh coding

Nhánh `kind="coding"` **đã** tin `level` của LLM: `anchor = _LEVEL_ANCHORS[level]`
(`classifier_v2.py:329`), không hề pha heuristic. Sự bất đối xứng — coding tin LLM,
"other" thì vứt LLM đi rồi đếm regex — **chính là bug**. Fix triệt để là làm hai
nhánh đối xứng: `kind="other"` cũng chấm điểm từ `level`.

```
# thay cho :305-307 khi kind == "other"
if level not in _LEVEL_ANCHORS:                 # tái dùng guard :326
    return self._fallback_result(...)           # level lạ/thiếu -> fallback, không đoán
score = _LEVEL_ANCHORS[level]                    # L0=0 L1=8 L2=18 L3=32 L4=46 L5=62 L6=80
if context_tokens > LONG_CONTEXT_TOKENS:         # modifier bối cảnh duy nhất còn hợp lý
    score += 6                                   #   cho non-coding; các modifier khác
                                                 #   (error_artifact, multi_file) là coding-only
score = max(0, min(100, score))
signals = [Signal(f"v2_level_{level}", _LEVEL_ANCHORS[level]),
           Signal("v2_kind_other", 0),
           Signal(f"v2_prompt_{PROMPT_REVISION}", 0)]
self._log_why(why, kind, level)                  # KHÔNG còn None
```

**Vì sao bỏ hẳn heuristic khỏi nhánh này (không dùng làm "sàn"):**

- `max(llm, heuristic)` nghe an toàn nhưng nó **để heuristic ghi đè LLM một chiều**:
  chỉ nâng, không hạ. Khi LLM chấm đúng một bài phi-code là L1 (rẻ) mà heuristic vô
  tình dội math keyword lên 45, sàn `max` ép nó lên T2 — LLM mất quyền làm rẻ prompt.
  Trái mục tiêu tối ưu cost của v2.
- Bài không keyword: heuristic = 0 dù bài khó → sàn vô dụng đúng chỗ cần nhất. Sàn
  chỉ "cứu" được ca mà heuristic vốn đã bắt được — tức ca không phải #194.
- Đối xứng với nhánh coding cho hành vi **dễ suy luận và dễ test**: một prompt, một
  nguồn điểm (`level`), không hai đường chồng nhau.
- An toàn được lo bằng **fallback khi level không hợp lệ** (guard `:326`), không phải
  bằng cách trộn heuristic. LLM lỗi/timeout vẫn rơi về v1.5 như cũ (`:278`, `:281`).

`# ponytail: dùng lại _LEVEL_ANCHORS, không thêm thang điểm mới; xoá nhánh _score_non_coding khỏi kind=other.`

### §3.2 (Đòn bẩy v2) Hiệu chỉnh `_SYSTEM_PROMPT` cho độ khó phi-code

Đây là chỗ tối ưu router v2 thật sự. Thang L0–L6 hiện viết **gần như toàn bằng ngôn
ngữ coding** (`classifier_v2.py:83-97`); mỗi bậc chỉ có 1–2 mẩu phi-code (L4 "designing
an algorithm", L6 "mathematical proof"). Nếu định tuyến "other" sắp phụ thuộc hoàn
toàn vào `level`, thì độ chuẩn của level trên prompt phi-code phải được nâng — nếu
không ta chỉ dời điểm mù từ heuristic sang LLM.

Đề xuất bổ sung **anchor phi-code** cho từng bậc trong prompt (mỗi bậc 1 ví dụ
non-coding rõ ràng), ví dụ:

| Bậc | Anchor phi-code cần thêm |
|-----|--------------------------|
| L1 | dịch một câu, đổi đơn vị đo |
| L2 | tóm tắt một đoạn, hỏi định nghĩa ("đạo hàm là gì") |
| L3 | bài toán chuẩn một bước có đáp số kiểm được ngay |
| L4 | câu đố suy luận/tổ hợp nhiều bước (12 đồng xu, bắc cầu qua sông) |
| L5 | suy luận qua nhiều ràng buộc ẩn, chứng minh không hiển nhiên |
| L6 | chứng minh toán học đầy đủ, bất biến/đối kháng |

Kèm 1 rule: "Áp thang này cho **cả** yêu cầu phi-code (kind=other): độ khó = mức suy
luận, không phải độ dài văn bản." `PROMPT_REVISION` (`:47`) tăng r3 → r4 khi sửa để
cache không lẫn phiên bản. Đây là thay đổi **prompt**, đo bằng eval (§6), không đụng
code luồng.

### §3.3 Không đụng `_length_points`

Giữ nguyên như #201. Bỏ `length` chỉ kéo bản dài xuống bằng bản ngắn — cả hai cùng
sai. Fix đúng là nâng bản ngắn lên bằng ngữ nghĩa (§3.1), không phải hạ bản dài.

### §3.4 v1.5 chỉ là fallback tương đối — không đầu tư thêm

Chế độ Heuristic của Playground (`Playground.jsx:557-560`) và đường v2-rơi-về-v1.5
khi LLM timeout **không có `level`** → lớp không-keyword ở §2.1 vốn không giải được
bằng regex. Quyết định có chủ đích: **không** dựng `_detect_genre_reasoning` bằng
marker (recall thấp, false-positive cao, thêm bảo trì cho lợi ích mỏng). v1.5 giữ
vai "best-effort không LLM"; đường chất lượng cho #194 là v2 (§3.1–§3.2). Ghi giới
hạn này vào doc 09 để mentor thấy đã cân nhắc, không phải bỏ sót.

## §4 Ảnh hưởng interface & design-freeze

- **Không đổi public interface.** `ClassificationResult` giữ nguyên shape; chỉ thêm
  tên signal mới (`v2_level_*` ở nhánh other). Cùng lập luận #201 đã dùng, hợp
  `05_interfaces.md`.
- **Có đổi hành vi định tuyến** của v2 cho `kind="other"` → thay đổi phân phối
  model/chi phí. Đây là điểm cần team chốt: #201 gọi nó là "architecture decision
  under design-freeze" và hoãn. Doc này lập luận nó **thuộc phạm vi bug-fix của
  #194** (LLM đã chấm đúng, ta chỉ ngừng vứt kết quả), nhưng **phải kèm số đo eval**
  (§6) trước khi merge, không merge chay.

## §5 Test cần có (không framework, thêm vào `test_classifier_v2.py`)

1. `test_kind_other_hard_uses_llm_level` — mock LLM trả `kind=other, level=L5` cho
   prompt không keyword → tier **T3** (trước fix: T1).
2. `test_kind_other_easy_stays_t1` — mock `kind=other, level=L1` cho "viết lời chào"
   → **T1**, không escalate.
3. `test_kind_other_no_heuristic_bleed` — prompt dội nhiều math keyword nhưng LLM trả
   `level=L1`: kết quả **T1**, chứng minh heuristic không còn kéo điểm lên. Chốt việc
   `level` là nguồn sự thật duy nhất (đối lập với thiết kế max-floor đã loại).
4. `test_kind_other_invalid_level_falls_back` — LLM trả `level="L9"` → guard `:326`
   kích hoạt, rơi về `_fallback_result`, không crash.
5. Bất biến #194 (song song với test #201): cùng bài suy luận, bản ngắn và bản padded
   → **cùng tier** ở v2.

## §6 Tiêu chí thành công & câu hỏi mở

**Thành công tối thiểu:** ca `P156-F1-AI-004` và `P156-EVAL-AI-002` — bản ngắn và bản
dài của cùng bài suy luận cùng ra T3 ở classifier v2. Bất biến ngắn≡dài giữ được.

**Thành công tốt:** trên tập eval hỗn hợp, phân phối model dịch lên đúng chỗ khó mà
tổng chi phí không tăng quá ngưỡng team đặt.

**Câu hỏi mở (cần team/mentor chốt, không thuộc một PR bug-fix):**

- LLM chấm `level` cho `kind="other"` **đáng tin đến đâu?** Thang L0–L6 viết chủ yếu
  bằng ngôn ngữ coding; cần một mẫu eval non-coding để đo độ chuẩn của level trước
  khi tin dùng. Nếu độ chuẩn thấp, cân nhắc chỉ dùng LLM level như *tín hiệu escalate*
  (chỉ nâng, có ngưỡng) thay vì map thẳng.
- Chi phí: bài phi-code khó vốn đang chạy model rẻ (sai) nay lên T3 (đúng nhưng đắt).
  Đo delta cost trên traffic thật/eval hỗn hợp — cùng mối lo §4 của doc 13. Baseline
  nằm ở PR #179 chưa merge.
- Có nên hợp nhất math genre (#201) vào cơ chế level-passthrough này không? Cả hai
  đều nhắm "phi-code khó → T3". Dài hạn có thể trùng; ngắn hạn giữ tách để #201 merge
  độc lập.

## §7 Cặp prompt eval bất biến độ dài (Expected Behavior §2 của #194)

Issue yêu cầu "cặp prompt tương đương ý nghĩa, khác độ dài" để benchmark length bias.
`mixed_200.jsonl` **không dùng được** — schema khóa nguồn WildChat
(`source_record_id` pattern, `source_dataset` const), còn đây là prompt tổng hợp.
Đề xuất fixture riêng:

- **File:** `src/evals/datasets/length_bias_pairs.jsonl`
- **Schema tối thiểu** (mỗi dòng một prompt):
  `{"pair_id": str, "form": "concise"|"padded", "prompt": str, "language": "vi"|"en", "category": str, "expected_tier": "T1"|"T2"|"T3"}`
- **Bất biến kiểm:** với mọi `pair_id`, `tier(concise) == tier(padded) == expected_tier`.
  Đây là định nghĩa "done" cho #194, chạy trên classifier v2.

Bộ hạt giống dưới đây — 5 cặp, phủ vi/en, gồm ca-khó-không-keyword (đòn chính của
§3.1) và ca-dễ-đối-chứng (padding **không** được đẩy T1→T2). Bun soạn thành jsonl.

**LP1 — câu đố suy luận, không keyword, `expected_tier=T3`, vi**
- concise: `Có 12 đồng xu giống hệt, một đồng giả khác khối lượng. Tìm số lần cân tối thiểu trên cân thăng bằng để xác định đồng giả và cho biết nó nặng hay nhẹ.`
- padded: `Hôm nọ mình đọc được một câu đố khá thú vị và cứ nghĩ mãi chưa ra, nên muốn nhờ bạn phân tích giúp cho cặn kẽ. Tình huống là thế này: có tất cả 12 đồng xu trông giống hệt nhau về bề ngoài, nhưng trong số đó có đúng một đồng là giả và khối lượng của nó khác các đồng còn lại — có thể nặng hơn mà cũng có thể nhẹ hơn, ta chưa biết. Công cụ duy nhất là một chiếc cân thăng bằng hai đĩa. Bạn hãy tìm giúp mình số lần cân tối thiểu cần thiết để vừa xác định được đâu là đồng giả, vừa kết luận được nó nặng hơn hay nhẹ hơn.`

**LP2 — chứng minh số học, `expected_tier=T3`, en**
- concise: `Prove that n^5 - n is divisible by 30 for every integer n.`
- padded: `I've been reviewing some number theory and ran into a claim I want to be fully convinced of, so could you walk me through a complete and rigorous argument rather than just asserting it? The statement is the following: for every single integer n, whether positive, negative, or zero, the expression n to the fifth power minus n is always divisible by 30. Please prove that this holds in general.`

**LP3 — thiết kế thuật toán phát biểu bằng lời, không dùng chữ "O()", `expected_tier=T3`, vi**
- concise: `Cho một mảng số nguyên phân biệt vốn tăng dần nhưng đã bị xoay vòng tại một vị trí không biết, hãy tìm phần tử nhỏ nhất mà không duyệt hết mảng.`
- padded: `Mình có một bài nhỏ trong dự án và muốn nghe cách tiếp cận tối ưu từ bạn. Dữ liệu đầu vào là một mảng gồm các số nguyên đôi một khác nhau; ban đầu mảng này được sắp xếp tăng dần, nhưng sau đó người ta xoay vòng nó quanh một vị trí nào đó mà mình không hề biết trước. Yêu cầu của mình là tìm ra phần tử có giá trị nhỏ nhất trong mảng, và điều quan trọng là mình không muốn phải duyệt qua toàn bộ các phần tử vì mảng có thể rất lớn.`

**LP4 — đối chứng dễ, padding không được đẩy lên tier, `expected_tier=T1`, vi**
- concise: `2 + 2 bằng mấy?`
- padded: `Mình đang ngồi cà phê buổi sáng, đầu óc còn hơi lơ mơ chưa tỉnh hẳn, tự nhiên lại thắc mắc một phép tính con nít mà nhất thời chưa nhẩm ra ngay. Bạn giúp mình một chút cho chắc nhé: hai cộng hai thì cho kết quả là bao nhiêu vậy? Cảm ơn bạn nhiều lắm.`

**LP5 — đối chứng dễ, en, `expected_tier=T1`**
- concise: `What is the capital of France?`
- padded: `Quick question that popped into my head while I was planning a trip — nothing urgent, just curious and wanted to double-check my memory before I tell my friends. Could you remind me which city is the official capital of France?`

`# ponytail: 5 cặp đủ chốt bất biến; thêm cặp khi eval lộ ngưỡng nào còn lệch.`
