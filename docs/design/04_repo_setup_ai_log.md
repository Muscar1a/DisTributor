# GitHub Repo Setup & AI Log — SmartRoute Gateway
**Gate 1 · v1.1 · 05/08/2026**

---

## 1. Thông tin repo
- **Tên repo đề xuất:** `smartroute-gateway`
- **Mô tả:** AI Agent Gateway định tuyến đa nhà cung cấp theo độ khó request để tối ưu chi phí & chất lượng.
- **Visibility:** Private (Thuộc Organization, quản lý quyền ghi/chỉnh sửa theo danh sách cộng tác viên).
- **License:** MIT.

## 2. Cấu trúc thư mục (chuẩn cho toàn dự án)
```
smartroute-gateway/
├── README.md                  # giới thiệu, kiến trúc, cách chạy, demo
├── AI_LOG.md                  # nhật ký sử dụng AI (mục 7)
├── LICENSE
├── .env.example               # OPENAI_API_KEY=, GEMINI_API_KEY=, GROQ_API_KEY=, ADMIN_KEY=, LOG_CONTENT=false
├── .gitignore                 # .env, __pycache__, node_modules, *.db
├── docker-compose.yml         # gateway + postgres + dashboard
├── docs/
│   ├── 01_brief.md
│   ├── 02_prd.md
│   ├── 03_wireframe_ui_flow.html
│   ├── 04_repo_setup_ai_log.md
│   ├── 05_interfaces.md       # contract A/B/C/D — nguồn sự thật về mọi input/output giữa FE/BE/AI/DevOps
│   ├── 06_architecture.md     # kiến trúc chính thức: C4, runtime views, deployment, ADR
│   └── adr/                   # Architecture Decision Records (ADR-001-chon-fastapi.md, ...)
├── src/
│   ├── gateway/               # backend FastAPI
│   │   ├── app/
│   │   │   ├── main.py
│   │   │   ├── api/           # chat_completions.py, admin.py, feedback.py, health.py
│   │   │   ├── core/          # classifier_v1.py, classifier_v2.py, policy.py, cost.py, circuit.py
│   │   │   ├── adapters/      # base.py, openai_adapter.py, gemini_adapter.py, groq_adapter.py, ollama_adapter.py, mock_adapter.py
│   │   │   ├── db/            # models.py, session.py, crud.py
│   │   │   └── config/        # models.yaml, pricing.yaml, policies.yaml, loader.py
│   │   ├── tests/             # test_classifier.py, test_policy.py, test_cost.py, test_fallback.py
│   │   ├── pyproject.toml
│   │   └── Dockerfile
│   ├── dashboard/             # React + Vite + Recharts
│   │   ├── src/pages/         # Playground, Dashboard, Config, Logs, Settings
│   │   └── package.json
│   └── evals/
│       ├── datasets/mixed_200.jsonl
│       ├── run_eval.py        # chạy 4 chế độ: all_cheap | all_premium | random | smartroute
│       └── report.md          # sinh ra ở M2 (full eval), hoàn thiện ở M3
└── .github/
    ├── workflows/ci.yml       # ruff + pytest mỗi PR
    ├── ISSUE_TEMPLATE/{feature.md, bug.md}
    └── PULL_REQUEST_TEMPLATE.md
```

## 3. Checklist khởi tạo (làm ngay khi nộp Gate 1)
- [ ] Tạo repo, push `README.md`, `LICENSE`, `.gitignore`, `.env.example`, thư mục `docs/` với 6 file Gate 1 (kèm `05_interfaces.md`, `06_architecture.md`).
- [ ] Tạo `AI_LOG.md` ở root với entry đầu tiên (mẫu ở mục 7).
- [ ] Tạo branch `dev`; bật **branch protection** cho `main` (merge qua PR, CI pass).
- [ ] Tạo **Milestones**: `M1 — Vertical slice (MVP)`, `M2 — Mở rộng + Eval`, `M3 — Hoàn thiện` (deadline theo bảng lộ trình PRD §10, khóa lại theo lịch chính thức).
- [ ] Tạo **Labels**: `m1`, `m2`, `m3`, `feat`, `bug`, `docs`, `eval`, `blocked`, `interface-change`, `infra`.
- [ ] Tạo **Project board** (kiểu Kanban): `Backlog → In Progress → Review → Done`.
- [ ] Tạo issues từ danh sách FR trong PRD (mỗi FR = 1 issue, gắn milestone theo bảng lộ trình PRD §10) — dùng tiêu đề dạng `[FR-02] Heuristic difficulty classifier`.
- [ ] Thêm `ci.yml`: chạy `ruff check` + `pytest` trên PR vào `dev`/`main`.
- [ ] Mời giảng viên/TA làm collaborator (nếu repo private).

## 4. Quy ước làm việc
| Hạng mục | Quy ước |
|---|---|
| Branch | `main` (ổn định, gắn tag mỗi milestone) · `dev` (tích hợp) · `feat/fr-02-classifier`, `fix/...`, `docs/...` |
| Commit | Conventional Commits: `feat(router): heuristic scoring v1`, `fix(adapter): gemini stream parse`, `docs: gate1 prd` |
| PR | 1 FR/issue mỗi PR khi có thể; mô tả theo template (What/Why/Test/Screenshot); tự review checklist trước khi request review |
| Tag release | `v0.1-m1`, `v0.2-m2`, `v1.0-final` — mỗi tag kèm bản demo chạy được |
| ADR | Quyết định kiến trúc lớn (chọn framework, DB, phương án classifier v2) ghi 1 file ADR ngắn trong `docs/design/adr/` (tạo thư mục khi có ADR đầu tiên) |

### 4.1. Quy trình làm việc trên Kanban Board (Project)
1. **Ready**: Chọn một task có sẵn ở cột `Ready`.
2. **Assignee & Move**: Tự gán (Assign) task đó cho bản thân và kéo thẻ sang cột `In Progress`.
3. **Branching**: Tạo branch mới từ branch `dev` theo chuẩn `feature/<tên-tác-vụ>` hoặc `feat/<tên-tác-vụ>`. **Tuyệt đối không làm việc trực tiếp trên branch `main` hoặc `dev`**.
4. **Coding & Committing**: Tiến hành viết code, thực hiện commit (theo chuẩn Conventional Commits) và push lên remote.
5. **Pull Request (PR)**: Tạo Pull Request từ branch của bạn vào branch `dev` (kèm từ khóa liên kết issue, ví dụ `Closes #26`).
6. **Reviewing**: Kéo thẻ issue tương ứng sang cột `In Review` để các thành viên khác vào review.
7. **Approve & Merge**: Sau khi PR được đồng ý (Approved) từ các thành viên khác, tiến hành merge PR. Khi PR được merge, issue sẽ tự động được đóng và thẻ sẽ tự động di chuyển sang cột `Done` (nếu đã cấu hình Automation).

### 4.2. Định nghĩa Ready (Definition of Ready - DoR)
Trước khi một task được đưa sang trạng thái **Ready** để thành viên nhận việc, task đó phải đảm bảo các tiêu chí sau:
* **Mô tả chi tiết**: Ghi rõ yêu cầu nghiệp vụ và kỹ thuật cần làm.
* **Tiêu chí nghiệm thu (Acceptance Criteria)**: Định nghĩa rõ ràng các điểm cần đạt được.
  * *Ví dụ cho task `FR-03 Provider adapters`:*
    * Hỗ trợ provider OpenAI.
    * Hỗ trợ provider Gemini.
    * Hỗ trợ provider Groq.
    * Interface được thiết kế thống nhất cho mọi adapter.
    * Có viết đầy đủ Unit Test đi kèm.
* **Người thực hiện (Assignee)**: Xác định rõ ai sẽ là người đảm nhận chính.
* **Đầy đủ thông tin**: Không bị chặn (blocked) bởi các task khác và có đầy đủ tài liệu/API key/cấu hình cần thiết.

### 4.3. Định nghĩa Done cho Task (Definition of Done - DoD)
Một task chỉ được coi là hoàn thành (**Done**) khi đáp ứng đầy đủ:
* **Code chạy ổn định**: Code đã hoàn thiện chức năng, chạy đúng trên local và môi trường kiểm thử.
* **Build pass**: Code không bị lỗi cú pháp, build Docker/FastAPI thành công không có lỗi.
* **Test pass**: Vượt qua tất cả các bộ Unit Test và Integration Test mà không phát sinh lỗi.
* **PR approved & merged**: Pull Request đã được review, chấp thuận bởi các thành viên khác và đã merge vào branch tích hợp (`dev`).

## 5. Definition of Done theo Milestone
*(Scope theo chiến lược vertical slice — PRD §10.)*
- **M1 — Vertical slice (MVP):** **lõi bắt buộc** — endpoint text-only chạy với SDK OpenAI; heuristic v1; **1 adapter thật (Gemini) + Mock**; fallback tuần tự cơ bản; log 2 pha + cost đủ trường; unit test classifier ≥ 10 case; khớp `docs/design/05_interfaces.md`; AC-1, AC-3.1–3.3, AC-4, AC-5 (PRD §3.2) pass. **Cắt được nếu trễ** (thứ tự cắt: PRD §10): playground → override → adapter Groq → mini-eval 50 prompt. Tag `v0.1-m1`.
- **M2 — Mở rộng + Eval đầy đủ:** adapter provider thứ 3; circuit breaker demo được; policy engine 3 chế độ; dashboard (stats + logs) + config UI; Postgres + `docker compose up` chạy full stack; **full eval 200 prompt + report v1** với QR theo PRD §9.3; AC-2, AC-3.4–3.5, AC-6 pass; tag `v0.2-m2`.
- **M3 — Hoàn thiện:** streaming SSE; key management; *(nếu M1–M2 ổn)* classifier v2 + escalation; `evals/report.md` hoàn chỉnh (savings %, QR, latency, routing accuracy, kiểm chứng H1–H3); README đủ để người ngoài chạy lại; demo video; tag `v1.0-final`.

## 6. README skeleton (dán vào README.md)
```markdown
# SmartRoute Gateway
Định tuyến request đến LLM phù hợp theo độ khó → tối ưu chi phí, giữ chất lượng.

## Kiến trúc
(chèn sơ đồ từ docs/06_architecture.md)

## Quick start
cp .env.example .env   # điền API keys
docker compose up
# Gateway: http://localhost:8000  ·  Dashboard: http://localhost:5173

## Dùng với SDK OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="<gateway-key>")

## Kết quả eval
(bảng savings/quality — cập nhật ở M2, chốt ở M3)

## Docs
docs/01_brief.md · docs/02_prd.md · docs/03_wireframe_ui_flow.html · docs/05_interfaces.md · docs/06_architecture.md · AI_LOG.md
```

---

## 7. AI LOG — Nhật ký sử dụng AI

**Mục đích & nguyên tắc:** minh bạch việc dùng công cụ AI trong toàn dự án. Mọi output từ AI đều được (1) đọc hiểu, (2) kiểm chứng/chạy thử, (3) chỉnh sửa cho khớp bối cảnh trước khi commit. Không commit code AI sinh ra mà chưa hiểu. Mỗi lần dùng AI có ý nghĩa (thiết kế, sinh code, debug, viết test, viết docs) → thêm 1 dòng.

**Định dạng bảng (file `AI_LOG.md` ở root repo):**

| # | Ngày | Công cụ | Mốc/Task | Mục đích & prompt tóm tắt | Kết quả sử dụng | Kiểm chứng / chỉnh sửa của tôi |
|---|---|---|---|---|---|---|
| 1 | 02/08/2026 | Claude | M0 — Docs | Yêu cầu thiết kế chi tiết bộ deliverables Gate 1 (brief, PRD, wireframe, repo setup) cho đề tài gateway định tuyến theo độ khó | Bản nháp 4 tài liệu | Rà từng FR/NFR, đối chiếu yêu cầu môn học; chỉnh timeline theo lịch thực tế; xác nhận danh sách model & giá trước khi chốt ở M1 |
| 2 | 05/08/2026 | Claude | M0 — Review | Đồng bộ bỏ nhãn Gate + xử lý 8 điểm review của mentor (giả thuyết H1–H3, input spec §1.5, pain points §2.2, AC §3.2, công thức QR §9.3, thu hẹp scope vertical slice, 2 quyết định kỹ thuật ADR-009/010, log 2 pha) | Brief/PRD/interfaces/architecture v1.1 | Đối chiếu từng điểm review với chỗ sửa; 2 trade-off (content-filter không fallback, classifier lỗi→T2) do team tự chốt — sẽ xin mentor confirm |
| 3 | *(mẫu)* 10/08/2026 | Claude Code / Copilot | M1 — FR-02 | Sinh khung `classifier_v1.py` + 10 unit test theo bảng scoring trong PRD §6.2 | Code khởi tạo classifier | Chạy pytest, thêm 5 case tiếng Việt bị miss, chỉnh trọng số tín hiệu code từ 25→22 |
| 4 | ... | | | | | |

**Ghi chú thêm mỗi mốc:** cuối mỗi milestone viết 3–5 dòng tổng kết: AI giúp nhanh nhất ở đâu, sai ở đâu, bài học prompt.
