# 15 — Cache-Aware Handoff: giảm chi phí cache miss khi đổi model giữa session

**v1.0 · 2026-09-14 · File: `docs/design/15_cache_aware_handoff.md` · Phạm vi: tối ưu chi phí multi-turn**

> **Vị trí trong bộ tài liệu:** tài liệu này sở hữu **thiết kế lớp giảm chi phí cache miss khi chuyển model giữa session multi-turn**. Nó **mở rộng** `08_adaptive_routing.md` §8.1 (Working Set) — chưa implement — và **không** thay thế bất kỳ tài liệu classifier nào (doc 09, 10, 12, 13, 14). Phạm vi: chỉ ảnh hưởng cách `messages[]` được chuẩn bị trước khi gửi tới LLM provider khi có model switch; không đổi cách chấm điểm, không đổi cách chọn tier, không đổi contract B.2 của classifier. Khi lệch nhau về requirement → `02_prd.md` thắng; về technical decision → `06_architecture.md` thắng.

---

## 1. Bài toán — chi phí ẩn mà không tài liệu nào tính

### 1.1 Provider-side prompt caching

Mọi LLM provider lớn (OpenAI, Anthropic, Google) cache **prefix** của prompt trên server. Khi request tiếp theo có cùng prefix trên **cùng model**, phần prefix cached được giảm giá:

| Provider | Discount input cached | Điều kiện |
|---|---|---|
| OpenAI | 50% | Tự động, cùng model, prefix ≥ 1024 token |
| Anthropic | 90% | Cùng model, cache_control marker |
| Google (Gemini) | ~50% (context caching) | Cùng model, explicit API |

**Cache là per-model.** Không có cross-model cache pool — kể cả trong cùng family (GPT-4o-mini và GPT-4o **không** chia sẻ cache). Đây là ràng buộc cứng của provider, ngoài tầm kiểm soát của gateway.

### 1.2 Xung đột với smart routing

Trong hội thoại multi-turn, mỗi lần Session Router đổi tier → đổi model → **toàn bộ prompt cache trên model cũ mất giá trị**, và model mới phải xử lý toàn bộ context tích luỹ từ đầu ở full price.

```
Turn 1: "Viết FastAPI CRUD"          → nano   (cache bắt đầu trên nano)
Turn 2: "Thêm pagination"            → nano   (cache hit ✔, input rẻ)
Turn 3: "Thêm JWT auth"              → nano   (cache hit ✔, input rẻ)
Turn 4: "Race condition khi..."       → STRONG (cache nano vô giá trị,
         + stack trace 2000 token                strong xử lý ~8000 token
                                                 context FULL PRICE)
Turn 5: "Sửa lỗi nhỏ tiếp"          → nano   (cache nano đã hết hạn,
                                                 lại full price)
```

Chi phí cache miss **tỉ lệ thuận với context đã tích luỹ × giá token model đích**. Ca đắt nhất — escalate lên model mạnh ở turn muộn — xảy ra đúng lúc context lớn nhất, trên model đắt nhất.

### 1.3 Chi phí mà hệ thống chưa tính

Công thức savings hiện tại (`08_adaptive_routing.md` §9, `admin.py:195-207`):

```
net_cost = actual_cost + router_cost
savings% = (baseline_cost − net_cost) / baseline_cost × 100
```

Công thức này **không tính cache discount bị mất**. Nó giả định mọi input token đều full price bất kể có cache hay không. Trong thực tế, chiến lược "dùng một model xuyên suốt" hưởng cache discount từ turn 2 trở đi — nên **baseline thật** rẻ hơn baseline trong công thức.

> **Hệ quả:** savings% đang bị khai khống. Smart routing có thể báo tiết kiệm 40% nhưng thực tế chỉ tiết kiệm 25% (hoặc thậm chí âm) nếu tính cache discount mà "dùng một model" sẽ hưởng.

---

## 2. Đo lường — chi phí cache miss trên một session thật

### 2.1 Kịch bản: session coding 8 lượt, escalate ở turn 5

Giả định: mỗi lượt thêm ~1000 token input + ~800 token output. Turn 5 cần escalate (race condition). Pricing:

| | nano ($0.10/M in, $0.40/M out) | strong ($15/M in, $60/M out) |
|---|---|---|
| Cache discount | 50% | 50% |

**Kịch bản A: Dùng strong xuyên suốt (baseline thật)**

| Turn | Input mới | Input cached | Output | Input cost | Output cost |
|---|---|---|---|---|---|
| 1 | 1000 | 0 | 800 | $0.0150 | $0.0480 |
| 2 | 1000 | 1800 | 800 | $0.0150 + $0.0135 | $0.0480 |
| ... | | | | | |
| 8 | 1000 | 13600 | 800 | $0.0150 + $0.1020 | $0.0480 |
| **Tổng** | | | | | **≈ $0.91** |

**Kịch bản B: Smart routing hiện tại (nano turn 1-4,6-8 + strong turn 5, KHÔNG nén)**

| Turn | Model | Input mới | Input cached | Input cost |
|---|---|---|---|---|
| 1-4 | nano | cache build | cache hit | rất rẻ (~$0.002 tổng) |
| **5** | **strong** | **7000 FULL PRICE** | **0** | **$0.105** |
| 6 | nano | 9000 full price (cache cũ hết hạn) | 0 | $0.0009 |
| 7-8 | nano | cache rebuild | cache hit | rất rẻ |
| **Tổng** | | | | **≈ $0.17** |

**Kịch bản C: Smart routing + handoff nén (đề xuất)**

| Turn | Model | Input mới | Input cached | Input cost |
|---|---|---|---|---|
| 1-4 | nano | cache build | cache hit | ~$0.002 |
| 5a | nano (summary) | 100 mới | 6000 cached | ~$0.0004 |
| **5b** | **strong** | **2000** (summary + vấn đề) | **0** | **$0.030** |
| 6 | nano | 9000 full price | 0 | $0.0009 |
| 7-8 | nano | cache rebuild | cache hit | rất rẻ |
| **Tổng** | | | | **≈ $0.09** |

**Chênh lệch B→C mỗi lần switch: ~$0.075.** Với 1000 switch events/ngày: **$75/ngày ≈ $2250/tháng.**

### 2.2 Chi phí tỉ lệ theo context size

| Context tại thời điểm switch | Cache miss cost (strong, full) | Cache miss cost (strong, nén) | Tiết kiệm |
|---|---|---|---|
| 2000 token | $0.030 | $0.015 | 50% |
| 5000 token | $0.075 | $0.023 | 69% |
| 8000 token (sát trần) | $0.120 | $0.030 | 75% |

Càng muộn trong session, càng tiết kiệm nhiều. Đúng ca phổ biến nhất (task khó xuất hiện sau nhiều lượt dễ).

---

## 3. Quan hệ với doc 08 §8.1 — Working Set

Doc 08 §8.1 đã thiết kế một cơ chế quản lý context khi đổi tier — **Working Set**: prune message theo intent, giữ lại subset. Thiết kế đó **chưa được implement** và có ba quyết định quan trọng:

| Quyết định doc 08 §8.1 | Tài liệu này | Quan hệ |
|---|---|---|
| *"Prune khi switch, giữ nguyên khi stay"* | **Giữ nguyên.** Đây là nguyên tắc đúng — stay = ăn cache, switch = cache mất nên prune miễn phí | Đồng thuận |
| *"Không gọi LLM tóm tắt — tốn tiền, thêm latency, thêm điểm lỗi"* | **Đồng ý, nhưng bổ sung một ngoại lệ** — escalate lên model đắt (§4.2) | Mở rộng có điều kiện |
| *"Câu trả lời cuối là bản tóm tắt tự nhiên"* | **Đúng và đây là baseline.** Summary call chỉ đáng tiền khi assistant response cuối không chứa đủ context (§4.3) | Kế thừa insight, thêm guard |

### 3.1 Working Set là baseline, summary là escalation

Cơ chế hai tầng:

```
Khi phát hiện model switch:
  1. Áp Working Set (doc 08 §8.1) — prune message theo intent, $0, <1ms
  2. Kiểm tra: working set đã đủ nhỏ chưa?
     ĐỦ NHỎ (< SUMMARY_THRESHOLD token) → dùng working set, xong
     VẪN LỚN → §4 quyết định có nén thêm không (phụ thuộc hướng switch)
```

**Phần lớn trường hợp Working Set đã đủ.** Summary call chỉ kích hoạt khi Working Set vẫn lớn **và** đang escalate lên model đắt — ca mà mỗi token tiết kiệm trên model đích có giá trị cao nhất.

---

## 4. Thiết kế — Summary-Mediated Handoff

### 4.1 Khi nào kích hoạt

```
handoff_needed =
    model_switch                          # tier đổi → model đổi
    AND working_set_tokens > SUMMARY_THRESHOLD   # prune chưa đủ nhỏ
    AND direction == ESCALATE             # chỉ khi lên model đắt hơn
    AND context_tokens > CONTEXT_MIN      # context quá nhỏ thì không đáng
```

**Chỉ escalate**, không de-escalate. Lý do:
- Escalate: model đích **đắt hơn**, mỗi token tiết kiệm giá trị cao. Summary call trên model cũ (rẻ, cached) là chi phí thấp.
- De-escalate: model đích **rẻ hơn**, token tiết kiệm giá trị thấp. Summary call trên model cũ (đắt) tốn nhiều hơn tiết kiệm.

Doc 08 §8.1 Working Set **đủ tốt** cho de-escalate — model nhỏ nhận ít context hơn cũng là lợi (giảm nhiễu, doc 08 §8.1 lý do 3).

### 4.2 Summary call — input và output

**Input (gửi cho model cũ, đang giữ cache):**

```
messages = [
    *working_set_messages,        # đã prune theo doc 08 §8.1
    Message(
        role="user",
        content=_SUMMARY_PROMPT    # hằng số, xem §4.2.1
    ),
]
```

Phần lớn `working_set_messages` đã được cache trên model cũ → chi phí input rất thấp.

#### 4.2.1 Summary prompt

```
Tóm tắt trạng thái hiện tại của cuộc hội thoại thành JSON, tập trung vào
thông tin cần thiết để tiếp tục giải quyết yêu cầu mới nhất của user:
{
  "task": "mô tả ngắn gọn việc đang làm",
  "code_state": "code hiện tại (nếu có, giữ nguyên, không rút gọn)",
  "decisions": ["các quyết định thiết kế đã đưa ra"],
  "unresolved": "vấn đề chưa giải quyết (nếu có)"
}
Chỉ giữ thông tin liên quan trực tiếp. Bỏ lịch sử hội thoại, lời chào, xác nhận.
```

**Vì sao JSON có schema cố định:**
- Output có cấu trúc → parse được, verify được, log được
- Schema cố định → `max_tokens` thấp (giới hạn chi phí output)
- Trường `code_state` giữ nguyên code → không mất thông tin quan trọng nhất

#### 4.2.2 Tham số

| | Giá trị | Lý do |
|---|---|---|
| Model | model cũ (đang giữ cache) | Cache hit, giá rẻ |
| `temperature` | 0 | Tái lập được |
| `max_tokens` | 800 | Giới hạn chi phí output; code dài vẫn vừa |
| Timeout | `SUMMARY_TIMEOUT_MS` (mặc định 3000ms) | Timeout → bỏ summary, gửi working set thô |

**Output:** JSON string → parse → dùng ở §4.3.

### 4.3 Xây messages[] cho model đích

```python
def build_handoff_messages(
    summary_json: dict,
    current_user_message: Message,
    system_message: Message | None,
) -> list[Message]:
    context_block = (
        f"## Trạng thái hiện tại\n"
        f"Task: {summary_json['task']}\n"
        f"Decisions: {', '.join(summary_json.get('decisions', []))}\n"
        f"Unresolved: {summary_json.get('unresolved', 'none')}\n\n"
        f"## Code\n{summary_json.get('code_state', '(none)')}"
    )
    messages = []
    if system_message:
        messages.append(system_message)
    messages.append(Message(role="user", content=context_block))
    messages.append(Message(role="assistant", content="Understood. I have the full context. What do you need?"))
    messages.append(current_user_message)
    return messages
```

**Kích thước:** system (~200) + context (~1000-2000) + filler (~30) + user message (~500-2000) ≈ **1700-4200 token**. So với full history 6000-8000: tiết kiệm 50-75% input token trên model đắt.

**Cặp user/assistant giả (context_block + filler):** đảm bảo model đích hiểu context_block là ngữ cảnh đã có, không phải yêu cầu cần thực hiện. Đây là kỹ thuật chuẩn khi inject context vào conversation mới.

### 4.4 Lượt tiếp theo — quay về model cũ

```
Turn N+1: Client gửi messages[] (tự nhiên có response của strong ở turn N)
          → Session Router route về model cũ (hoặc model khác)
          → Model cũ thấy: turn 1..N-1 (CÓ THỂ CACHED) + turn N-N+1 (mới)
```

Nếu khoảng cách turn N và turn N+1 đủ ngắn, cache turn 1..N-1 trên model cũ **vẫn sống** (TTL cache provider thường 5-10 phút). Đây là chỗ lợi ích cộng dồn lớn nhất.

### 4.5 Khi summary call thất bại

```
summary call timeout / lỗi / JSON hỏng
    → bỏ summary
    → gửi working set (đã prune theo doc 08 §8.1) cho model đích
    → signals += [Signal("handoff_fallback", 0)]
```

Không bao giờ block request vì summary call hỏng. Worst case = hành vi hiện tại (gửi context chưa nén).

---

## 5. Điểm cắm trong kiến trúc

### 5.1 Phát hiện model switch

Sau `session_router.route()` và `policy_engine.select()` trong `chat_completions.py` (khoảng dòng 440-487). Lúc này có:

- Model lượt trước: từ `state` (cần thêm `last_model_id` vào `SessionState`)
- Model lượt này: `plan.chain[0]`
- So sánh: nếu khác → model switch

### 5.2 Can thiệp messages

Ngay trước `fallback_executor.execute(plan.chain, messages, params)` (dòng ~679) và `execute_stream(...)` (dòng ~568):

```python
# Pseudocode — vị trí cắm
effective_messages = messages  # mặc định: gửi nguyên

if _is_model_switch(state, plan) and _should_handoff(working_set_tokens, direction):
    working_set = _apply_working_set(messages, turn_intent)  # doc 08 §8.1
    if len(working_set_tokens) > SUMMARY_THRESHOLD:
        summary = await _summary_call(model_old, working_set, current_user_msg)
        if summary:
            effective_messages = _build_handoff_messages(summary, current_user_msg, system_msg)
            handoff_cost = _estimate_cost(summary_usage)
        else:
            effective_messages = working_set  # fallback
    else:
        effective_messages = working_set

fb_result = await fallback_executor.execute(plan.chain, effective_messages, params)
```

### 5.3 Hạch toán chi phí

Chi phí summary call cộng vào `router_cost_usd` — đúng cơ chế doc 08 §9.1 đã thiết kế:

```
router_cost_usd = classifier_cost + handoff_cost
net_cost = actual_cost + router_cost_usd
```

Thêm signal `Signal("handoff_summary", 0)` để audit.

---

## 6. Thay đổi SessionState

Thêm **một trường**:

```python
@dataclass
class SessionState:
    ...
    last_model_id: str | None = None    # MỚI — để phát hiện model switch
```

Cập nhật ở Phase 2 logging, sau khi biết model thực tế đã dùng. Tương thích ngược: `None` = không có lượt trước = không switch.

---

## 7. Ma trận trường hợp

### 7.1 Khi nào handoff kích hoạt

| # | Tình huống | Working Set | Summary | Lý do |
|---|---|---|---|---|
| H1 | Escalate T1→T2, context 1500 token | Prune theo intent | ✗ | Dưới `CONTEXT_MIN` |
| H2 | Escalate T2→T3, context 6000 token | Prune → 4000 token | ✔ | Trên threshold, escalate, đáng tiền |
| H3 | De-escalate T3→T2, context 6000 token | Prune → 3000 token | ✗ | De-escalate: model đích rẻ, WS đủ |
| H4 | Giữ nguyên tier (không switch) | ✗ | ✗ | Không prune, ăn cache |
| H5 | Single-turn (không session) | ✗ | ✗ | Không có lượt trước |
| H6 | `force_model` / `force_tier` | Full history | ✗ | Client tự quyết (doc 08 §8.1) |

### 7.2 Chất lượng — context bị mất?

| # | Tình huống | Context gốc | Summary giữ được | Mất gì |
|---|---|---|---|---|
| Q1 | "Fix race condition trong code" | Code + trace + 5 lượt tán gẫu | Code + trace + task description | Tán gẫu (đúng là nhiễu) |
| Q2 | "Sửa cái lúc nãy bạn refactor" | "Lúc nãy" ở turn 3 | `decisions: ["refactored auth module"]` | Giữ ý, mất chi tiết thảo luận |
| Q3 | "Tiếp tục viết test cho hàm trên" | "Hàm trên" ở turn trước | `code_state: "def calculate(...)..."` | Giữ code, mất lời giải thích |
| Q4 | Code 300 dòng + stack trace 200 dòng | 500 dòng raw | Code + trace giữ nguyên trong JSON | Không mất (code_state giữ nguyên) |

**Q2 là ca yếu nhất:** tham chiếu ngầm tới quyết định trước. Summary call trên model cũ (đã đọc toàn bộ hội thoại) **biết** "lúc nãy" là gì và mã hoá nó vào `decisions[]`. Strong model đọc `decisions` thay vì đọc hội thoại gốc. Chất lượng phụ thuộc vào summary call — nhưng model cũ có full context nên summary tốt.

### 7.3 Thất bại

| # | Tình huống | Hành vi |
|---|---|---|
| F1 | Summary call timeout | Gửi working set thô, signal `handoff_fallback` |
| F2 | Summary JSON hỏng / thiếu trường | Như F1 |
| F3 | Summary call trả code bị cắt (vượt max_tokens) | Code cắt + user msg nguyên → strong model vẫn có vấn đề + code một phần, tốt hơn không có gì |
| F4 | Model cũ không còn available (provider lỗi) | Bỏ summary, gửi working set thô |
| F5 | Summary call bản thân tốn quá nhiều | Cost circuit doc 08 §9.1 van #4 bảo vệ |

---

## 8. Giới hạn — nói thẳng

| # | Giới hạn | Hệ quả |
|---|---|---|
| **L1** | **Summary call thêm latency.** ~200-500ms cho một LLM call, cộng vào thời gian response. | User chờ thêm nửa giây. Mitigation: chỉ kích hoạt khi escalate + context lớn — ca hiếm |
| **L2** | **Summary có thể mất thông tin quan trọng.** Model cũ tóm tắt theo judgment của nó, có thể bỏ sót chi tiết mà strong model cần. | Không giải được triệt để. Mitigation: schema cố định buộc giữ code + decisions + unresolved |
| **L3** | **Chỉ giải được escalate, không giải de-escalate.** De-escalate mất cache model đắt (đã trả tiền), không lấy lại được. | Chấp nhận — de-escalate token rẻ nên ít đau, và Working Set đã đủ |
| **L4** | **Cache TTL ngoài tầm kiểm soát.** Nếu provider xoá cache sớm (traffic cao, quota), lợi ích "quay về model cũ cache vẫn warm" biến mất. | Không giải được — ràng buộc provider |
| **L5** | **Gateway phức tạp hơn.** Thêm một LLM call có điều kiện vào critical path. | Mitigation: timeout ngắn, fallback sạch, signal ghi log |
| **L6** | **Chưa có số đo thật.** Mọi con số ở §2 là ước lượng. Phải đo trên traffic thật trước khi tuyên bố savings. | Gate G2 ở §10 |

---

## 9. Không thuộc phạm vi

- Không đổi classifier (doc 09/10/12/13/14) — classifier chấm điểm, tài liệu này nén context.
- Không đổi Session Router state machine, hysteresis, EMA — chỉ thêm `last_model_id` vào state.
- Không đổi PolicyEngine / model selection — tài liệu này can thiệp **sau** khi model đã được chọn.
- Không đổi contract B.2 — classifier vẫn nhận `messages[]` gốc.
- Không đổi `MAX_INPUT_TOKENS` — token guard vẫn chạy trước trên messages gốc.
- Không xây cross-model cache pool — không khả thi, kể cả cùng model family.
- Không implement Working Set (doc 08 §8.1) — tài liệu này **giả định** nó sẽ được implement và xây trên nền nó. Nếu WS chưa có, handoff vẫn hoạt động (dùng full messages thay cho working set), chỉ kém tối ưu hơn.

---

## 10. Kế hoạch triển khai

| Bước | Việc | Verify |
|---|---|---|
| **0** | ⟨doc 08 §8.1⟩ Implement Working Set — prune message theo intent khi tier switch | Unit test per-intent, `CONTEXT_PRUNE_MIN_TOKENS` guard |
| **1** | Thêm `last_model_id` vào `SessionState` + cập nhật Phase 2 logging | Backward-compatible: `None` khi không có |
| **2** | Logic phát hiện model switch trong `chat_completions.py` | Test: cùng model → không switch; khác model → switch |
| **3** | Summary call: prompt §4.2.1, parse JSON, timeout, fallback | Mock adapter: JSON hợp lệ, JSON hỏng, timeout → fallback |
| **4** | `build_handoff_messages` — xây messages[] cho model đích | Test: output messages đúng format, token count < threshold |
| **5** | Wire vào `chat_completions.py` trước `fallback_executor.execute()` | Integration test: escalate session, verify messages[] gửi cho strong đã nén |
| **6** | Hạch toán `handoff_cost` vào `router_cost_usd` | Verify: admin stats công thức savings đúng |
| **G1** | **Gate: chất lượng.** Chạy eval multi-turn (doc 08 §11) A/B handoff on/off. QR/QR_hard không tụt | Phải pass trước khi bật |
| **G2** | **Gate: tiết kiệm thật.** Đo `input_tokens_saved` trên traffic thật. Savings > 0 sau khi trừ summary call cost | Phải dương |

**Thứ tự có chủ đích:** bước 0 (Working Set) mang lại lợi ích lớn nhất với chi phí thấp nhất và **không có LLM call**. Summary call (bước 3-5) chỉ đáng xây khi Working Set đã chạy và đo được là vẫn chưa đủ.

---

## Changelog

* **v1.0 — 2026-09-14** — Bản đầu. Xác định vấn đề chi phí cache miss khi đổi model giữa session multi-turn — chi phí này không có trong công thức savings hiện tại (§1.3). Đo ước lượng: tiết kiệm ~$0.075/lần switch, ~$2250/tháng ở 1000 switch/ngày (§2). Thiết kế hai tầng: Working Set (doc 08 §8.1, $0) làm baseline, summary-mediated handoff ($rẻ, chỉ khi escalate + context lớn) làm escalation (§4). Summary call chạy trên model cũ (cache hit), output JSON có schema cố định, gửi cho model đích messages[] nén 50-75%. Fallback sạch khi summary hỏng (§4.5). Một trường mới trong SessionState (`last_model_id`), hạch toán vào `router_cost_usd` (§5.3). Sáu giới hạn ghi nhận thẳng (§8), quan trọng nhất: L2 (summary mất thông tin) và L1 (thêm latency).
