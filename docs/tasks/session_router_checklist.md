# Session Router + Classifier — Implementation Checklist
* **Design doc:** `docs/design/08_adaptive_routing.md` (v1.2) · `09_classifier_v1_5.md` (v1.0, mục M) · `10_classifier_input_domains.md` (v1.0, mục N)
* **Branch:** `feat/llm-classifier`
* **Cập nhật:** 21/08/2026 — thêm mục M (classifier v1.5) và N (domain input mới). Trạng thái mục M xác minh bằng `pytest` + đọc diff, không theo trí nhớ.

---

## A. Config — `config/routing.yaml` (§5)

- [x] **`routing.yaml`** — 7 tham số tunable: `alpha`, `deescalate_margin`, `dwell_turns`, `max_session_escalations`, `failure_boost`, `streak_boost`, `similarity_threshold`
- [x] **`RoutingConfig` dataclass** — frozen, defaults khớp §5, load từ YAML
- [x] **`load_routing_config()`** — fallback về defaults nếu file thiếu
- [ ] **Hot-reload qua `/admin/config`** — chỉnh nóng routing params qua admin endpoint

## B. TurnAnalyzer — `turn_analyzer.py` (§5.1)

- [x] **`classify_intent(last_msg, prev_user_msg) -> str`** — priority: correction > new_task > meta > refine > continue, song ngữ Việt–Anh
- [x] **`analyze_turn(messages, similarity_threshold) -> Turn`** — trả Turn dataclass gom intent + failure_signal + positive_ack + has_error_artifact + has_concurrency
- [x] **`_has_new_error_artifact(messages, last_msg) -> bool`** — fingerprint SHA-1, so sánh trong mảng messages, chỉ phát hiện trace MỚI
- [x] **`_is_resubmission(last_msg, prev_user_msg, threshold) -> bool`** — Jaccard similarity + length-difference guard (<30%)
- [x] **`count_hard_signals(classifier_signals, turn) -> tuple[int, bool]`** — tập `{code, math_logic, multi_step, error_artifact, concurrency_keywords}`, jump = `{error_artifact, concurrency_keywords}`
- [x] **`_POSITIVE_ACK_RE`** — "works now / chạy được rồi / ok cảm ơn / thanks that fixed it"
- [x] **`_CONCURRENCY_RE`** — race/deadlock/thread/async/lock/mutex/concurrent keywords
- [ ] **Signal `resolved_ack`** — §6.1(c): positive-ack xuất signal `resolved_ack` để giải thích

## C. SessionState — `state.py` (§4)

- [x] **`SessionState` dataclass** — 10 trường: turn_count, current_tier, tier_history(cap 5), ema_score, failure_streak, unresolved_failure, failed_tier, last_escalation_turn, session_escalation_count, last_user_msg_hash
- [x] **`to_dict()` / `from_dict()`** — JSONB serialization roundtrip
- [x] **`is_expired(last_activity_at, ttl_s)`** — lazy TTL check (2h default)
- [x] **Fixed-size ~300 bytes** — mọi trường scalar, hai mảng cap 5

## D. SessionRouter — `router.py` (§5, §6, §7)

- [x] **`route(messages, state, cls) -> (Tier, list[Signal], SessionState)`** — thuật toán §5 đầy đủ
- [x] **§6.1: Clear `unresolved_failure`** — đầu lượt khi intent ∈ {refine, meta, continue} + không failure mới; hoặc positive_ack / new_task
- [x] **Effective score: EMA inheritance** — continue/refine/correction kế thừa `max(score, ema)`
- [x] **Effective score: new_task reset** — cắt kế thừa, chấm từ đầu
- [x] **Failure boost** — `failure_boost + streak_boost * min(streak, 2)`, chỉ khi chưa cạn budget
- [x] **`_escalate()`** — max +1 tier/lượt; nhảy T3 khi ≥2 hard signals + ≥1 jump signal
- [x] **`_deescalate()`** — 4 hold checks (correction, unresolved, dwell, margin) rồi new_task→raw, meta→raw, refine/continue→cur-1
- [x] **Dwell check** — dùng `current_turn = state.turn_count + 1`
- [x] **Margin check** — dùng raw `cls.score`, không dùng effective score
- [x] **Failure lock** — `unresolved_failure` + intent ≠ meta → giữ tier
- [x] **Failed tier floor** — không route lại vào tier đã fail
- [x] **§6.2: Budget exhausted → pin T3** + signal `escalation_budget_exhausted`
- [x] **`_update_state()`** — EMA dùng effective_score, escalation/failure tracking, new_task reset ema
- [x] **`_init_state_from_messages()`** — degraded mode §5.3: suy từ mảng messages

## E. DB: Migration + CRUD (§4, §4.1)

- [x] **Migration `20260820_0005`** — thêm `routing_state` JSON column vào `sessions`
- [x] **`Session.routing_state`** — cột mới trong model
- [x] **`get_routing_state(db, session_id)`** — trả `(dict | None, datetime | None)` cho TTL check
- [x] **`update_routing_state(db, session_id, new_state)`** — optimistic guard: chỉ ghi khi turn_count mới hơn

## F. Wiring — `main.py` + `chat_completions.py` (§13 step 2)

- [x] **`main.py` lifespan** — construct SessionRouter với config, attach `app.state.session_router`
- [x] **`chat_completions.py`** — chèn giữa classify và policy.select: load state → TTL → `route()` → set `force_tier`
- [x] **Bypass khi `force_model` hoặc `force_tier`** — session routing chỉ khi client không override
- [x] **Phase 2 persist** — ghi `new_routing_state.to_dict()` vào DB qua background task

## G. OutcomeObserver (§9, §13 step 3)

- [ ] **`OutcomeObserver` class** — background phase 2, nhận evidence từ nhiều nguồn
- [ ] **Refusal heuristic** — detect model refusal trong output (FR-17)
- [ ] **Length heuristic** — output bất thường ngắn/dài
- [ ] **`OutcomeObserver.record(session_id, evidence)`** — interface mở cho evidence ngoài
- [ ] **Nối feedback endpoint** — `POST /v1/feedback` / session-feedback clear `unresolved_failure` (§6.1(d))

## H. Eval — Datasets & Metrics (§11, §13 steps 1,3)

- [ ] **`evals/datasets/turn_intents_50.jsonl`** — 50 lượt gán nhãn intent, ≥8 case/intent, song ngữ
- [x] **`src/evals/datasets/multiturn_30.jsonl`** — ~30 hội thoại synthetic (đã có)
- [ ] **`evals/gold_tiers.py`** — 3 tier × k=3 samples, cache vĩnh viễn
- [ ] **`evals/metrics.py`** — Task Success Rate, Routing Accuracy, Under/Over-routing, Savings%, Latency, Stability
- [ ] **Unit test TurnAnalyzer** — chạy trên `turn_intents_50.jsonl`, accuracy ≥85%, zero correction-miss
- [ ] **Replay test SessionRouter** — 10 hội thoại synthetic, assert đúng tier sequence
- [ ] **Gold multi-turn (a) turn-level** — prefix cố định T3, chấm từng lượt độc lập
- [ ] **Gold multi-turn (b) trajectory-level** — router thật end-to-end, đo task success + cost + stability

## I. Context Length Handling (§8)

- [x] **`context_window` trong `pricing.yaml`** — per-model context window (tokens), loaded vào `ModelPricing.context_window`
- [x] **Filter model theo context window** — `PolicyEngineV1._chain_for()` loại model có `context_window < input_tokens`; tier rỗng → chain tier cao hơn (existing `_tiers_from` logic); hết model → `NoCapableModelError`

## K. Working Set / Context Pruning (§8.1)

- [ ] **Prune on switch, keep on stay** — chỉ prune khi tier thay đổi (prompt cache per-model → đổi tier = mất cache, prune miễn phí)
- [ ] **Working set theo intent** — `new_task`: system + turn hiện tại; `meta`/`refine`: system + assistant reply cuối + turn; `correction`: system + code block mới nhất + error artifact + cặp cuối + turn; `continue`: system + K=3 cặp cuối + code block anchor
- [ ] **Anchor detection** — nhận diện fenced code block cuối / error-artifact fingerprint; fallback = full history
- [ ] **`smartroute.context_mode`** — mặc định `"full"` (không đổi hành vi); `"auto"` opt-in khi tier switch + history > `CONTEXT_PRUNE_MIN_TOKENS`
- [ ] **Response metadata** — `smartroute.context = {mode, messages_sent, messages_total, input_tokens_saved}` + header `X-SR-Context-Mode`
- [ ] **Eval guard A/B** — chạy trajectory-level pruning on/off, chỉ bật khi QR/QR_hard giữ guard

## L. Router Cost Accounting (§9.1)

- [ ] **`router_cost_usd` trong `requests`** — trường mới, mặc định 0 với heuristic router
- [ ] **Net savings** — `/admin/stats` và eval report tính `savings = baseline − (cost + router_cost)`
- [ ] **Cost circuit** — nếu `Σ router_cost / Σ total_cost > ROUTER_COST_BUDGET_PCT` (2%) trong 24h → tắt v2 classifier, fallback heuristic, `/healthz` báo degraded

## J. Demo & Dashboard (§12, §13 Demo)

- [x] **Playground badge tier** — `Playground.jsx:263` badge `tierCode · difficulty` theo `TIER_COLOR`, `:418` chấm màu mỗi message
- [ ] **`/admin/requests/{id}`** — hiển thị chuỗi signals giải thích routing decision · endpoint **chưa có**; hiện Playground đã render câu giải thích signals (`Playground.jsx:125`), nên nhu cầu demo đã được phủ — mục này còn lại là trang admin
- [x] **Session routing signals trong response header** — `X-SR-Tier`, `X-SR-Tier-Effective`, `X-SR-Score`, `X-SR-Model`, `X-SR-Cost-USD`, `X-SR-Request-Id` đều đã set

## M. Classifier v1.5 — `09_classifier_v1_5.md` §12

Trạng thái xác minh ngày 21/08/2026: `pytest src/gateway/tests/test_{zoning,classifier_v1_5,classifier}.py` → **130 passed**.

- [x] **1. `zoning.py`** — tách instruction/artifact zone · 7 test pass (fence, inline code, stack trace, fence không đóng B7, chuỗi rỗng, chỉ-fence) · ⚠️ **thiếu case fence lồng (B8)** và **indented block ≥3 dòng** dù cả hai đã implement
- [x] **2. Quy tắc đảo §4.1 + sửa regex §6.4** — syntax regex chỉ chạy trên artifact, intent regex chỉ trên instruction; E1–E7 có regression test (`test_zone_inversion_no_false_code`, `test_date_not_math`, `test_range_not_math`, `test_two_short_questions_not_multi_step`)
- [x] **3. Lexicon D1–D6 + M1–M5 + động từ ý định/danh từ kỹ thuật** — đủ 6 driver kèm guard (`test_guard_d2_library_usage`, `test_guard_d3_no_evidence`, `test_guard_d6_library_integration`), song ngữ Việt–Anh + biến thể không dấu · ⚠️ **G4 chưa verify** vì thiếu dataset
- [x] **4. `band()` + công thức chấm §6.1 + fast-path mới §6.5** — `test_c1_with_max_modifiers_stays_t1` (modifier không đổi được tier), `test_short_coding_task_no_fast_path` (E8–E10)
- [ ] **5. Bảng ví dụ §6.6 thành test tham số hoá** — **(một phần)** `test_scoring_examples` mới có **11/17 dòng**, thiếu 6
- [ ] **6. `narrative_pairs_20.jsonl` + test bất biến** — dataset **chưa có**; hiện chỉ 2 test hardcode một cặp (`test_narrative_invariant_hello_world_bare/_verbose`)
- [ ] **7. Chạy lại `mixed_200.jsonl`, so phân bố tier v1 vs v1.5** — chưa chạy; đây là số liệu savings% cho báo cáo
- [ ] **8. `classifier_version = "heuristic-v1.5"`** — **(một phần)** code đã trả đúng chuỗi, nhưng **`05_interfaces.md` B.2 (dòng 305) vẫn là `"heuristic-v1" | "llm-v2" | "embed-v2"`** — thiếu `heuristic-v1.5`
- [ ] **9. Cập nhật PRD §6.2 sang bảng §7** — hiện mới có block con trỏ sang doc 09, chưa thay bảng trọng số

### M.1 Ngoài kế hoạch §12 — đã làm thêm

- [x] **Opt-in `smartroute.classifier_version: "v1" | "v1.5"`** — `chat_completions.py` chọn classifier theo request. v1.5 **không** phải mặc định → v1 và test cũ không bị đụng, nên **regression §11.3 chưa kích hoạt** (sẽ đỏ khi v1.5 lên làm mặc định)
- [x] **Selector `Classifier: v1 / v1.5` trên Playground** — `Playground.jsx`, `api.js` truyền tham số; đủ để so sánh A/B thủ công ngay trên demo
- [x] **Log signals mỗi request** — `logger.info("classifier=... score=... tier=... signals=...")`
- [x] **Fix `update_routing_state`** — `json.dumps(new_state)` trong `crud.py:149`; trước đó truyền thẳng `dict` vào raw SQL param nên state **không ghi được**. Mục E đã tick từ trước nhưng đường ghi thực tế hỏng cho tới lần sửa này

### M.2 Cổng §11.1

- [x] **G5** — E1–E10 có regression test, tất cả pass
- [ ] **G1** — zero hard → T1 · có `test_under_routing_regression` nhưng **chưa chạy trên dataset gán nhãn**
- [ ] **G2** — accuracy ≥80% trên bộ 30 prompt · chưa chạy
- [ ] **G3** — bất biến kể chuyện ≥95% · chặn bởi bước 6
- [ ] **G4** — phân giải hạng ≥85% · chặn bởi dataset dưới
- [ ] **G6** — router p95 < 300ms, hard cap 800ms · chưa đo
- [ ] **`src/evals/datasets/coding_bands_60.jsonl`** — 60 prompt, 20/hạng, song ngữ
- [ ] **`src/evals/datasets/narrative_pairs_20.jsonl`** — 20 cặp (task trần ↔ task bọc văn kể)

---

## N. Classifier — domain input mới — `10_classifier_input_domains.md`

> **G1 là cổng chặn.** Ba mệnh đề H1/H2/H3 mới chỉ là suy luận từ đọc code, chưa chạy để xác nhận. **Không implement §4/§6 trước khi qua G1** — toàn bộ thiết kế nhóm A dựa vào H1.

- [x] **G1 (chặn) — xác nhận H1/H2/H3 bằng probe chạy thật**
  * H1: ✅ XÁC NHẬN — `_MARKER_M2_RE` chứa nhánh `example` bắt trúng section header `Example` → đề CF 2100 bị kéo xuống C1/T1 (score=8)
  * H2: ✅ KHÔNG ÁP DỤNG — API chỉ nhận `role ∈ {user, system, assistant}` + `content: str`; `role="tool"` hoặc list-of-blocks bị Pydantic reject
  * H3: ✅ XÁC NHẬN — `_prompt_text()` trả message `role="user"` cuối → trong vòng lặp agent chấm lại prompt gốc

**Nhóm A — đề competitive programming** (đo được: dải 800–2600 nén vào T1/T2, **không đề nào chạm T3**)

- [x] **A1. Genre detector CP** — ≥2 marker cấu trúc (`time limit per test`, `the number of test cases`, ký hiệu ràng buộc `n ≤ 2·10⁵`, bộ ba `Input`/`Output`/`Example`) — §4.1
- [x] **A2. Band cho `genre == CP`** — bỏ qua M1–M5 và `length`; sàn **C2, không bao giờ C1**; 5 luật nâng C3 (n,q ≥ 10⁵ + update · `998244353` · interactive · ràng buộc ≥ 10⁹ · danh từ kỹ thuật khó) — §4.2
- [ ] **A3. Dataset `src/evals/datasets/cp_problems_40.jsonl`** — 40 đề thật kèm rating gốc, trải 800–2600 · ngưỡng: **không đề ≥1900 nào rơi T1**

**Nhóm B — codebase qua agent harness** (đo được: `"Fix this."` + 60 dòng Go có `go func`/`sync.Mutex` → **T2**)

- [ ] **B4. Tài liệu hoá `force_tier` như tính năng tích hợp harness chính thức** — §6.4 · **làm trước B1/B2**: harness tự biết lượt này là "đọc file" hay "thiết kế lại module", chính xác hơn mọi cách suy ngược từ text đã bị nén, và **không cần code mới**
- [ ] **B1. Strip comment + string literal** khỏi artifact zone trước khi quét cú pháp — §6.3
- [ ] **B2. `_D1_SYNTAX_RE` trên artifact zone** — ≥2 construct đồng thời **khác nhau** → nâng band lên C3; **chỉ nâng, không bao giờ hạ** — §6.2
- [ ] **B3. Sửa đổi doc 09 §4.2** — ghi rõ luật hai loại bằng chứng: *lexical* (chữ trong comment/string) vẫn cấm, *structural* (cú pháp thực thi được) được nâng band một chiều
- [ ] **G3 doc 10 — đo phân bố tier trên transcript agent thật (20+ lượt), bật/tắt EMA inheritance** → trả lời §5.2 bằng số: `max(score, ema)` ở intent `continue` là đúng (cả vòng lặp là một task) hay rò rỉ chi phí (đa số lượt là cơ học)
- [ ] **G5 doc 10 — genre detector false positive < 2%** trên dataset hiện có
- [ ] **G4 doc 10 — regression doc 09**: toàn bộ case §8 của doc 09 giữ nguyên kết quả, 0 hồi quy

**Ngoài phạm vi, ghi lại để không phát hiện lại:** sandbox chạy sample test của đề CP (§4.3 doc 10) — đây là câu trả lời *đúng* cho nhóm A vì mỗi đề tự mang theo test oracle, nhưng cần sandbox thực thi + giới hạn tài nguyên. Bản **human-in-the-loop chạy được ngay**: user báo "wrong answer on test 3" → `correction` + error artifact → `failure_boost` escalate theo §6.1 doc 08. Và §4.4: **v2/LLM không cứu được nhóm A** — rating CF là đại lượng đo trên quần thể thí sinh, không phải thuộc tính của văn bản đề.

---

**Tổng: 53/97 done.** *(G1 + A1 + A2 ticked — 21/08/2026)*

| Mục | Trạng thái |
|---|---|
| A–F, I — core engine Session Router + context window | ✅ hoàn chỉnh |
| M1–M4 — zoning, quy tắc đảo, lexicon, band scoring | ✅ implement + 130 test pass |
| M5, M8 — bảng ví dụ, `classifier_version` | 🟡 một phần |
| M6, M7, M2-gates — dataset + eval v1.5 | ❌ chặn bởi 2 dataset thiếu |
| G, H, K, L — OutcomeObserver, eval pipeline, pruning, router cost | ❌ chưa bắt đầu |
| J — demo UI | 🟡 2/3, còn trang `/admin/requests/{id}` |
| N — domain input mới (CP + agent harness) | 🟡 G1 pass, A1+A2 done (93 test pass); A3 dataset + nhóm B chưa bắt đầu |

**Đường tới hạn cho demo:** hai dataset `coding_bands_60.jsonl` + `narrative_pairs_20.jsonl` đang chặn 4 cổng (G1–G4) của v1.5. Không có chúng thì không có số liệu chứng minh v1.5 tốt hơn v1 — mà đó chính là luận điểm của cả doc 09.

