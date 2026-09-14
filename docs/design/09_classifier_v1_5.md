# Classifier v1.5 — Heuristic phân hạng độ khó theo *loại việc*, không theo *độ dài văn bản*

**v1.0 · 2026-08-21 · File: `docs/design/09_classifier_v1_5.md` · Phạm vi: M3 / final demo**

> **Vị trí trong bộ tài liệu:** tài liệu này sở hữu **thiết kế chi tiết của classifier heuristic v1.5** — bản kế nhiệm trực tiếp của `ClassifierV1Heuristic`. Nó **không** thay thế `02_prd.md` §6.2 (PRD vẫn sở hữu requirement và bảng trọng số chính thức; §6.2 mô tả bản v1 đang chạy cho tới khi v1.5 land). Nó **không** thuộc FR-12 (classifier v2 ML/LLM) — v1.5 vẫn thuần CPU, không I/O, không LLM call, giữ nguyên contract B.2 trong `05_interfaces.md`. Quan hệ với `08_adaptive_routing.md`: v1.5 chỉ đổi cách sinh `score`/`signals` cho **một lượt**; Session Router tiêu thụ output đó không đổi interface. Khi lệch nhau về requirement → PRD thắng; về technical decision → `06_architecture.md` thắng.

---

## 1. Bối cảnh & vấn đề

Classifier v1 chấm điểm bằng cách cộng dồn tín hiệu regex trên **toàn bộ text của message user cuối**. Trong domain coding — domain trọng tâm của đồ án — cách này sai ở hai chỗ mà người dùng gặp ngay từ lượt đầu.

### 1.1 Vấn đề 1 — độ dài văn bản bơm điểm độ khó

Cùng **một task duy nhất** (fix một chương trình hello world hai dòng), chỉ khác cách người dùng *kể*:

| Cách viết | Tín hiệu v1 kích hoạt | Score | Tier |
|---|---|---|---|
| `Fix this: print("hello world")` | `fast_path_easy` | **0** | **T1** ✔ |
| Kể chuyện 3 dòng + "giờ ban debug giup minh" | `code 22` + `multi_step 15` | **37** | **T2** ✘ |
| Kể chuyện 6 dòng + code fence + "debug giúp mình, nó chỉ có hai dòng thôi" | `code 22` + `multi_step 15` + `length 10` | **47** | **T2** ✘ |

*(Số đo thật, chạy trên `ClassifierV1Heuristic` bản hiện tại ngày 21/08/2026.)*

Task không đổi. Độ khó thật không đổi. Nhưng tier nhảy T1→T2 chỉ vì user tâm sự dài hơn. Đây là **over-routing thuần tuý** — trả tiền model T2 cho việc T1, và tệ hơn: điểm 47 này còn được **EMA của Session Router kế thừa** sang các lượt sau (§9), nên một câu chuyện dài ở lượt 1 làm đắt cả phiên.

### 1.2 Vấn đề 2 — tín hiệu `code` là nhị phân trong domain mà mọi thứ đều là code

`_code_points()` trả **+22 phẳng** cho mọi thứ match regex — không phân biệt:

```
"Fix print('hello')"                              → code +22
"Implement distributed consensus with leader
 election and log compaction"                     → code +22   (nếu match được)
```

Trong một gateway phục vụ coding, "có liên quan tới code" là **đường cơ sở**, không phải tín hiệu phân biệt. Tín hiệu mang gần như **zero sức phân giải** đúng ở chỗ cần phân giải nhất. Câu hỏi thật sự chưa được trả lời ở bất kỳ đâu trong bộ tài liệu:

> **Thế nào là một coding task khó, thế nào là một coding task dễ?**

Tài liệu này trả lời câu hỏi đó (§5) và biến câu trả lời thành thuật toán chấm điểm (§6).

### 1.3 Các lỗi khác đo được trên bản hiện tại

Ngoài hai vấn đề trên, khảo sát bản v1 phát hiện thêm 4 nhóm lỗi (tất cả đều **đo được**, không phải suy đoán):

| # | Input | Kết quả v1 | Sai ở đâu |
|---|---|---|---|
| E1 | `Let me know when you are free` | `code +22` | `\blet\b` trong `_CODE_TOKEN_RE` bắt trúng tiếng Anh thường |
| E2 | `I want to return to my hometown next year` | `code +22` | `\breturn\b` — như trên |
| E3 | `The class I teach is about history` | `code +22` | `\bclass\b` — như trên |
| E4 | `Tôi cần giao hàng trong 2-3 ngày` | `math +20` | `_MATH_EXPR_RE` = `\d\s*[+\-*/^%=]\s*\d` bắt trúng khoảng số |
| E5 | `Cuộc họp diễn ra ngày 2026-08-21 nhé` | `math +20` | Ngày ISO cũng là "digit − digit" |
| E6 | `Hi? How are you?` | `multi_step +15` | `prompt.count("?") >= 2` không phân biệt câu hỏi thật |
| E7 | `debug nghĩa là gì` | `code +22` | Câu hỏi định nghĩa bị coi là task debug |
| **E8** | `Implement Raft consensus in Go` | `fast_path_easy` → **score 0 → T1** | ≤8 từ + không match lexicon nào → ép T1 |
| **E9** | `Fix my race condition please` | `fast_path_easy` → **score 0 → T1** | như trên |
| **E10** | `Build a distributed rate limiter` | `fast_path_easy` → **score 0 → T1** | như trên |

E8–E10 nghiêm trọng nhất: đây là **under-routing các task khó nhất trong domain** xuống model rẻ nhất, vi phạm trực tiếp rủi ro R1 trong `06_architecture.md` và tiêu chí AC-1.1 ("không prompt hard nào bị gán T1"). Fast-path đang dùng **số từ** làm proxy cho độ dễ, mà độ khó coding gần như **không tương quan với số từ** — "Implement Paxos" là 2 từ.

---

## 2. Chẩn đoán — 5 lỗi cấu trúc (không phải 10 lỗi regex)

Mười triệu chứng ở §1 quy về **năm** nguyên nhân gốc. Sửa từng regex là vá triệu chứng; thiết kế v1.5 sửa nguyên nhân.

| # | Lỗi cấu trúc | Hệ quả | Triệu chứng liên quan |
|---|---|---|---|
| **R1** | **Một vùng văn bản duy nhất.** Văn xuôi, code dán vào, stack trace, log — tất cả bị chấm bằng cùng bộ regex trên cùng một blob. | Từ tiếng Anh thường bị bắt như cú pháp code; code dán vào bị tính như độ dài yêu cầu; nội dung trong backtick nâng điểm. | E1–E3, §1.1 |
| **R2** | **Độ dài dùng làm proxy độ khó.** `length` cộng tối đa +18 theo số token của message. | Độ dài đo *độ dài lời kể*, không đo *khối lượng việc*. Tâm sự dài = đắt; "Implement Paxos" = rẻ. | §1.1, E8–E10 |
| **R3** | **Tín hiệu `code` nhị phân.** Có/không, +22 hoặc 0. | Không phân giải được trong domain mà ~100% request đều là code. | §1.2 |
| **R4** | **Cộng dồn các tín hiệu tương quan.** Một câu chuyện dài về debug kích hoạt `code` + `length` + `multi_step` = +47, nhưng cả ba đều truy về **một** sự kiện ("văn bản dài có nhắc code"), không phải ba độ khó độc lập. | Điểm bị nhân lên bởi cách diễn đạt, không bởi độ khó. | §1.1 |
| **R5** | **Không có bằng chứng ngược, và fast-path đếm từ.** Không tín hiệu nào *trừ* điểm. "hello world", "hai dòng", "ví dụ đơn giản" — bằng chứng dễ rất mạnh — hiện không có tác dụng gì. Đường thoát duy nhất xuống T1 là `≤ 8 từ`. | Task dễ nhưng diễn đạt dài không xuống được T1; task khó nhưng diễn đạt ngắn bị ép xuống T1. | §1.1, E8–E10 |

---

## 3. Nguyên tắc thiết kế

Một câu đổi cả mô hình:

> **Độ khó = hạng phức tạp của *công việc được yêu cầu*, không phải kích thước của *thông điệp mô tả nó*.**

Bốn nguyên tắc dẫn xuất, dùng làm tiêu chí nhận/loại cho mọi quyết định trong tài liệu này:

1. **Phân vùng trước, chấm điểm sau.** Regex nào chạy trên vùng nào phải là quyết định có chủ đích (§4).
2. **Hạng, không phải điểm cộng.** Task coding được xếp vào một trong ba hạng có định nghĩa rõ; hạng quyết định sàn tier. Các tín hiệu phụ chỉ *điều chỉnh trong hạng*, không bao giờ đổi hạng (§5, §6).
3. **Bằng chứng dễ ngang hàng bằng chứng khó.** Marker thu hẹp phạm vi ("hai dòng", "hello world") là tín hiệu hạng nhất, không phải phần thưởng an ủi (§5.3).
4. **Giữ thiên lệch bảo thủ khi thật sự phân vân.** `06_architecture.md` R1 vẫn đúng: đẩy nhầm task khó xuống model rẻ tốn hơn nhiều so với trả dư cho task dễ. v1.5 giảm over-routing bằng cách **phân giải tốt hơn**, không bằng cách hạ ngưỡng bừa.

**Ràng buộc giữ nguyên (không thương lượng):** thuần CPU, không I/O, không LLM call, không bao giờ raise, tự cắt theo `ROUTER_TIMEOUT_MS`, song ngữ Việt–Anh kể cả gõ không dấu — y hệt contract B.2 hiện hành.

---

## 4. Phân vùng văn bản (giải R1)

Message user cuối được tách làm hai vùng trước khi chấm:

| Vùng | Nội dung | Cách nhận diện |
|---|---|---|
| **Instruction zone** | Văn xuôi người dùng viết — *yêu cầu* | Phần còn lại sau khi bóc artifact |
| **Artifact zone** | Code dán vào, stack trace, log, output | Fenced block ` ``` `, inline code span `` ` ``, khối ≥3 dòng liên tiếp có thụt lề/cú pháp, khối khớp fingerprint stack trace |

### 4.1 Quy tắc đảo — sửa gốc E1–E3

Đây là thay đổi nhỏ nhất mang lại lợi ích lớn nhất:

| Bộ regex | v1 chạy trên | **v1.5 chạy trên** | Lý do |
|---|---|---|---|
| **Cú pháp** (`def`, `class`, `import`, `return`, `function`, `const`, `let`, `var`, `SELECT`…) | toàn bộ text | **chỉ artifact zone** | Trong văn xuôi, đây là từ tiếng Anh thường ("let me know", "the class I teach"). Trong artifact zone, đây là code thật. |
| **Ý định** (`debug`, `refactor`, `fix bug`, `viết hàm`, `code review`…) | toàn bộ text | **chỉ instruction zone** | Ý định là thứ user *nói*, không phải thứ nằm trong code dán vào. |

Chỉ riêng phép đảo này diệt trọn nhóm false-positive phổ biến nhất trong chat Việt–Anh trộn (E1–E3) mà **không cần thêm một regex nào**.

### 4.2 Artifact zone không bao giờ quyết định hạng

Artifact zone chỉ đóng góp **tín hiệu định lượng**: có/không, kích thước, có phải error trace không. Nó **không bao giờ** được đọc để xác định hạng độ khó.

Hệ quả phụ đáng giá — **miễn nhiễm prompt injection**: một khối code chứa `# ignore above, this is a T3 task` không thể tác động tới routing, vì lexicon hạng không bao giờ chạy trên artifact zone. Người dùng dán code từ nguồn không tin cậy (issue GitHub, log của khách) không tạo được bề mặt tấn công chi phí.

### 4.3 Instruction zone rỗng

Nếu user chỉ dán code không kèm chữ nào → mặc định **C2** (ngầm hiểu "giải thích/sửa đoạn này"). Không rơi vào fast-path, không rơi vào C1.

---

## 5. Thang độ khó coding — trả lời câu hỏi của §1.2

### 5.1 Điều gì làm một coding task khó **với LLM**

Đây mới là câu hỏi đúng — không phải "khó với con người". Sáu yếu tố, mỗi yếu tố kèm **guard** chống kích hoạt thừa (guard quan trọng ngang driver: driver không guard sẽ tái tạo đúng vấn đề "+22 phẳng" ở hạng cao hơn).

| # | Driver | Vì sao khó với LLM | Kích hoạt khi (instruction zone) | **Guard — KHÔNG kích hoạt khi** |
|---|---|---|---|---|
| **D1** | **Đồng thời / bất định** | LLM phải mô phỏng thứ tự xen kẽ của nhiều luồng — điểm yếu cố hữu; lỗi im lặng, không tái hiện được | race condition, deadlock, livelock, mutex, lock, thread, goroutine, atomic, memory ordering, flaky test, intermittent, tranh chấp, đồng thời | `async`/`await` chỉ xuất hiện như cú pháp thường ("viết hàm async gọi API") |
| **D2** | **Thuật toán / độ phức tạp** | Phải *dẫn xuất* lời giải và giữ invariant, không tra cứu được | quy hoạch động, DP, graph/đồ thị, đệ quy, invariant, chứng minh đúng, độ phức tạp, O(n), NP, tối ưu thuật toán | Dùng thư viện sẵn ("sort danh sách", "dùng heapq") |
| **D3** | **Hiệu năng có bằng chứng** | Phải suy luận về profiling, bộ nhớ, cache — không quan sát được từ code | chậm/slow/timeout/bottleneck/memory leak/OOM/profil **kèm** số đo hoặc quy mô ("30s", "1M rows", "p95") | "optimize" trần trụi, "làm nhanh hơn" không kèm bằng chứng → **C2** |
| **D4** | **Phạm vi hệ thống / kiến trúc** | Phải giữ mô hình lớn hơn context, quyết định có hệ quả lan rộng | thiết kế hệ thống, kiến trúc, migration, schema design, microservice, distributed, consensus, refactor **nhiều module**, event sourcing | Refactor một hàm, đổi tên trong một file |
| **D5** | **Chẩn đoán không rõ nguyên nhân** | Phải sinh và loại giả thuyết, không có triệu chứng chỉ thẳng | "không biết tại sao", "đã thử ... vẫn lỗi", "chỉ xảy ra trên prod", heisenbug, intermittent, "lúc được lúc không" | Thông báo lỗi đã nêu đúng nguyên nhân + dòng (SyntaxError, ImportError, NameError) → **C1** |
| **D6** | **Đúng-đắn nghiêm ngặt** (bảo mật / tiền / giao dịch) | Sai lầm im lặng và tốn kém; đòi hỏi lập luận đối kháng | **thiết kế/phân tích** + crypto, threat model, auth scheme, token rotation, ACID, transaction isolation, làm tròn tiền/Decimal | ***Dùng* thư viện có sẵn** — "add JWT auth với fastapi-users", "tích hợp Stripe" → **C2** |

> **Guard của D6 là có chủ đích, để giữ nhất quán với `08_adaptive_routing.md` §1**, nơi ví dụ walkthrough gán `"Add JWT authentication"` → **T2**. Tích hợp thư viện auth là C2; *thiết kế* cơ chế auth chống replay là C3.

### 5.2 Điều gì làm một coding task dễ

| # | Marker | Vì sao dễ | Ví dụ |
|---|---|---|---|
| **M1** | **Biến đổi cơ học** — không đổi ngữ nghĩa, không cần hiểu logic | Ánh xạ 1-1, kiểm chứng được ngay | format/lint, đổi tên biến, thêm docstring/comment, thêm type hint, sửa thụt lề, JSON↔YAML |
| **M2** | **Tra cứu / boilerplate** | Nằm sẵn trong trọng số model, không cần suy luận | "đọc file JSON trong Python thế nào", regex email, CRUD chuẩn, cú pháp thư viện phổ biến |
| **M3** | **Định nghĩa / giải thích khái niệm** | Là câu hỏi kiến thức, không phải task | "list và tuple khác nhau gì", "debug nghĩa là gì", "what is a closure" |
| **M4** | **Lỗi cú pháp đã định vị** | Thông báo lỗi đã nêu nguyên nhân + dòng | `SyntaxError: invalid syntax, line 12`, thiếu import, sai tên biến |
| **M5** | **Phạm vi thu hẹp tường minh** | User tự khai báo task nhỏ | "hello world", "hai dòng", "vài dòng", "một hàm nhỏ", "ví dụ đơn giản", "minimal", "toy", "cho người mới", "for learning" |

**M5 chính là liều thuốc cho §1.1.** Trong kịch bản kể chuyện, cụm "nó chỉ có hai dòng thôi" và "hello world" là bằng chứng *mạnh nhất* trong toàn bộ message — mạnh hơn nhiều so với việc câu chuyện dài 6 dòng. v1 bỏ qua hoàn toàn; v1.5 cho nó quyền quyết định hạng.

### 5.3 Ba hạng và quy tắc ưu tiên

```
is_coding = có động từ ý định coding (instruction zone)
          ∨ có danh từ kỹ thuật (instruction zone)
          ∨ artifact zone chứa code / stack trace

nếu KHÔNG is_coding  → nhánh non-coding (§6.3)

band = C3   nếu bất kỳ driver D1..D6 nào kích hoạt (đã qua guard)
     = C1   ngược lại, nếu bất kỳ marker M1..M5 nào kích hoạt
     = C2   ngược lại (mặc định)
```

**Ưu tiên `C3 > C1 > C2` là có chủ đích, không phải typo.** Driver khó luôn thắng marker dễ: user viết *"fix nhanh giúp mình cái deadlock đơn giản này"* vẫn ra **C3** — "đơn giản" không hạ được một bài toán đồng thời. Ngược lại, khi không có driver khó nào, marker dễ **thắng mặc định C2** — đó là cơ chế đưa hello-world về T1. C2 là hạng *mặc định*, nghĩa là "coding task bình thường, không có bằng chứng nào theo hướng nào".

Không có bước "demote" riêng: marker dễ *chính là* điều kiện vào C1. Một quy tắc, không có số học hạ hạng.

| Hạng | Định nghĩa một câu | Thuộc hạng này |
|---|---|---|
| **C1 — Cơ học / tra cứu** | Không cần hiểu logic chương trình để làm đúng | M1–M5 (§5.2) |
| **C2 — Hiện thực tiêu chuẩn** | Cần hiểu logic, nhưng đường đi đã rõ | Viết hàm/class/endpoint/component; thêm feature vào code có sẵn; viết unit test; review một diff; debug thường có trace định vị được; **port/dịch giữa hai ngôn ngữ**; giải thích code không tầm thường |
| **C3 — Sâu** | Cần dẫn xuất, giữ mô hình lớn, hoặc lập luận đối kháng | D1–D6 (§5.1) |

> **Vì sao "port Python → JavaScript" là C2 chứ không phải C1:** nhìn thì cơ học, nhưng phải giữ *tương đương ngữ nghĩa* qua hai hệ thống kiểu và hai mô hình thư viện khác nhau — đó là hiểu logic, không phải ánh xạ 1-1. Đây đúng là ranh giới C1/C2 và cần nêu rõ để tránh tranh cãi khi gán nhãn eval.

---

## 6. Mô hình chấm điểm v1.5

### 6.1 Công thức

```
NHÁNH CODING:
    score = band_base + min( Σ modifiers , MODIFIER_CAP )
    score = max( score , band_floor )

NHÁNH NON-CODING:
    score = tín hiệu cộng dồn như v1 (đã sửa lỗi regex §6.4)
```

| Hạng | `band_base` | `band_floor` | Tier tự nhiên | Trần khi cộng đủ modifier |
|---|---|---|---|---|
| **C1** | 8 | — | T1 | 8 + 18 = **26 → vẫn T1** |
| **C2** | 32 | 30 | T2 | 32 + 18 = **50 → vẫn T2** |
| **C3** | 62 | 60 | T3 | **T3** |

`MODIFIER_CAP = 18`.

**Hai thuộc tính quan trọng của bộ số này:**

1. **Modifier không bao giờ đổi được tier.** C1 kịch trần = 26 < 30, C2 kịch trần = 50 < 60. Nghĩa là **hạng quyết định tier; modifier chỉ xếp hạng bên trong tier** (phục vụ giải trình và ngưỡng vùng mơ hồ của v2 sau này). Đây là hàng rào cấu trúc chống lại chính lỗi R4 — không có cách nào để cộng dồn tín hiệu tương quan đẩy một task C1 lên T2 nữa.
2. **`band_floor` chống hạ điểm từ nhánh khác**, và giữ tier ổn định khi Session Router lấy `cls.score` thô để kiểm tra margin de-escalate (§9.2).

### 6.2 Modifiers (nhánh coding)

| Modifier | Điểm | Kích hoạt | Trạng thái cài đặt |
|---|---|---|---|
| `error_artifact` | +8 | Artifact zone chứa stack trace / exception thật | **Tái dùng** `_has_new_error_artifact` của `turn_analyzer.py` |
| `artifact_large` | +6 | Artifact zone > 150 token | Mới (2 dòng) |
| `multi_file` | +6 | Nhắc ≥2 file/module, hoặc "toàn bộ codebase", "across the codebase" | Mới (1 regex) |
| `output_constraint` | +6 | JSON schema, định dạng chính xác | **Tái dùng** v1 |
| `multi_step` | +6 | Chỉ khi band ∈ {C1, C2} — C3 đã hàm ý đa bước | **Tái dùng** v1 (đã sửa §6.4) |
| `long_context` | +6 | Tổng context > 2.000 token | **Tái dùng** v1 |

Tổng cộng chỉ **2 detector mới**; bốn cái còn lại đã có trong repo.

> **`length` bị loại hoàn toàn khỏi nhánh coding.** Đây là thay đổi đơn lẻ quan trọng nhất của v1.5 và là lời giải trực tiếp cho §1.1. Độ dài văn xuôi không còn đóng góp một điểm nào cho độ khó coding. Khối lượng thật được đo bằng `artifact_large` (bao nhiêu code) và `multi_file` (bao nhiêu phạm vi) — hai thứ *thực sự* tỉ lệ với công việc — chứ không bằng việc user tâm sự dài hay ngắn.
>
> Giới hạn context vẫn được bảo vệ ở hai lớp độc lập: token guard 8.000 (`MAX_INPUT_TOKENS` trong `chat_completions.py`) và bộ lọc `context_window` của Policy Engine (`08_adaptive_routing.md` §8). Không cần `length` gánh thêm nhiệm vụ đó.

### 6.3 Nhánh non-coding

Giữ nguyên mô hình cộng dồn của v1 (`math`, `multi_step`, `output_constraint`, `long_creative`, `length`, `long_context`) — **không đụng tới**, vì domain trọng tâm là coding và mô hình v1 hoạt động chấp nhận được ở đây. Chỉ áp các bản sửa lỗi regex ở §6.4, vốn là sửa lỗi thuần tuý chứ không đổi thiết kế.

### 6.4 Sửa lỗi regex (diệt E4–E7)

| Lỗi | Sửa |
|---|---|
| E4, E5 — `2-3 ngày`, `2026-08-21` → `math` | `_MATH_EXPR_RE` chỉ kích hoạt khi **(a)** có `=` với số ở hai vế, **hoặc (b)** có ≥2 toán tử khác nhau, **hoặc (c)** đi kèm một từ khóa toán. Khoảng số và ngày ISO không thoả điều kiện nào. |
| E6 — `Hi? How are you?` → `multi_step` | Đếm câu hỏi **trong instruction zone**, và chỉ tính câu hỏi có ≥4 từ. Đồng thời loại `?.` / `?:` trong code vì artifact zone đã bị bóc ra. |
| E7 — `debug nghĩa là gì` → task debug | Marker **M3** (định nghĩa) → C1. |
| E1–E3 | Đã giải bằng quy tắc đảo §4.1, không cần regex mới. |

### 6.5 Fast-path viết lại (diệt E8–E10)

```
fast_path_easy  ⟺  khớp regex chào hỏi/cảm ơn/ack
                ∨  ( ≤ 8 từ  ∧  KHÔNG phải coding task  ∧  không tín hiệu non-coding nào )
```

Điều kiện `KHÔNG phải coding task` là bản vá: `Implement Raft consensus in Go` có động từ ý định (`implement`) + danh từ kỹ thuật (`consensus`) → là coding task → **không bao giờ** vào fast-path → D4 kích hoạt → C3 → T3. Số từ mất quyền phủ quyết.

### 6.6 Ví dụ chấm điểm đầy đủ

| Prompt | Nhánh | Hạng (vì sao) | base | modifiers | score | tier |
|---|---|---|---|---|---|---|
| `Fix this: print("hello world")` | coding | C1 (M5 "hello world") | 8 | — | **8** | T1 |
| Kể chuyện 6 dòng + fence + "debug giúp mình, chỉ hai dòng thôi" | coding | **C1** (M5 "hai dòng", "hello world") | 8 | `multi_step` 6 | **14** | **T1** ✔ |
| `Đọc file JSON trong Python thế nào?` | coding | C1 (M2) | 8 | — | **8** | T1 |
| `SyntaxError: invalid syntax, line 12` + code | coding | C1 (M4) | 8 | `error_artifact` 8 | **16** | T1 |
| `Thêm docstring cho file này` + 400 dòng | coding | C1 (M1) | 8 | `artifact_large` 6 | **14** | T1 |
| `Viết hàm parse CSV` | coding | C2 (mặc định) | 32 | — | **32** | T2 |
| `Viết unit test cho class này` + 80 dòng | coding | C2 | 32 | — | **32** | T2 |
| `TypeError: NoneType...` + traceback 200 dòng | coding | C2 (trace định vị được) | 32 | `error_artifact` 8 + `artifact_large` 6 = 14 | **46** | T2 |
| ...cùng trace + *"đã thử đủ cách vẫn lỗi, chỉ xảy ra trên prod"* | coding | **C3 (D5)** | 62 | (trần) | **≥62** | **T3** |
| `Add JWT auth với fastapi-users` | coding | C2 (**guard D6**) | 32 | — | **32** | T2 |
| `Thiết kế cơ chế token rotation chống replay` | coding | C3 (D6) | 62 | — | **62** | T3 |
| `Fix my race condition please` | coding | C3 (D1) | 62 | — | **62** | **T3** ✔ |
| `Implement Raft consensus in Go` | coding | C3 (D4) | 62 | — | **62** | **T3** ✔ |
| `Query này chạy 30s, tối ưu giúp` | coding | C3 (D3, có số đo) | 62 | — | **62** | T3 |
| `Tối ưu hàm này cho nhanh hơn` | coding | C2 (**guard D3** — không bằng chứng) | 32 | — | **32** | T2 |
| `Let me know when you are free` | non-coding | — | — | — | **0** | T1 |
| `Tôi cần giao hàng trong 2-3 ngày` | non-coding | — | — | — | **0** | T1 |

Hai dòng in đậm đầu tiên là **bất biến trung tâm** của v1.5: cùng một task hello-world, kể chuyện hay không kể chuyện, đều ra T1.

---

## 7. Bảng tín hiệu v1.5 (bản tóm tắt thay cho PRD §6.2 khi land)

| Tín hiệu | Cách phát hiện | Điểm | Vùng |
|---|---|---|---|
| `band_c1` | Marker M1–M5 (§5.2) | +8 | instruction |
| `band_c2` | Coding task mặc định | +32, sàn 30 | instruction |
| `band_c3` | Driver D1–D6 đã qua guard (§5.1) | +62, sàn 60 | instruction |
| `error_artifact` | Stack trace / exception | +8 | artifact |
| `artifact_large` | Artifact > 150 token | +6 | artifact |
| `multi_file` | ≥2 file/module, "toàn bộ codebase" | +6 | instruction |
| `output_constraint` | JSON schema, định dạng chính xác | +6 | instruction |
| `multi_step` | Từ khóa đa bước / ≥2 câu hỏi thật (chỉ C1, C2) | +6 | instruction |
| `long_context` | Context > 2.000 token | +6 | toàn bộ messages |
| `fast_path_easy` | Chào hỏi/ack, hoặc ≤8 từ **và không phải coding task** | ép T1 | instruction |
| *(non-coding)* `math`, `long_creative`, `length` | Như v1, đã sửa §6.4 | như v1 | instruction |

`MODIFIER_CAP = 18` · Ánh xạ tier giữ nguyên: `<30 → T1`, `30–59 → T2`, `≥60 → T3`.

Mọi tín hiệu kích hoạt vẫn được ghi vào `signals` để giải trình (NFR-05) — v1.5 **tăng** khả năng giải trình: `signals` giờ nêu được *hạng* và *driver nào* kích hoạt, thay vì chỉ "code +22".

---

## 8. Ma trận trường hợp — quét toàn bộ

Bảng dưới là kiểm thử thiết kế: mỗi dòng là một tình huống có thể xảy ra, kết quả v1 (đo được hoặc suy ra từ luật) và kết quả v1.5 dự kiến.

### 8.1 Over-routing (v1 tính quá cao)

| # | Tình huống | v1 | v1.5 | Cơ chế sửa |
|---|---|---|---|---|
| O1 | Kể chuyện dài + task hello-world | T2 (47) | **T1** (14) | §6.2 bỏ `length` + M5 |
| O2 | "let me know / return to hometown / the class I teach" | code +22 | **0** | §4.1 quy tắc đảo |
| O3 | Dán 400 dòng code, xin thêm docstring | length +18 → T2 | **T1** | `length` không còn ở nhánh coding; M1 |
| O4 | Dùng backtick để trích tên file / 1 dòng log | code +22 (fence) | artifact zone, không đổi hạng | §4.2 |
| O5 | "2-3 ngày", "2026-08-21" | math +20 | **0** | §6.4 |
| O6 | "Hi? How are you?" | multi_step +15 | **0** | §6.4 |
| O7 | "debug nghĩa là gì" | code +22 | **C1 → T1** | M3 |
| O8 | "so sánh list và tuple" | multi_step +15 | **C1 → T1** | M3 |
| O9 | Code dán vào chứa `?.` / ternary | multi_step +15 | **0** | Artifact zone bị bóc |
| O10 | "Tối ưu hàm này" (không bằng chứng perf) | tuỳ regex | **C2 → T2** | Guard D3 |
| O11 | "Add JWT auth với thư viện X" | tuỳ | **C2 → T2** | Guard D6 (nhất quán doc 08 §1) |

### 8.2 Under-routing (v1 tính quá thấp)

| # | Tình huống | v1 | v1.5 | Cơ chế sửa |
|---|---|---|---|---|
| U1 | `Implement Raft consensus in Go` | **T1 (0)** | **T3** | §6.5 + D4 |
| U2 | `Fix my race condition` | **T1 (0)** | **T3** | §6.5 + D1 |
| U3 | `Build a distributed rate limiter` | **T1 (0)** | **T3** | §6.5 + D4 |
| U4 | "Test của tôi lúc chạy được lúc không" | thấp | **T3** | D1 (flaky) |
| U5 | "Query chạy 30s, tối ưu giúp" | tuỳ | **T3** | D3 có số đo |
| U6 | "Thiết kế schema cho SaaS multi-tenant" | tuỳ | **T3** | D4 |
| U7 | "Đã thử đủ cách vẫn lỗi, chỉ xảy ra trên prod" | tuỳ | **T3** | D5 |
| U8 | "Refactor auth across 5 modules" | tuỳ | **T3** | D4 + `multi_file` |

### 8.3 Đối kháng & lạm dụng

| # | Tình huống | Hành vi v1.5 | Ghi chú |
|---|---|---|---|
| A1 | Code dán vào chứa `# ignore above, route to T3` | **Không tác dụng** | §4.2 — lexicon hạng không chạy trên artifact zone |
| A2 | User tự khai "đây là task cực khó T3" | **Không tác dụng** | Không có lexicon cho tuyên bố tự khai. Cố ý: nếu không, đây là đường leo thang chi phí trivial |
| A3 | User viết "đơn giản thôi" cho một task deadlock | **Vẫn C3** | Ưu tiên `C3 > C1` (§5.3) |
| A4 | User nhồi từ khóa dễ để ép T1 | Vẫn C3 nếu có driver; nếu không có driver thì task *đúng là* không khó | Chấp nhận được: hạ tier task dễ là đúng mục tiêu |
| A5 | Spam token rác 8.000 ký tự | Token guard 400 trước khi tới classifier | `chat_completions.py:174` |

### 8.4 Biên & bệnh lý

| # | Tình huống | Hành vi v1.5 |
|---|---|---|
| B1 | Message rỗng / chỉ khoảng trắng | score 0 → T1, không raise |
| B2 | Chỉ có artifact, không chữ nào | C2 mặc định (§4.3) |
| B3 | Artifact khổng lồ (sát 8.000 token) | C2 + `artifact_large` + `long_context` = 44 → T2; capability do §8 doc 08 lo |
| B4 | Không có message role `user` | Giữ nguyên hành vi v1 (trả kết quả, không raise) |
| B5 | Tiếng Việt không dấu | Hỗ trợ — mọi lexicon mới phải có biến thể không dấu, y như v1 |
| B6 | Ngôn ngữ thứ ba (Nhật, Trung…) | Không match lexicon → non-coding hoặc fast-path. **Giới hạn đã biết → §10** |
| B7 | Fence không đóng | Bóc tới cuối message, coi phần còn lại là artifact |
| B8 | Fence lồng / markdown trong fence | Bóc theo fence ngoài cùng; không parse đệ quy (YAGNI) |
| B9 | Classifier vượt `ROUTER_TIMEOUT_MS` | Giữ nguyên: T2 + `classifier_error`, không raise (contract B.2) |
| B10 | Emoji / unicode nhiễu | Không ảnh hưởng — regex chạy trên nền text |

---

## 9. Tương tác với Session Router (`08_adaptive_routing.md`)

v1.5 không đổi interface, nhưng đổi **phân phối** của `score`, nên bốn điểm nối cần được kiểm lại khi triển khai:

1. **EMA inheritance (§5 doc 08)** — `ema_score` kế thừa `max(score, ema)` qua các lượt. Điểm bơm ở lượt 1 vì kể chuyện dài hiện **làm đắt cả phiên**, không chỉ một request. v1.5 làm sạch nguồn của EMA; đây là chỗ lợi ích cộng dồn lớn nhất, và cũng là chỗ cần đo lại `alpha` sau khi land.
2. **Margin check khi de-escalate (§6 doc 08)** — dùng `cls.score` **thô**. `band_floor` của C3 = 60 khiến margin check hiếm khi trip trong một phiên C3 → phiên giữ T3. Đây là **hành vi mong muốn** (phiên Raft nên ở T3), nhưng phải ghi rõ để không bị chẩn đoán nhầm là "de-escalation hỏng".
3. **`new_task` reset** — lượt 5 là "sửa lỗi chính tả" sau một phiên C3 sẽ được chấm C1 = 8 và reset EMA → về T1. Thiết kế hạng hỗ trợ đúng hành vi này.
4. **Degraded mode (§5.3 doc 08)** — `_init_state_from_messages` suy state từ mảng messages; không bị ảnh hưởng bởi thay đổi này.

---

## 10. Giới hạn còn lại — và vì sao v2 vẫn cần thiết

Trung thực về chỗ v1.5 **vẫn sai**. Đây là input trực tiếp cho quyết định FR-12.

| # | Giới hạn | Ví dụ hỏng |
|---|---|---|
| **L1** | **Driver kích hoạt từ văn kể, không từ yêu cầu.** v1.5 phân vùng prose/artifact, nhưng **không** phân biệt được câu kể với câu yêu cầu *bên trong* instruction zone. | *"Hôm qua tôi fix một cái deadlock kinh khủng, giờ giúp tôi đổi tên biến này"* → D1 kích hoạt từ mệnh đề kể → **C3 → T3**, trong khi task thật là C1. **Đây là dạng còn sót của chính vấn đề §1.1.** |
| L2 | **Ràng buộc lexicon.** Task khó dùng từ ngữ ngoài từ điển → tụt xuống C2 mặc định. | Thuật ngữ domain hẹp, tên thư viện mới |
| L3 | **Ngôn ngữ thứ ba** (B6) | Prompt tiếng Nhật |
| L4 | **Không đo được độ khó thật của code trong artifact** — chỉ đo kích thước | 20 dòng code cực tinh vi vs 20 dòng CRUD |

> **L4 và hai domain input mới → `10_classifier_input_domains.md`.** Tài liệu đó đo được hai loại input mà thang C1/C2/C3 chấm sai hệ thống: (a) **đề competitive programming** — cả dải 800–2600 nén vào T1/T2, không bao giờ chạm T3, vì marker M2 bắt trúng section header `Example` bắt buộc của mọi đề CF; (b) **codebase qua agent harness** — `"Fix this."` + 60 dòng Go có `go func`/`sync.Mutex` chỉ ra **T2**, vì §4.2 cấm artifact zone quyết định band trong khi ở kịch bản này artifact *chính là* mô tả công việc. Doc 10 **sửa đổi §4.2** theo hướng một chiều (bằng chứng *structural* được nâng band, bằng chứng *lexical* vẫn cấm) — đó cũng là lời giải một phần cho L4 ở bảng trên.

**L1 có thể vá một phần** bằng cách chỉ chạy driver trên "câu yêu cầu" (câu chứa `giúp tôi`/`hãy`/`cần bạn`/`please`/`can you`, hoặc câu cuối). Cách này **mong manh** — người Việt đặt yêu cầu ở nhiều vị trí, và tách câu tiếng Việt không đáng tin. **Quyết định: không xây bây giờ.** Ghi nhận là residual đã biết, đo tần suất trên dataset §11, và để **classifier v2 sở hữu** — đây chính là loại phân biệt ngữ nghĩa mà LLM tie-breaker (`08_adaptive_routing.md` §9.1, PRD §6.3) giải được còn regex thì không.

> **Kết luận cho lộ trình:** v1.5 diệt được toàn bộ lỗi *cơ học* (E1–E10, O1–O11, U1–U8) với chi phí $0 và không I/O. Phần còn lại (L1–L4) là **ngữ nghĩa**, và chỉ ngữ nghĩa. Điều này làm luận điểm cho v2 **mạnh hơn và rẻ hơn**: sau v1.5, vùng cần LLM tie-breaker hẹp lại đúng vào vùng mơ hồ thật sự, khớp với van kiểm soát chi phí #1 ở §9.1 doc 08 (`|score − ngưỡng| < 8`).

---

## 11. Tiêu chí chấp nhận & eval

### 11.1 Cổng bắt buộc (không đạt → không merge)

| Cổng | Tiêu chí | Nguồn |
|---|---|---|
| G1 | **Zero hard → T1.** Không prompt nhãn hard nào bị gán T1 | AC-1.1, PRD §3.2 |
| G2 | Accuracy ≥ 80% trên bộ 30 prompt gán nhãn hiện có | AC-1.1 |
| G3 | **Bất biến kể chuyện (mới).** Với mỗi cặp (task trần, task bọc trong văn kể), tier phải **giống nhau** ở ≥95% cặp | §1.1 — đây là bug gốc |
| G4 | **Phân giải hạng (mới).** Accuracy ≥85% trên `coding_bands_60.jsonl` khi phân 3 hạng | §5 |
| G5 | E1–E10 có regression test, tất cả pass | §1.3 |
| G6 | Router p95 < 300ms, hard cap 800ms | NFR-01, ADR-009 |

### 11.2 Dataset cần thêm

| File | Nội dung |
|---|---|
| `src/evals/datasets/coding_bands_60.jsonl` | 60 prompt coding gán nhãn hạng, **20/hạng**, song ngữ Việt–Anh (có biến thể không dấu), phủ đủ D1–D6 và M1–M5 |
| `src/evals/datasets/narrative_pairs_20.jsonl` | 20 **cặp** (task trần ↔ task bọc văn kể) — bộ test cho G3 |

Nhãn hạng do 2 người gán độc lập; bất đồng → thảo luận chốt, ghi vào `annotation_review.md` như quy trình đang dùng.

### 11.3 Regression đã biết trên test hiện có

Các test sau **sẽ đỏ** và phải được cập nhật cùng PR — đây là thay đổi thiết kế có chủ đích, không phải test hỏng:

| Test (`src/gateway/tests/test_classifier.py`) | Vì sao đổi |
|---|---|
| `test_tin_hieu_code_cong_22` | `code +22` phẳng không còn tồn tại → thay bằng assert hạng |
| `test_cau_ngan_nhung_co_tin_hieu_thi_khong_fast_path` | Assert `code == 22` → đổi sang assert band |
| `test_prompt_trung_binh_cong_10`, `test_prompt_dai_cong_18` | `length` bị loại khỏi nhánh coding → giữ test nhưng chuyển sang prompt non-coding |
| `test_cong_don_nhieu_tin_hieu_len_t3` | Cộng dồn không còn là cơ chế lên T3 → đổi sang prompt có driver C3 |

Không đổi: toàn bộ test fallback/timeout/không-raise (contract B.2 giữ nguyên).

---

## 12. Kế hoạch triển khai

| Bước | Việc | Verify |
|---|---|---|
| 1 | `zoning.py` — tách instruction/artifact zone | Unit test: fence, inline code, trace, fence không đóng (B7), fence lồng (B8) |
| 2 | Áp quy tắc đảo §4.1 + sửa regex §6.4 lên v1 hiện tại | E1–E7 pass; bộ 30 prompt **không tụt** accuracy |
| 3 | Lexicon D1–D6 + M1–M5 + động từ ý định/danh từ kỹ thuật | `coding_bands_60.jsonl` đạt G4 (≥85%) |
| 4 | Hàm `band()` + công thức chấm §6.1 + fast-path mới §6.5 | E8–E10 pass; G1 zero hard→T1 |
| 5 | Bảng ví dụ §6.6 thành test tham số hoá | 17/17 dòng khớp tier mong đợi |
| 6 | `narrative_pairs_20.jsonl` + test bất biến | G3 ≥95% |
| 7 | Chạy lại `mixed_200.jsonl`, so phân bố tier v1 vs v1.5 | Ghi lại dịch chuyển phân bố + savings% vào eval report; G6 latency |
| 8 | `classifier_version = "heuristic-v1.5"`; bổ sung giá trị này vào contract B.2 trong `05_interfaces.md` | Log và `/admin/requests/{id}` phân biệt được request chấm bằng v1 vs v1.5 — cần cho so sánh A/B ở bước 7 |
| 9 | Cập nhật PRD §6.2 sang bảng §7 | Code và PRD khớp nhau |

**Thứ tự có chủ đích:** bước 2 mang lại phần lớn lợi ích (diệt E1–E7) với diff nhỏ nhất và **không** đổi mô hình chấm điểm — có thể merge độc lập nếu bước 3–4 chậm.

---

## 13. Ranh giới phạm vi

**Trong phạm vi:** phân vùng văn bản, thang hạng coding, mô hình chấm điểm mới, sửa lỗi regex, fast-path mới, dataset + eval cho những thứ đó.

**Ngoài phạm vi (cố ý):**
- Bất kỳ LLM/embedding call nào → FR-12, PRD §6.3, doc 08 §9.1.
- Đổi ngưỡng tier (30/60) hay `tier_shift` của policy → PRD §6.4 sở hữu.
- Tách câu yêu cầu vs câu kể (L1) → v2.
- Đổi nhánh non-coding ngoài phần sửa lỗi → không cần cho domain trọng tâm.
- `router_cost_usd` → doc 08 §9.1; v1.5 giữ chi phí router = **$0**.

---

**Changelog**
- v1.0 (21/08/2026) — bản đầu. Chẩn đoán 5 lỗi cấu trúc của classifier v1 (§2) từ 10 lỗi đo được (§1.3); thiết kế phân vùng instruction/artifact kèm quy tắc đảo cú pháp↔ý định (§4); thang độ khó coding C1/C2/C3 với 6 driver khó + 5 marker dễ, mỗi driver kèm guard chống over-fire (§5); mô hình chấm điểm band-base + modifier có trần + sàn tier, loại bỏ `length` khỏi nhánh coding (§6); ma trận 34 trường hợp gồm over/under-routing, đối kháng và biên (§8); phân tích tương tác với Session Router (§9); ghi nhận trung thực residual L1–L4 và bàn giao cho classifier v2 (§10); cổng eval G1–G6 kèm 2 dataset mới và danh sách regression test đã biết (§11).
