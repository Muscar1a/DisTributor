# FR-02 — Classifier V1 (heuristic) · ghi chú hiện thực

**Cho ai đọc:** cả team. Nhóm 2 cần mục 3 và mục 9 để đấu nối. Ai muốn hiểu thuật toán đọc mục 4–6. Ai review PR đọc mục 7–8.

**Nguồn thiết kế:**
- `docs/design/02_prd.md` §6.1–6.2 — bảng trọng số và định nghĩa tier
- `docs/design/05_interfaces.md` §B.2 — contract của classifier
- `docs/design/06_architecture.md` §3 (ADR-005), §7 (rủi ro R1)

**Trạng thái:** classifier + policy engine chạy được và có test. Chưa nối vào API HTTP. 66 test pass, ruff sạch.

---

## 1. Bối cảnh — vì sao cần classifier

Sản phẩm của nhóm là một cái cổng đứng giữa ứng dụng và các nhà cung cấp LLM. Ý tưởng kiếm tiền của nó rất đơn giản:

> Câu hỏi dễ thì gửi cho model rẻ. Câu hỏi khó mới gửi cho model đắt.

Giá giữa model rẻ và model đắt chênh nhau 20–100 lần. Nếu 60–70% request là việc dễ (giả thuyết H1 trong PRD) thì chỉ cần phân loại đúng là tiết kiệm được phần lớn hoá đơn.

Nhưng muốn làm được thế, phải có ai đó **nhìn vào câu hỏi và đoán xem nó khó hay dễ** — trước khi gọi LLM. Đó chính là classifier.

Nó phải đoán rất nhanh (dưới 100ms), vì nếu bản thân việc đoán đã tốn 2 giây thì người dùng chẳng được lợi gì.

### Ba mức độ khó (tier)

| Tier | Nghĩa | Ví dụ việc | Model dùng |
|---|---|---|---|
| **T1** | Dễ | Chào hỏi, hỏi đáp đơn giản, dịch câu ngắn | Rẻ nhất |
| **T2** | Vừa | Tóm tắt, viết email, dịch đoạn dài | Trung bình |
| **T3** | Khó | Code, toán, suy luận nhiều bước, phân tích dài | Mạnh nhất, đắt nhất |

### Vì sao dùng luật (heuristic) chứ không dùng AI để phân loại

Có 2 cách làm classifier:

- **Luật (rule-based)** — đọc chữ trong câu, thấy dấu hiệu gì thì cộng điểm. Nhanh, miễn phí, giải thích được từng quyết định. Nhưng cứng nhắc, dễ bỏ sót cách diễn đạt lạ.
- **Học máy / gọi LLM** — chính xác hơn, hiểu ngữ nghĩa. Nhưng chậm, tốn tiền, và **không giải thích được vì sao** nó xếp câu này vào T3.

ADR-005 chọn làm luật trước, học máy sau. Lý do: cần một mốc so sánh có thật. Nếu nhảy thẳng vào học máy, đến lúc bảo vệ đồ án sẽ không trả lời được câu "nó tốt hơn cách đơn giản bao nhiêu?". Có bản v1 chạy được rồi, sau này bản v2 mới chứng minh được giá trị bằng số.

---

## 2. Chạy thử ngay — không cần API key, không cần cài gì thêm

Mở PowerShell tại thư mục dự án:

```powershell
python -m src.gateway.demo_route
```

Nó chạy sẵn 3 prompt mẫu ứng với 3 tier. Muốn thử câu của bạn:

```powershell
python -m src.gateway.demo_route "Viết hàm Python kiểm tra số nguyên tố"
python -m src.gateway.demo_route --policy cost_first "Viết hàm Python kiểm tra số nguyên tố"
```

### Đọc kết quả

```
Prompt   : Viết hàm Python giải phương trình bậc hai, so sánh với numpy, trả JSON đúng schema
Score    : 67  (heuristic-v1, 0ms)
Tín hiệu : code+22, math+20, multi_step+15, output_constraint+10
Tier     : T3 -> T2  [policy: cost_first]
Chain    : gemini-flash@google -> mock-mid@mock -> llama-3.3-70b@groq
```

| Dòng | Nghĩa |
|---|---|
| `Score` | Điểm khó, thang 0–100. Trong ngoặc là phiên bản thuật toán và thời gian chấm |
| `Tín hiệu` | **Vì sao** ra điểm đó. Cộng lại đúng bằng Score: 22+20+15+10 = 67 |
| `Tier` | Bên trái là tier do classifier chấm, bên phải là tier sau khi policy can thiệp |
| `Chain` | Danh sách model sẽ gọi theo thứ tự. Model đầu lỗi thì thử model thứ hai, rồi thứ ba |

Ở ví dụ trên, classifier nói T3 nhưng chế độ `cost_first` kéo xuống T2 để tiết kiệm. Chạy lại cùng câu đó với `--policy quality_first` sẽ thấy nó ở nguyên T3. Đó là toàn bộ ý tưởng sản phẩm, gói trong hai lệnh.

---

## 3. Bản đồ file

| File | Nội dung | Ai được sửa |
|---|---|---|
| `src/gateway/app/core/interfaces.py` | Bản hợp đồng giữa BE và AI-core, chép nguyên từ `05_interfaces.md` §B | **Không ai** — sửa phải PR tài liệu trước |
| `src/gateway/app/core/classifier_v1.py` | Thuật toán chấm điểm | Member 1 |
| `src/gateway/app/core/policy.py` | Chọn danh sách model từ tier | Member 1 |
| `src/gateway/app/config/models.yaml` | Tier nào dùng model nào, ngưỡng điểm | Member 1 + admin |
| `src/gateway/app/config/policies.yaml` | 3 chế độ cost/balanced/quality | Member 1 |
| `src/gateway/app/config/pricing.yaml` | Giá và quality_rank — **hiện là số giả** | Member 2 |
| `src/gateway/app/config/loader.py` | Nạp YAML, kiểm tra hợp lệ lúc khởi động | Member 1 |
| `src/gateway/tests/test_classifier.py` | 41 case | ai thêm cũng được |
| `src/gateway/tests/test_policy.py` | 25 case | ai thêm cũng được |
| `src/gateway/demo_route.py` | CLI chạy thử | — |

---

## 4. Thuật toán chấm điểm

### 4.1 Ý tưởng

Đọc câu hỏi, tìm các **dấu hiệu** cho thấy nó khó. Mỗi dấu hiệu có một số điểm. Cộng hết lại ra tổng điểm. Tổng điểm rơi vào khoảng nào thì thành tier đó.

```
"Viết hàm Python kiểm tra số nguyên tố rồi giải thích độ phức tạp"
         │
         ├── thấy "viết hàm", "Python"  → dấu hiệu code       +22
         ├── câu dài 12 từ              → dưới ngưỡng, không cộng
         └── không thấy dấu hiệu khác
                                          ─────────────────────────
                                          tổng = 22 → T1
```

### 4.2 Bảng dấu hiệu (đúng PRD §6.2)

| Dấu hiệu | Phát hiện bằng cách nào | Điểm |
|---|---|---|
| `code` | Có khối ` ``` `, hoặc từ khoá lập trình (`def`, `class`, `import`, `SELECT`, `function`…), hoặc chữ "debug / refactor / sửa lỗi / viết hàm" | +22 |
| `math` | Có ký hiệu toán (`√ ∫ ∑ ≤ ≥`), hoặc chữ "chứng minh / giải phương trình / solve", hoặc **số–phép tính–số** như `12 * 47` | +20 |
| `multi_step` | Có chữ "phân tích / so sánh / đánh giá / lập kế hoạch / vì sao / step by step", hoặc câu chứa **từ 2 dấu `?` trở lên** | +15 |
| `output_constraint` | Đòi trả về JSON đúng schema, đòi dạng bảng, đòi "đúng 300 từ" | +10 |
| `long_context` | Tổng token của **tất cả** message vượt 2.000 | +10 |
| `long_creative` | Vừa có "viết bài / essay / truyện" **vừa** đòi trên 500 từ | +10 |
| `length` | Độ dài riêng của câu hỏi: dưới 50 token → 0 điểm · 50–300 → +10 · trên 300 → +18 | 0–18 |
| `fast_path_easy` | Câu chào, hoặc câu ≤8 từ **và không dính dấu hiệu nào ở trên** | ép thẳng về T1 |

Tổng điểm luôn bị kẹp trong 0–100, vì cộng nhiều dấu hiệu có thể vượt 100.

### 4.3 Từ điểm sang tier

```
score < 30      → T1
30 ≤ score < 60 → T2
score ≥ 60      → T3
```

Hai ngưỡng này **không viết cứng trong code** mà đọc từ `models.yaml`. Lý do: US-04 cho phép admin chỉnh ngưỡng qua giao diện, không phải sửa code rồi deploy lại.

### 4.4 Vì sao từ khoá viết cả tiếng Việt lẫn không dấu

Trong code bạn sẽ thấy từ khoá lặp 2 lần:

```python
r"sửa\s*lỗi|sua\s*loi|viết\s*hàm|viet\s*ham"
```

Vì người Việt gõ chat thường bỏ dấu. Nếu chỉ bắt bản có dấu thì "sua loi giup minh" không được nhận diện là code, và request bị đẩy nhầm xuống model rẻ. `\s*` cho phép giữa hai chữ có hoặc không có khoảng trắng.

---

## 5. Luồng chạy của code, theo thứ tự

Đọc song song với `classifier_v1.py`.

### Bước 1 — Bấm giờ và bọc chống lỗi

```python
async def classify(self, messages):
    started = time.perf_counter()
    try:
        score, signals = self._score(messages, started)
        tier = self._to_tier(score)
    except Exception:
        return self._fallback(started)     # bất cứ lỗi gì cũng không văng ra ngoài
    return ClassificationResult(...)
```

Khối `try/except` này là yêu cầu bắt buộc của hợp đồng (§B.2 điều 1). Nếu classifier ném lỗi ra ngoài thì **cả request của người dùng chết**, trong khi chỉ cần đoán bừa "mức trung bình" là họ vẫn có câu trả lời. Bản dự phòng: T2, 45 điểm, kèm dấu hiệu `classifier_error` để sau này truy được.

### Bước 2 — Chọn câu để chấm

```python
prompt = self._prompt_text(messages)      # message user CUỐI CÙNG
context_tokens = sum(estimate_tokens(m.content) for m in messages)   # TẤT CẢ message
```

Một cuộc hội thoại có nhiều message: system prompt, các lượt trước, và câu hỏi mới nhất. Chỉ câu hỏi mới nhất mới là việc cần định tuyến, nên chỉ chấm nó. Toàn bộ phần còn lại chỉ dùng để tính `long_context`.

Nếu chấm cả cụm thì một system prompt dài 300 từ sẽ khiến **mọi** request đều được +18 điểm độ dài, và hệ thống mất khả năng phân biệt.

### Bước 3 — Chạy qua từng dấu hiệu

```python
for name, points in (
    ("code", self._code_points(prompt)),
    ("math", self._math_points(prompt)),
    ("multi_step", self._multi_step_points(prompt)),
    ...
):
    if points:
        signals.append(Signal(name, points))    # ghi lại để giải thích
        score += points
```

Mỗi dấu hiệu là một hàm riêng trả về điểm hoặc 0. Tách nhỏ như vậy để test được từng cái độc lập — hỏng chỗ nào biết ngay chỗ đó.

Danh sách `signals` là phần **giải thích được** (NFR-05). Nhờ nó, sau này admin mở log thấy "67 điểm vì code+22, math+20…" chứ không phải một con số vô danh. Nếu định tuyến sai, có bằng chứng để lần ra nguyên nhân.

### Bước 4 — Kiểm tra quá hạn

```python
self._check_deadline(started)     # quá ROUTER_TIMEOUT_MS (mặc định 800ms) thì bỏ cuộc
```

### Bước 5 — Fast-path (xét sau cùng)

```python
if not signals and self._is_fast_path_easy(prompt):
    return 0, [Signal("fast_path_easy", 0)]
```

Câu chào hoặc câu rất ngắn **mà không dính dấu hiệu nào** thì khỏi tính, cho thẳng T1. Điều kiện `not signals` là quan trọng — xem mục 6.2.

### Bước 6 — Kẹp điểm và trả về

```python
return max(0, min(100, score)), signals
```

---

## 6. Những quyết định khi code, và lý do

### 6.1 Ước lượng token thay vì dùng tokenizer thật

```python
def estimate_tokens(text):
    words = len(text.split())
    return max(int(words * 1.3), len(text) // 4)
```

Token là đơn vị mà LLM dùng để tính tiền và giới hạn độ dài. Đếm chính xác phải gọi thư viện tokenizer — thêm phụ thuộc, và chậm. Mà SLO bắt classify phải xong dưới 100ms.

Nên ước lượng bằng 2 công thức rồi **lấy số lớn hơn**:
- `số từ × 1.3` — hợp với tiếng Anh
- `số ký tự ÷ 4` — hợp với tiếng Việt có dấu, vốn tốn nhiều token hơn mỗi từ

Lấy số lớn hơn nghĩa là thiên về "đánh giá dài hơn thực tế" → dễ được xếp tier cao hơn → an toàn hơn.

### 6.2 Fast-path phải xét SAU CÙNG, không phải đầu tiên

Bản đầu mình viết fast-path ngay đầu hàm cho nhanh: câu ngắn thì thoát luôn, khỏi tính gì cả.

Test bắt lỗi ngay:

```
"Tóm tắt tài liệu trên"        ← 4 từ
+ system message 5.000 token   ← cả một tài liệu đính kèm
→ fast-path nhận diện "câu ngắn" → ép T1 → gửi cho model rẻ nhất
```

Câu ngắn nhưng việc rất nặng. Sửa: tính hết mọi dấu hiệu trước (bao gồm `long_context`), chỉ khi **không dấu hiệu nào bật** mới cho đi fast-path.

Đây là ví dụ cụ thể cho việc vì sao luật dự án bắt viết test trước.

### 6.3 Chữ "tính" không tự nó là dấu hiệu toán

Ban đầu định bắt luôn từ khoá "tính" theo PRD. Nhưng:

- "**tính** cách nhân vật này thế nào?" → không phải toán
- "app có những **tính** năng gì?" → không phải toán

Nên phải thu hẹp: chỉ tính là toán khi có **số ở hai bên phép tính** (`\d\s*[+\-*/^%=]\s*\d`), hoặc gặp từ khoá rõ ràng như "chứng minh", "giải phương trình".

Bài học chung của rule-based: mỗi lần thêm từ khoá phải nghĩ ngay "từ này còn xuất hiện ở ngữ cảnh nào khác không?".

### 6.4 Ngưỡng và timeout truyền qua constructor, không đọc env lung tung

```python
def __init__(self, t1_max=30, t2_max=60, router_timeout_ms=None):
```

Hợp đồng §B.2 điều 3: "không đọc config ngoài constructor". Nhờ vậy test tạo được classifier với ngưỡng tuỳ ý mà không phải sửa biến môi trường toàn cục — test chạy song song không giẫm lên nhau.

---

## 7. ⚠️ Vấn đề đã biết — cần quyết ở mentor duty

**Bảng trọng số trong PRD hiện tại không thể pass AC F1.1 của chính nó.**

Đây là kết quả chạy thật, không phải suy đoán:

| Prompt | Dấu hiệu bật | Điểm | Tier |
|---|---|---|---|
| "Viết hàm Python kiểm tra số nguyên tố" | code +22 | 22 | **T1** ❌ |
| "Debug đoạn code này giúp mình" | code +22 | 22 | **T1** ❌ |
| "Chứng minh bất đẳng thức Cauchy" | math +20 | 20 | **T1** ❌ |
| "Viết hàm… so sánh… trả JSON đúng schema" | 4 dấu hiệu | 67 | T3 ✅ |

Mâu thuẫn nằm ở chỗ:

- PRD §6.1 định nghĩa **T3 = "Code/debug, toán, suy luận đa bước"**
- AC F1.1 ghi rõ: *"không có prompt nhãn hard nào bị gán T1"*
- Nhưng trọng số §6.2 cho code chỉ +22, mà ngưỡng T1 là dưới 30

Kết quả: một câu hỏi code thuần tuý bị đẩy xuống **model rẻ nhất**. Đúng bằng rủi ro **R1** mà `06_architecture.md` §7 cảnh báo là nghiêm trọng nhất.

Code hiện tại **cài đúng PRD**, không tự ý sửa — vì trọng số nằm trong tài liệu đã freeze từ 05/08.

### Ba hướng xử lý

| Hướng | Cách làm | Đánh đổi |
|---|---|---|
| 1 | Nâng `code`/`math` lên khoảng 45–50 | Một mình đủ lên T2; kèm bất kỳ dấu hiệu nào nữa là T3. Đơn giản nhất |
| 2 | Thêm luật sàn: có `code` hoặc `math` → tier tối thiểu T2 | Giữ nguyên trọng số, nhưng thêm một khái niệm mới vào thuật toán |
| 3 | Hạ ngưỡng tier xuống | Ảnh hưởng mọi loại prompt, không chỉ code |

**Chưa chọn hướng nào.** Muốn chọn có căn cứ thì phải có **bộ 30 prompt gán nhãn** (AC F1.1 yêu cầu: 10 prompt mỗi tier, song ngữ Việt–Anh). Có bộ đó rồi mới đo được phương án nào cho tỉ lệ đúng cao hơn. Chưa có thì mọi lựa chọn đều là đoán.

---

## 8. Hai chỗ tài liệu chưa rõ, đã phải tự diễn giải

Ghi ra đây để ai thấy nên hiểu khác thì phản biện sớm.

### 8.1 `order_by` có sắp xếp cả model chính không?

`policies.yaml` có `order_by: cost_asc` (rẻ trước). `models.yaml` lại khai báo mỗi tier có một `primary` và danh sách `fallbacks`.

Câu hỏi: nếu `order_by` sắp xếp lại toàn bộ, thì `primary` còn nghĩa gì?

**Đã chọn:** `primary` luôn đứng đầu chain, `order_by` chỉ sắp xếp các fallback.

**Vì sao:** nếu để `order_by` sắp xếp cả `primary`, chế độ `cost_first` sẽ đẩy model mock (giá 0đ) lên đầu tiên — tức mọi request tiết kiệm đều rơi vào model giả. Và cấu hình admin chọn trở thành vô nghĩa, trái US-03 ("admin cấu hình model chính + danh sách fallback").

### 8.2 "tier liền kề cao hơn" nghĩa là mạnh hơn hay rẻ hơn?

`05_interfaces.md:313` viết: *"tier rỗng sau lọc → dùng chain của tier liền kề cao hơn"*.

**Đã chọn:** "cao hơn" = **mạnh hơn và đắt hơn** (T1 hết model thì leo lên T2).

**Vì sao:** tụt xuống tier rẻ để "có còn hơn không" chính là R1. Trả lời sai một câu khó tốn kém hơn nhiều so với trả dư tiền cho một câu dễ.

---

## 9. Cách Nhóm 2 dùng lại

Chỉ cần 2 dòng cuối, không phải biết bên trong chấm điểm ra sao:

```python
from src.gateway.app.core.classifier_v1 import ClassifierV1Heuristic
from src.gateway.app.core.policy import PolicyEngineV1
from src.gateway.app.core.interfaces import Message

classifier = ClassifierV1Heuristic()      # ngưỡng, timeout truyền qua constructor nếu cần
engine = PolicyEngineV1()                 # tự nạp YAML trong app/config/

result = await classifier.classify([Message(role="user", content=prompt)])
plan = engine.select(result, policy="balanced")
# plan.chain            -> [ModelRef(model_id, provider), ...] thứ tự thử
# plan.tier_effective   -> tier cuối cùng sau khi áp policy
# result.signals        -> để ghi vào DB, hiển thị trên dashboard
```

Muốn thay bằng bản giả khi test, chỉ cần kế thừa `BaseClassifier`:

```python
class StubClassifier(BaseClassifier):
    async def classify(self, messages):
        return ClassificationResult(score=45, tier=Tier.T2, signals=[],
                                    classifier_version="stub", latency_ms=0)
```

Đó là toàn bộ ý nghĩa của việc có hợp đồng: hai nhóm làm song song, ghép vào là chạy.

---

## 10. Chạy test

```powershell
python -m pytest src/gateway/tests -q      # 68 test
python -m ruff check src/                  # lint
```

CI đã gác đúng thư mục này (`ci.yml` chạy `pytest src/gateway/tests/` + `ruff check src/`), nên PR nào làm hỏng test sẽ bị chặn merge.

⚠️ **Thư mục `tests/` ở gốc repo đang hỏng.** Nó vẫn còn từ template và import `src.main`, `src.agents` — những module đã bị PR #13 xoá. Chạy `pytest tests/` sẽ lỗi ngay ở `conftest.py`. CI không quét nó nên không đỏ, nhưng ai lỡ chạy `pytest` không tham số sẽ tưởng mình làm hỏng gì đó. Nên xoá ở một PR dọn dẹp riêng.

---

## 11. Việc còn tồn

| Việc | Ai | Vì sao cần |
|---|---|---|
| Bộ 30 prompt gán nhãn (`src/evals/datasets/`) | Member 1 | Điều kiện để chốt trọng số ở mục 7 |
| Quyết hướng xử lý mục 7 | Mentor duty | Đụng PRD đã freeze |
| Nối classifier + policy vào `chat_completions.py` (hiện đang trả mock cứng) | Nhóm 2 | Để thành pipeline HTTP đủ |
| Xoá thư mục `tests/` ở gốc repo | ai cũng được | Đang hỏng, import module đã bị xoá |
| Thay số giả trong `pricing.yaml` bằng snapshot giá thật | Member 2 | Mọi con số tiết kiệm đều tính từ file này |
| Thống nhất schema `models.yaml` | Member 1 + Nhóm 2 | PR #13 dùng schema `models:` kèm `capabilities`, bản này dùng `tiers:`/`thresholds:` theo §D — đã giữ bản theo §D |
