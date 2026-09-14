# Classifier — hai domain input mà v1.5 không phủ: đề competitive programming & codebase qua agent harness

**v1.0 · 2026-08-21 · File: `docs/design/10_classifier_input_domains.md` · Phạm vi: sau M3 / hậu demo**

> **Vị trí trong bộ tài liệu:** tài liệu này **mở rộng** `09_classifier_v1_5.md`, không thay thế. Doc 09 sở hữu thang C1/C2/C3 và luật phân vùng instruction/artifact; doc 10 xử lý **hai loại input mà thang đó chấm sai một cách hệ thống**, và **sửa đổi có chủ đích §4.2 của doc 09** (mục §6.1 dưới đây nêu rõ sửa cái gì và vì sao). Không thuộc FR-12: phần A vẫn thuần CPU; phần B đề xuất một sandbox tuỳ chọn và nêu rõ chi phí. Khi lệch nhau về requirement → `02_prd.md` thắng; về technical decision → `06_architecture.md` thắng.

---

## 1. Bối cảnh

Doc 09 giả định input là **một người viết yêu cầu bằng prose, kèm (tuỳ chọn) một đoạn code dán vào**. Toàn bộ thiết kế dựa trên giả định đó: intent regex chạy trên instruction zone, syntax regex chạy trên artifact zone, và artifact **không bao giờ** quyết định band (§4.2).

Có hai loại input phá vỡ giả định này:

**A. Đề competitive programming (Codeforces, AtCoder, ICPC).** Prose rất dài nhưng là *đề bài*, không phải *lời kể*. Độ khó thật nằm ở thuật toán cần phát minh — thứ hoàn toàn **không xuất hiện trong văn bản**.

**B. Code từ codebase thật, qua agent harness.** Người dùng cắm SmartRoute vào Claude Code / Cursor / một agent tự viết. Harness đọc file từ repo rồi gửi kèm một chỉ thị **cực ngắn**. Instruction zone gần như rỗng; artifact zone mang toàn bộ thông tin.

Cả hai đều là kịch bản thật của sản phẩm: (A) là demo "SmartRoute giải được bài khó", (B) là **con đường tích hợp chính** khi mở API cho người dùng ngoài.

---

## 2. Số đo trên `classifier_v1_5.py` hiện tại

Chạy trực tiếp trên implementation ngày 21/08/2026.

### 2.1 Đề Codeforces

Đề tổng hợp, viết đúng format CF (Time limit / Memory limit / Input / Output / Example), nhãn độ khó là do tôi gán theo dạng bài:

| Đề | Dạng bài | Tín hiệu v1.5 | Score | Tier | Đúng ra |
|---|---|---|---|---|---|
| ~800 | chia hết, một phép tính | `band_c1` | **8** | **T1** | T1 ✔ |
| ~1400 | greedy / hai con trỏ | `band_c1` | **8** | **T1** | T2 ✘ |
| ~2100 | cây + XOR trie + update/query | `band_c2` | **32** | **T2** | T3 ✘ |
| ~2600 | segment tree beats, n,q ≤ 10⁶ | `band_c2` | **32** | **T2** | T3 ✘ |
| bare | đề rút gọn một dòng | `band_c2` | **32** | **T2** | T1 ✘ |

Toàn bộ dải **1800 điểm rating** nén vào đúng **hai** tier, và **không đề nào chạm T3**. Classifier có **độ phân giải bằng không** trên trục độ khó của CP.

### 2.2 Input kiểu agent harness

| Input | Tín hiệu v1.5 | Score | Tier | Đúng ra |
|---|---|---|---|---|
| `"Fix this."` + 60 dòng Go có `go func`, `sync.Mutex`, closure capture bug | `band_c2` + `artifact_large` | **38** | **T2** | T3 ✘ |
| `"Fix the failing test in scheduler_test.go"` (không dán code) | `band_c2` | **32** | **T2** | T2 ✔ |
| Lượt agent kèm dump tool-result 100 dòng | `band_c2` | **32** | **T2** | — |
| `"Rename the variable x to count."` + 200 dòng | `band_c1` + `artifact_large` | **14** | **T1** | T1 ✔ |

Dòng 1 là ca đắt nhất: đoạn Go đó có **bug đua dữ liệu thật** (biến `job` bị bắt trong closure của goroutine). Con người nhìn 5 giây là thấy đây là việc C3. `_check_d1()` không hề kích hoạt, vì D1 chỉ quét **instruction zone**, mà instruction zone đúng bằng hai chữ `"Fix this."`.

### 2.3 Phân biệt đo được và suy ra

Bảng §2.1 và §2.2 là **số đo thật**. Ba mệnh đề dưới đây là **suy luận từ đọc regex, chưa chạy để xác nhận** — cần kiểm chứng trước khi dựa vào:

* **(H1)** Lý do đề ~800 và ~1400 rơi vào `band_c1` là do `_MARKER_M2_RE` chứa nhánh `|example|`, mà **`Example` là section header bắt buộc của mọi đề Codeforces**. Hai đề rơi C1 đều có section `Example`; hai đề rơi C2 thì bản tổng hợp của tôi không có. Nếu H1 đúng, đây là lỗi nặng nhất trong nhóm A: *mọi* đề CF thật đều có `Example`, nên *mọi* đề CF thật đều bị M2 kéo xuống C1 → T1, kể cả đề 3000.
* **(H2)** `Message.content` được khai báo là `str` (`interfaces.py:26`). Chưa kiểm chứng `chat_completions.py` chuẩn hoá message `role="tool"` và content dạng list-of-blocks (định dạng agent harness thường dùng) ra sao.
* **(H3)** `_prompt_text()` trả **message `role="user"` cuối cùng**. Trong vòng lặp agent, các lượt ở giữa là `assistant`/`tool`, nên message user cuối có thể nằm cách đó 20 lượt — classifier sẽ chấm lại **cùng một prompt cũ** ở mọi lượt. Đọc code thì thấy vậy, chưa chạy để xác nhận trên mảng messages thật.

---

# Phần A — Đề competitive programming

## 3. Chẩn đoán

### 3.1 Rating **không phải** thuộc tính của văn bản

Đây là điểm gốc, và nó quyết định toàn bộ phần còn lại.

Rating của một bài Codeforces được tính từ **thống kê số người giải được** trong contest — nó là một đại lượng đo trên *quần thể thí sinh*, không phải một đặc trưng của *chuỗi ký tự đề bài*. Hệ quả:

* Một bài 800 và một bài 2400 có thể có đề **gần như giống hệt nhau** về độ dài, cấu trúc, từ vựng và cỡ ràng buộc. Cả hai đều "cho mảng `a` gồm `n` số, `n ≤ 2·10⁵`, trả lời `q` truy vấn".
* Cái làm bài 2400 khó là **lời giải phải phát minh ra** — và bản chất của competitive programming là đề bài *cố tình giấu* lời giải. Nếu đề lộ thuật toán thì nó không còn khó.

Nói cách khác: **thông tin cần để chấm độ khó không nằm trong input**. Không có classifier nào — regex hay LLM — khôi phục được nó từ mỗi văn bản đề.

### 3.2 v1.5 đang đọc boilerplate, không đọc độ khó

Nhìn lại §2.1: hướng sai **tương quan với section header**, không tương quan với độ khó. Hai đề có `Example` → C1; hai đề không có → C2. Nếu H1 đúng thì classifier thực chất đang chấm điểm **format tài liệu**.

Đây đúng là **cùng một căn bệnh với narrative inflation ở doc 09 §1.1**, chỉ dịch lên một tầng: v1 đọc *độ dài lời kể*, v1.5 (trên input CP) đọc *khung tài liệu*. Cả hai đều là đặc trưng bề mặt tương quan giả với độ khó.

Điều này cũng cho thấy giới hạn của marker M2/M3 nói chung: các từ `example`, `template`, `snippet` là **marker dễ trong ngữ cảnh chat**, nhưng là **từ vựng trung tính trong tài liệu kỹ thuật**. Marker dễ chỉ an toàn khi input là hội thoại.

### 3.3 Cái gì thực sự trích được từ đề CF

Xếp theo độ tin cậy:

| Bậc | Tín hiệu | Độ tin cậy | Ghi chú |
|---|---|---|---|
| 1 | **Đây có phải đề CP không** (genre) | **rất cao** | Thuần cấu trúc: `Time limit per test`, `Memory limit per test`, bộ ba `Input`/`Output`/`Example`, ký hiệu ràng buộc `1 ≤ n ≤ 2·10⁵`, `the number of test cases` |
| 2 | **Lớp độ phức tạp bắt buộc** suy từ ràng buộc | trung bình | `n ≤ 10¹⁸` → toán/ma trận; `n,q ≥ 10⁵` cả hai → cấu trúc dữ liệu; `n ≤ 20` → mũ/bitmask |
| 3 | **Marker kỹ thuật** | yếu–trung bình | `998244353` (số nguyên tố NTT → đếm/DP/đa thức, lệch về ≥1600), `interactive problem`, `count the number of ways`, cây + truy vấn cập nhật |
| 4 | **Độ dài đề, độ phong phú từ vựng, câu chuyện dẫn nhập** | **bằng không** | Phải loại bỏ. "Monocarp có n cái kẹo" không nói gì về độ khó |

Bậc 1 gần như hoàn hảo. Bậc 2–3 chỉ gợi ý *kỹ thuật nào sẽ dùng*, gợi ý rất kém về *khó tới đâu*. Bậc 4 phải bị chặn — và hiện **không** bị chặn.

### 3.4 Bất đối xứng chi phí trong CP lớn hơn hẳn domain khác

Competitive programming **không có điểm thành phần**. Lời giải sai 1% cũng là 0 điểm. Nên:

* **Under-route** (đưa bài 2100 cho model T1): xác suất thành công ≈ 0. Người dùng trả tiền cho một câu trả lời **chắc chắn vô giá trị**, và mất niềm tin.
* **Over-route** (đưa bài 800 cho model T3): tốn thêm tiền cho **một** lần gọi. Kết quả vẫn đúng.

Chênh lệch này lớn hơn nhiều so với domain coding thường (nơi model yếu vẫn cho code chạy được một phần, người dùng sửa tiếp). Nên với genre = CP, **default hợp lý là cao, không phải giữa**.

### 3.5 Đề CP tự mang theo test oracle — đây là lối thoát thật

Điểm độc nhất của CP mà không domain nào khác có: **mỗi đề đều kèm sample Input/Output ngay trong văn bản**.

Nghĩa là ta **không cần dự đoán độ khó trước**. Ta có thể **kiểm chứng sau**, rất rẻ:

1. Route lạc quan (C2/T2).
2. Trích block `Example` → chạy lời giải sinh ra với sample input.
3. Output khác sample → **bằng chứng thất bại ground-truth**, không phải suy đoán.
4. Escalate.

Đây là chuyển một bài toán **dự đoán không giải được** thành một bài toán **kiểm chứng rẻ**. Về mặt kiến trúc nó khớp sẵn với Session Router: bước 3 chính là `unresolved_failure` + `failure_boost` trong `08_adaptive_routing.md` §6.1.

## 4. Thiết kế A

### 4.1 Nhận diện genre trước, chấm band sau

Chèn **trước** `_determine_band()`, vì genre quyết định luật nào được áp dụng:

```
_CP_MARKER_RE:  "time limit per test" | "memory limit per test"
              | "the number of test cases"
              | "for each test case"
              | ràng buộc: \d\s*[≤<]=?\s*[a-z]\s*[≤<]=?\s*\d+\s*[·*^]?\s*10\s*\^?\s*\d
              | bộ ba dòng riêng: ^Input$ ... ^Output$ ... ^Examples?$

genre = CP  ⟺  khớp ≥ 2 marker khác nhau
```

Ngưỡng **≥2** là cần thiết: một mình chữ `Output` xuất hiện trong vô số request thường.

### 4.2 Band cho genre = CP

```
genre == CP:
    bỏ qua toàn bộ marker M1–M5      ← sửa H1
    bỏ qua signal `length`            ← sửa bậc-4 ở §3.3
    band = C2                         ← sàn, không bao giờ C1
    nâng lên C3 nếu có bất kỳ:
        (a) cả n và q đều ≥ 10⁵ VÀ có thao tác update      → cần cấu trúc dữ liệu
        (b) 998244353                                       → đếm/DP/đa thức
        (c) "interactive problem"                           → cần lập luận thích ứng
        (d) ràng buộc ≥ 10⁹                                 → toán/ma trận/digit DP
        (e) danh từ kỹ thuật khó: suffix automaton/array, max flow, matching,
            convex hull, heavy-light, centroid decomposition, segment tree beats,
            Mo's algorithm, li chao, FFT/NTT
```

**Vì sao sàn là C2 chứ không cố tách bài dễ:** ta không phân biệt được 800 với 1400 (§3.1), nên mọi cố gắng tách sẽ sai theo cả hai hướng. Sàn C2 mất phần tiết kiệm trên các bài thật sự dễ, đổi lại chặn được hoàn toàn ca thảm hoạ ở §3.4. Lưu lượng CP trong traffic thật rất nhỏ, nên phần tiết kiệm mất đi là nhỏ; còn ca thảm hoạ thì hiện diện rõ trong demo.

**Đánh đổi đã cân nhắc và bị loại:** dùng ràng buộc để đẩy bài nhỏ (`n ≤ 100`, không truy vấn) xuống C1. Loại, vì `n ≤ 100` cũng là ràng buộc điển hình của bài DP 1900 — cỡ ràng buộc nhỏ thường có nghĩa là *thuật toán mũ/đa thức bậc cao được phép*, chứ không có nghĩa là *bài dễ*. Đây là chỗ trực giác đi ngược thực tế.

### 4.3 Vòng verify bằng sample test

**Bản đầy đủ (cần sandbox — chưa có, chi phí thật):** trích `Example`, chạy code trong sandbox có giới hạn, so output. Cần: sandbox thực thi, giới hạn thời gian/bộ nhớ, parser cho block Example. Đây là hạng mục lớn, **không** thuộc phạm vi demo. Ghi lại ở đây vì nó là câu trả lời *đúng*, để sau này không phải phát hiện lại.

**Bản human-in-the-loop — chạy được ngay, không cần build gì thêm:** người dùng tự chạy lời giải, quay lại nói *"wrong answer on test 3"*. Đó là intent `correction` + error artifact → Session Router escalate theo đúng §6.1 của doc 08. Nghĩa là **cơ chế tự sửa ở lượt 2 đã hoạt động sẵn hôm nay**; classifier chỉ cần đúng *xấp xỉ* ở lượt 1, đừng sai thảm hoạ. Đây chính là lý do sàn C2 ở §4.2 là đủ tốt: nó đưa lượt 1 vào vùng mà vòng phản hồi sửa được, thay vì vùng T1 nơi kết quả vô giá trị mà người dùng không biết tại sao.

### 4.4 Giới hạn thành thật — v2/LLM **không** cứu được nhóm A

Cần nói rõ để đặt kỳ vọng đúng: dự đoán rating Codeforces từ đề bài là bài toán **khó cho cả mô hình mạnh**. Đây không phải khoảng cách heuristic-vs-LLM; đây là giới hạn thông tin (§3.1). Đừng lên kế hoạch coi FR-12 là lời giải cho nhóm A.

Cái v2 làm được cho nhóm A chỉ là nhận diện genre và dạng bài tốt hơn regex một chút — tức bậc 1 và bậc 3 ở §3.3. Bậc 2 và trục độ khó thật thì không.

---

# Phần B — Codebase qua agent harness

## 5. Chẩn đoán

### 5.1 Xung đột trực tiếp với doc 09 §4.2

Doc 09 §4.2 quy định: **artifact zone không bao giờ quyết định band**, để miễn nhiễm prompt injection. Trong ngữ cảnh chat, quy định đó đúng — người dùng viết ý định bằng prose, code dán vào chỉ là vật chứng.

Trong ngữ cảnh agent harness, quy định đó **làm classifier mù đúng chỗ quan trọng nhất**. Harness nén ý định người dùng thành một chỉ thị máy sinh (`"Fix this."`, `"Apply the change"`), còn **code chính là mô tả công việc**. §2.2 dòng 1 là bằng chứng: 60 dòng Go có đua dữ liệu thật → T2.

### 5.2 Phân bố lượt khác hẳn chat

| | Chat | Agent harness |
|---|---|---|
| 1 ý định người dùng | = 1 lượt user | = 15–30 lượt máy |
| Nội dung lượt giữa | ý định thật của người | `read file`, `apply edit`, `run test` — phần lớn là cơ học |
| Message user cuối | luôn là yêu cầu mới nhất | có thể là yêu cầu gốc từ 20 lượt trước (**H3**) |

Hệ quả cần đo, **chưa đo**: Session Router kế thừa `max(score, ema)` ở intent `continue` (doc 08 §5). Luật đó giả định ngữ nghĩa chat. Trong vòng lặp agent, nó ghim toàn bộ vòng lặp ở mức khó cao nhất từng thấy. Có thể **đúng** (cả vòng lặp là một task) hoặc là **rò rỉ chi phí** (đa số lượt là cơ học). Chưa có số liệu nên tài liệu này **không kết luận** — xem §8 G3.

## 6. Thiết kế B

### 6.1 Tách bằng chứng *lexical* và *structural* — sửa đổi doc 09 §4.2

Thay vì bỏ luật §4.2, tách nó làm hai loại bằng chứng:

| Loại | Ví dụ | Được phép |
|---|---|---|
| **Lexical** — chữ trong comment, string literal, tên biến | `// TODO: fix the race condition` | **Vẫn cấm.** Bơm được, và một comment nói về đua dữ liệu không có nghĩa công việc là về đua dữ liệu |
| **Structural** — cấu trúc cú pháp thực thi được | `go func() {`, `sync.Mutex`, `Arc<Mutex<`, `synchronized` | **Cho phép, nhưng chỉ được NÂNG band, không bao giờ hạ** |

Hai lý do để tách như vậy:

1. **Structural không giả được rẻ.** Muốn artifact có hai primitive đồng thời khác nhau thì phải thực sự viết code đồng thời. Còn nhét chữ vào comment thì miễn phí.
2. **Ràng buộc một chiều giữ nguyên tính an toàn ở hướng nguy hiểm.** Hướng nguy hiểm của injection là **hạ** tier — dụ hệ thống đưa việc khó cho model rẻ. Hướng "chỉ nâng" khiến kẻ tấn công chỉ có thể làm request của **chính họ** đắt hơn, và họ trả tiền cho việc đó. Rủi ro chấp nhận được.

### 6.2 Driver structural trong artifact zone

Chỉ mở đúng D1 (đồng thời) — đây là driver có ranh giới cú pháp rõ nhất và cũng là driver đắt nhất khi bỏ sót:

```
_D1_SYNTAX_RE (chạy trên artifact zone SAU khi strip comment/string):
    Go     : go\s+func | sync\.(Mutex|RWMutex|WaitGroup) | <-\s*chan | \.Lock\(\)
    Python : threading\. | asyncio\.(gather|create_task) | multiprocessing | Lock\(\)
    Rust   : Arc\s*< | Mutex\s*< | tokio::spawn | RwLock
    Java   : \bsynchronized\b | Atomic\w+ | ExecutorService | CompletableFuture
    JS/TS  : Promise\.all | new\s+Worker\( | Atomics\.

Luật: ≥ 2 construct KHÁC NHAU  →  nâng band lên C3
```

**Vì sao ≥2 và phải khác nhau:** một mình `await` có mặt khắp nơi trong JS/Python hiện đại và không mang thông tin. Hai primitive đồng thời khác nhau trong cùng một artifact thì gần như chắc chắn là code đồng thời thật.

**Chỉ nâng, không hạ:** artifact không có primitive nào **không** kéo band xuống. Task vẫn có thể khó vì lý do khác.

### 6.3 Strip comment và string literal

Cần cho §6.2 hoạt động đúng. Bản thô, theo họ ngôn ngữ: `//`, `#`, `/* */`, `"""`, `'''`, và string một dòng. Không hoàn hảo — string chứa `//` sẽ bị cắt nhầm — nhưng sai theo hướng **an toàn**: cắt nhầm làm mất tín hiệu (không nâng band), không tạo tín hiệu giả.

Không parse AST. Chi phí không tương xứng, và contract B.2 giới hạn 800ms thuần CPU.

### 6.4 Đường thoát rẻ nhất: để harness truyền hint

Trước khi build §6.2, cần ghi nhận: **gateway đã có sẵn `force_tier` và `force_model`** (`chat_completions.py`, và `orchestrator.handle()` nhận cả hai). Một harness tích hợp **biết rõ** nó đang làm gì — nó biết lượt này là "đọc file" hay "thiết kế lại module".

Nên với người dùng tích hợp API, đường rẻ nhất và chính xác nhất là **tài liệu hoá `force_tier` như một tính năng tích hợp chính thức**, thay vì cố suy ngược ý định từ text mà harness đã nén mất. Heuristic ở §6.2 chỉ dành cho harness **không** truyền hint.

Đây là bậc 1 của thang lười: phần lớn ca tốt nhất là không đoán.

---

## 7. Ma trận case

### 7.1 Nhóm A — competitive programming

| # | Input | v1.5 hiện tại | Sau thiết kế A |
|---|---|---|---|
| A1 | Đề 800 đủ format, có `Example` | C1 → T1 | C2 → T2 (mất tiết kiệm, chấp nhận §4.2) |
| A2 | Đề 1400 đủ format | C1 → T1 ✘ | C2 → T2 ✔ |
| A3 | Đề 2100, cây + update/query, n,q ≤ 2·10⁵ | C2 → T2 ✘ | C3 → T3 ✔ (luật a) |
| A4 | Đề 2600, n,q ≤ 10⁶, mod 998244353 | C2 → T2 ✘ | C3 → T3 ✔ (luật a+b) |
| A5 | Đề interactive | tuỳ boilerplate | C3 → T3 ✔ (luật c) |
| A6 | Đề rút gọn một dòng, không boilerplate | C2 → T2 | genre ≠ CP → rơi về thang doc 09, C2 → T2 |
| A7 | Đề CF dán kèm code người dùng đã thử + traceback | C2 + error_artifact | C2/C3 + error_artifact — vòng §4.3 human-in-the-loop hoạt động |
| A8 | "giải thích thuật toán Dijkstra" (không phải đề) | M2/M3 → C1 | genre ≠ CP → C1 → T1 ✔ (đúng, đây là recall) |

### 7.2 Nhóm B — agent harness

| # | Input | v1.5 hiện tại | Sau thiết kế B |
|---|---|---|---|
| B1 | `"Fix this."` + Go có `go func` + `sync.Mutex` | C2 → T2 ✘ | C3 → T3 ✔ (§6.2) |
| B2 | `"Rename x to count"` + 200 dòng tuần tự | C1 → T1 ✔ | C1 → T1 ✔ (không có primitive → không nâng) |
| B3 | `"Rename x to count"` + 200 dòng **có** `go func`+`Mutex` | C1 → T1 | C3 → T3 — **cố ý sai theo hướng đắt**, xem L2 §8 |
| B4 | Artifact có comment `// fix the race condition`, code tuần tự | C2 → T2 | C2 → T2 ✔ (lexical bị cấm, §6.1) |
| B5 | Harness truyền `force_tier=T1` | bypass | bypass ✔ (§6.4) |
| B6 | Lượt agent thuần cơ học (`apply edit`), user msg gốc cách 20 lượt | chấm lại prompt cũ (H3) | không đổi — cần đo, §8 G3 |

---

## 8. Giới hạn còn lại

* **L1 — Nhóm A vẫn không phân giải được trong dải 1400–2000.** §4.2 chỉ tách được "có marker cấu trúc dữ liệu / mod / interactive" khỏi "không có". Bài 1600 greedy tinh tế và bài 900 greedy hiển nhiên vẫn cùng C2. Theo §3.1 đây là giới hạn thông tin, **không phải lỗi thiết kế**, và §4.4 nói rõ v2 cũng không sửa được. Lối ra thật là §4.3.
* **L2 — §6.2 nâng band theo *code*, không theo *việc*.** Ca B3: đổi tên biến trong một file có code đồng thời sẽ bị đẩy lên C3. Sai theo hướng đắt. Sửa được bằng cách đối chiếu vùng code mà chỉ thị nhắm tới, nhưng cần định vị trong artifact — chưa tương xứng chi phí. Chấp nhận và ghi lại.
* **L3 — Strip comment thô sẽ sai trên code có string chứa ký tự comment.** Sai theo hướng an toàn (§6.3).
* **L4 — H1/H2/H3 chưa kiểm chứng.** Không được xây dựng trên chúng trước khi có §9 G1.

---

## 9. Gate kiểm chứng

| Gate | Nội dung | Ngưỡng |
|---|---|---|
| **G1** | Xác nhận H1/H2/H3 bằng probe chạy thật trước khi implement bất cứ thứ gì ở §4/§6 | 3/3 kết luận rõ |
| **G2** | Dataset `cp_problems_40.jsonl` — 40 đề thật, có rating gốc, trải đều 800–2600 | band accuracy: không đề ≥1900 nào rơi T1 |
| **G3** | **Đo** phân bố tier trên một transcript agent thật (20+ lượt), bật/tắt EMA inheritance | trả lời được §5.2 bằng số, không bằng suy đoán |
| **G4** | Regression doc 09: toàn bộ case §8 của `09_classifier_v1_5.md` giữ nguyên kết quả | 0 hồi quy |
| **G5** | Genre detector không bắt nhầm request thường | false positive < 2% trên dataset hiện có |

**G1 là gate chặn.** §2.3 nói rõ ba mệnh đề H1–H3 mới chỉ là đọc-code, và H1 là mệnh đề mà toàn bộ §4.2 dựa vào.

---

## 10. Phạm vi — cái gì tài liệu này **không** làm

* Không đổi thang C1/C2/C3, không đổi band base/floor, không đổi modifier cap của doc 09.
* Không đụng contract B.2: vẫn không raise, không I/O, tự cắt ở `ROUTER_TIMEOUT_MS`.
* Không đề xuất LLM call — trừ phần ghi nhận ở §4.4 rằng v2 *không* giải được nhóm A.
* Không build sandbox. §4.3 mô tả nó là hướng đúng và nêu chi phí; bản human-in-the-loop dùng cơ chế Session Router đã có.
* Không đổi Session Router. §5.2 nêu một câu hỏi mở và giao cho gate G3 trả lời bằng số đo.

---

## Changelog

* **v1.0 — 2026-08-21** — Bản đầu. Số đo §2.1/§2.2 chạy trên `classifier_v1_5.py` ngày 21/08/2026. Nhóm A: nhận diện genre + sàn C2 + 5 luật nâng C3, lý do gốc là rating không phải thuộc tính văn bản (§3.1). Nhóm B: tách bằng chứng lexical/structural, sửa đổi doc 09 §4.2 theo hướng một chiều chỉ-nâng. Ba mệnh đề H1–H3 đánh dấu chưa kiểm chứng, chặn bởi gate G1.
