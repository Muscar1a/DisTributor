# Intent qua LLM — chấm intent lượt hội thoại bằng model, giữ regex làm nền

**v0.1 · 2026-08-26 · File: `docs/design/13_llm_intent_classification.md` · Phạm vi: sau M3, mở rộng doc 08 + doc 12**

> **Vị trí trong bộ tài liệu:** tài liệu này sở hữu **thiết kế chấm `turn_intent` bằng LLM**. Nó **nới** ràng buộc "*không đổi Session Router*" của `12_classifier_v2.md` §0.3 — và nêu rõ vì sao. Nó **không** thay `08_adaptive_routing.md` §5: state machine, hysteresis, EMA, failure-lock giữ nguyên. Chỉ đổi **một đầu vào** của SessionRouter: `turn.intent` — trước tính 100% bằng regex, nay ưu tiên nhãn LLM khi có, rơi về regex khi không. Khi lệch requirement → `02_prd.md` thắng; technical → `06_architecture.md` thắng.

---

## 0. Bài toán — bằng chứng từ một ca thật

Prompt LeetCode **easy** (Longest Common Prefix) bị định tuyến **T3**. Signals breakdown thực tế:

```
length +10   v2_fallback +0   ema_inherit +52   failure_boost +15   intent_continue +0
```

Đọc chuỗi nhân quả:

| Signal | Ý nghĩa |
|---|---|
| `length +10` | v1.5 chấm raw = **10** (T1). Bài đúng là dễ. |
| `v2_fallback +0` | **LLM không chạy** — v2 đã rơi về heuristic v1.5. |
| `intent_continue +0` | intent bị gán **`continue`** → kế thừa độ khó lượt trước. |
| `ema_inherit +52` | `score = max(10, ema≈62)` → **62**. |
| `failure_boost +15` | cộng thêm do có failure signal. |

**Root cause:** đề bài chứa `"...if it is non-empty"`. Từ **`it`** (nội dung đề) bị [`_refers_to_context`](src/gateway/app/core/session_router/turn_analyzer.py) bắt là **đại từ tham chiếu hội thoại** → chặn nhãn `new_task` → intent thành `continue` → dính EMA của task khó trước đó → T3.

Kiểm chứng: cùng đề bài, nếu là **lượt đầu** (`prev=None`) → `new_task` → T1. Chỉ vì có lượt trước + chữ "it" trong content → `continue` → T3.

### 0.1 Vì sao regex intent hỏng **cả hai chiều**

`_refers_to_context` chỉ là một cú `re.search(r"\b(it|this|that|...)\b")` không giới hạn ngữ cảnh:

| Ca | Kỳ vọng | Regex cho | Kiểu lỗi |
|---|---|---|---|
| "Write a function... if **it** is non-empty [đề tự chứa 400 ký tự]" | new_task | continue | **false positive** — "it" là content, không phải anaphora |
| "Viết bộ unit test cho **hàm trên**" | continue | new_task | **false negative** — tham chiếu tiếng Việt không có trong lexicon |

Một hàm, hỏng hai hướng ngược nhau. Đây là giới hạn bản chất của việc phân intent bằng khớp từ khoá: intent là **quan hệ ngữ nghĩa giữa lượt này và lượt trước**, không phải sự hiện diện của một token.

---

## 1. Mục tiêu & không-mục-tiêu

**Mục tiêu**
1. `turn_intent` chính xác hơn regex, đặc biệt phân biệt **đề bài tự chứa** (`new_task`) vs **nói tiếp** (`continue/refine`).
2. **Không thêm lời gọi LLM** trên happy path — piggyback lên call v2 đã tồn tại.
3. Đường fallback (LLM không chạy) vẫn **không được** cho ra T3 sai như ca §0.

**Không-mục-tiêu**
- Không đổi state machine / hysteresis / EMA / failure-lock (doc 08 §5 giữ nguyên).
- Không để LLM quyết tier. LLM **đề xuất** intent; SessionRouter vẫn là nơi quyết định.
- Không bỏ regex. Regex ở lại làm **nền bắt buộc** cho đường fallback (§5, §7).

---

## 2. Quyết định — piggyback `intent` lên response v2

LLM đã được gọi một lần để lấy `level`. Thêm một field vào JSON schema là **gần như miễn phí** (vài token, không thêm round-trip):

```json
{"kind": "coding"|"other", "level": "L0..L6",
 "intent": "new_task"|"continue"|"refine"|"correction"|"meta",
 "why": "<=10 words"}
```

So với phương án gọi LLM riêng cho intent (doc 08 §5 đã từ chối vì SLO 300ms): phương án này **không** vi phạm SLO vì không phát sinh call mới.

---

## 3. Prompt r1 → r2

Bổ sung vào `_SYSTEM_PROMPT` một mục định nghĩa 5 intent + tiêu chí phân biệt cốt lõi:

> `new_task` = một yêu cầu **tự chứa**, hiểu được mà không cần đọc lượt trước (đề bài có spec/ví dụ/constraints riêng, hoặc đổi chủ đề rõ ràng). `continue/refine/correction/meta` = thao tác **trên kết quả của lượt trước**; không tự đứng một mình được.

Kèm 2–3 few-shot neo đúng các bẫy đã biết:
- *"Write a function to find the longest common prefix... Constraints..."* → `new_task` (đề tự chứa, dù mở đầu giữa session).
- *"Viết bộ unit test cho hàm trên"* → `continue` (tham chiếu kết quả trước).
- *"simplify it"* → `refine`.

**Đầu vào cần thêm:** intent cần **lượt user liền trước** để phán quan hệ. Prompt user hiện chỉ gửi instruction lượt cuối (`_format_user_prompt`). Thêm một dòng `previous_user_turn: <tóm tắt/cắt ngắn lượt trước>`. Ràng buộc token: cắt lượt trước về ≤ 200 ký tự.

Bump `PROMPT_REVISION` (`r1` → `r2` cho intent; → `r3` sau khi làm sắc biên L2/L3, §3.1).

### 3.1 Làm sắc biên L2/L3 — chỗ "easy → T2" thực sự nằm

Nghiệm thu r2 (session `5fac8a86`): intent-fix + config đã trị ema-inherit và fallback, nhưng **Two Sum vẫn T2** vì LLM gán **L3** (32 ≥ 30). Đây không còn là bug ema — là **biên bậc**.

Chỉ **2/6 biên** trùng vạch tier và mới gây hậu quả routing: **L2\|L3** (vạch T1/T2, score 30) và **L4\|L5** (vạch T2/T3, score 60). Nhầm ở biên khác (L1\|L2, L3\|L4) → cùng tier, vô hại. Mọi bug "easy → T2" đều nằm ở **một biên: L2\|L3**.

Gốc: định nghĩa L3 gộp hai vế ("viết hàm theo spec" *và* "hiểu logic hiện có") mà không nói quan hệ; bài tự chứa như Two Sum khớp vế đầu, trượt vế sau → **rule 2** (phân vân chọn cao) đẩy lên L3. Sửa bằng **một câu hỏi phân biệt nhị phân** đặt đúng tại biên, và tắt rule 2 ở riêng biên này:

> Task có cần **hiểu code hiện có**, HOẶC **nghĩ ra thuật toán không hiển nhiên** không?
> - **Không** → **L2** (bài tự chứa, pattern quen: Two Sum, LCP, reverse string, valid parentheses).
> - **Có** → **L3** (Median O(log), Dijkstra, thao tác trên code sẵn, viết test cho code sẵn).

**Rủi ro bất đối xứng** (doc 08 §5): nhầm L2→L3 = over-route (rẻ); nhầm L3→L2 = under-route (nguy hiểm). Nên câu phân biệt phải kéo Two Sum/LCP xuống L2 **mà giữ** bài L3 thật ở trên — ví dụ neo hai phía biên trong prompt phục vụ đúng việc này.

**Nghiệm thu:** chạy Two Sum / LCP / Median trong một session — kỳ vọng Two Sum & LCP **L2 → T1**, Median **L3 → T2**. Cần model thật (đo trên DB), không verify được bằng unit test.

---

## 4. Đổi contract B.2 (tối thiểu)

```python
@dataclass
class ClassificationResult:
    ...
    intent: str | None = None   # nhãn intent do LLM chấm; None nếu fallback/không có
```

Thêm field optional, mặc định `None` → **tương thích ngược**: mọi classifier cũ (v1, v1.5) và mọi đường fallback trả `None`, không vỡ caller nào. Đây là điểm khác với ràng buộc doc 12 §0.3 — được nới có chủ đích, phạm vi đúng một field.

---

## 5. Hợp nhất intent tại SessionRouter

`analyze_turn` nhận thêm nhãn LLM (nếu có) và **ưu tiên** nó; regex chỉ chạy khi nhãn vắng:

```
intent_llm = classification.intent           # có thể None
intent = intent_llm or classify_intent(...)  # regex là nền
```

`correction`/`failure_signal` **vẫn tính bằng cấu trúc** (stack trace mới, resubmission, correction phrase) — đây là tín hiệu tin cậy cao, rẻ, và phải hoạt động cả khi LLM nói khác. LLM chỉ chi phối trục `new_task ↔ continue/refine/meta`.

---

## 6. Bẫy cache

Cache key v2 hiện chỉ gồm instruction lượt cuối (`_cache_key`). Nhưng **intent phụ thuộc lượt trước** — cùng một instruction, ngữ cảnh trước khác nhau cho intent khác nhau. Hai lối:

| Lối | Đánh đổi |
|---|---|
| **A. Đưa `previous_user_turn` vào cache key** | Đúng, nhưng hit-rate giảm (khoá mịn hơn). |
| **B. Chỉ cache `{kind, level}`, luôn tính lại `intent`** | Giữ hit-rate cho phần đắt (level), nhưng intent cần chạy mỗi lượt → nếu intent cùng call LLM thì không tách được. |

**Khuyến nghị: Lối A.** `level` và `intent` sinh từ **cùng một** call; tách ra là phá lợi ích piggyback. Chấp nhận hit-rate thấp hơn — đằng nào các lượt trong một session hiếm khi trùng instruction.

---

## 7. Đường fallback **vẫn phải đúng** — không bỏ qua regex

Đây là phần quan trọng nhất, và là chỗ ca §0 thực sự nằm: khi LLM không chạy (không key, timeout, provider lỗi), `intent = None` → **regex là đường duy nhất**. LLM-intent **không** tự cứu ca fallback.

Nên thiết kế này **bắt buộc** kèm vá hai lỗ regex đã biết ở §0.1, coi như phần của cùng một thay đổi:

1. **Length-gate `_refers_to_context`** — chỉ coi "it/this/that" là anaphora khi câu đủ ngắn (đề tự chứa dài → bỏ qua). Sửa false positive (ca LCP).
2. **Lexicon tham chiếu tiếng Việt** — "hàm trên", "hàm đó", "đoạn code trên"... Sửa false negative (ca unit-test).

Không có phần này, một sự cố provider sẽ tái hiện đúng bug T3.

### 7.1 Vì sao fallback xảy ra tới 40% — và chỉnh bằng config, không phải bỏ fallback

Đo trên DB thật (20 request `llm-v2`):

| Chỉ số | Giá trị |
|---|---|
| Tỉ lệ fallback | **8/20 = 40%** |
| Latency classify (lượt LLM chạy) | p50 **1715ms**, p90 2253ms, max 2442ms |
| Đuôi phân bố | **bị cắt ở 2500ms** — mọi call chậm hơn đã timeout → không quan sát được |

Ca điển hình (`session 084e6836`, bài Two Sum): `latency_router_ms = 2501` — chạm **đúng** trần `router_timeout_ms=2500` → `asyncio.wait_for` cắt → fallback. Cùng session, hai lượt khác chỉ 12ms và 45ms. Kết luận: fallback **không** do hết key hay cấu hình sai — mà do **provider thật latency dao động**, thỉnh thoảng vượt trần.

**Gốc của latency 1.7s:** `classifier_v2_model = "gpt-5-nano"` bị code coi là **reasoning** (`model_id.startswith(("gpt-5","o1","o3","o4"))` → `max_tokens=500` + `reasoning_effort`). Reasoning model suy nghĩ trước khi trả → 1–2.5s cho một classify lẽ ra chỉ cần ~200ms.

**Hai núm chỉnh, cả hai đều qua config (không sửa code):**

| Núm | Config | Tác dụng | Đánh đổi |
|---|---|---|---|
| Nới trần | `ROUTER_TIMEOUT_MS` (env) / `config.yaml:routing.router_timeout_ms`, 2500 → ~4000 | Cứu phần lớn fallback | **Băng dán** — p50 vẫn 1.7s, mọi request chờ lâu hơn; 4000 là *ước lượng* vì đuôi bị cắt, chưa chắc bao hết p99 |
| Đổi model | `CLASSIFIER_V2_MODEL` (env) / `config.yaml:routing.classifier_v2_model` → model **non-reasoning** nhanh | **Trị gốc** — p50 rớt về ~100–300ms → fallback gần như biến mất | Cần một model classify không khớp prefix reasoning |

**Khuyến nghị:** làm **cả hai** — nới timeout làm lưới an toàn cho ca tắc hiếm, đổi model để p50 không còn 1.7s. Model classifier thuộc **config** (`classifier_v2_model`), không hard-code, nên đổi là một dòng `config.yaml`/env, không đụng `classifier_v2.py`.

`ROUTER_TIMEOUT_MS` dùng chung với v1/v1.5 (mặc định 800ms) — nới lên không ảnh hưởng chúng vì heuristic thuần chạy <100ms.

---

## 8. Rủi ro & đánh đổi

| Rủi ro | Giảm thiểu |
|---|---|
| Prompt r2 dài hơn (thêm định nghĩa intent + lượt trước) → tốn token/latency | Cắt lượt trước ≤200 ký tự; đo delta latency trước khi ship. |
| LLM chấm intent lệch → định tuyến sai | `correction`/failure vẫn bằng cấu trúc; LLM chỉ chi phối trục new_task↔continue. |
| Cache hit-rate giảm (§6) | Chấp nhận; instruction trùng trong 1 session vốn hiếm. |
| Prompt versioning: đổi mô tả intent lệch cả loạt | Gắn `PROMPT_REVISION`; đo bằng eval §9 trước/sau. |

---

## 9. Kiểm chứng

Dataset đã có: `evals/datasets/turn_intents_*.jsonl` + templates trong `build_multiturn.py` (18 hội thoại song ngữ, nhãn intent tay). Đo **intent accuracy** hai cấu hình:

1. **Regex-only** (đường fallback) — phải đạt ngưỡng đủ để không tái hiện ca §0; tối thiểu: ca LCP → `new_task`, ca unit-test → `continue`.
2. **LLM-intent** (happy path) — so với regex-only, kỳ vọng cải thiện trên các ca tham chiếu ngầm.

Ca hồi quy bắt buộc thêm vào dataset (trích từ DB thật, `session 084e6836`):
- LCP-as-followup → `new_task` (chống false positive "it", đường regex).
- "Viết unit test cho hàm trên" → `continue` (chống false negative VN, đường regex).
- **Two Sum sau một bài khó** → phải **T1**, không dính `ema_inherit` (bug đường fallback: intent=continue kế thừa ema +22 → T2).
- **LCP khi LLM chạy** → phải **L2**, không phải L3 (bug over-rate: LLM nano gán L3 → 32 → T2; đề easy neo ở L3 chỉ cần lệch 1 bậc là rớt tier).

---

## 10. Tóm tắt thay đổi

| File | Thay đổi |
|---|---|
| `classifier_v2.py` | Prompt r2 (thêm intent + previous_user_turn), parse `intent`, đưa vào `ClassificationResult`, cache key gồm lượt trước |
| `interfaces.py` | `ClassificationResult.intent: str \| None = None` |
| `session_router/router.py` | `intent = classification.intent or classify_intent(...)` |
| `session_router/turn_analyzer.py` | Length-gate `_refers_to_context` + lexicon tham chiếu VN (đường fallback) |
| `config.yaml` (routing) / env | `router_timeout_ms` (nới ~4000) + `classifier_v2_model` (non-reasoning) — §7.1, chỉ config |

**Trạng thái triển khai (2026-08-26):** các file trên đã xong; ca hồi quy §9 đặt ở **unit test** (`test_turn_analyzer.py`, `test_classifier_v2.py`, `test_router_llm_intent.py`) — trực tiếp, rẻ, không kéo theo regenerate committed dataset. Nhồi các ca này vào `evals/build_multiturn.py` để đo accuracy tổng thể là bước eval mở rộng, làm sau. Config §7.1 do vận hành set (`.env`).
