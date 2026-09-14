# Pricing Snapshot 202608 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bổ sung pricing snapshot có provenance cho toàn bộ model non-mock trong cấu hình và liên kết quy trình cập nhật từ repository guide.

**Architecture:** `pricing.yaml` tiếp tục là nguồn scalar mà runtime dùng để tính cost; snapshot Markdown là bằng chứng phiên bản, nguồn chính thức và các điều kiện giá tương ứng. Guide chỉ dẫn reviewer/owner đến snapshot và quy trình duy trì, không thay đổi code hoặc hành vi gateway.

**Tech Stack:** Markdown, YAML, Python 3.11, PyYAML, pytest.

## Global Constraints

- Chỉ thay đổi `src/evals/pricing_snapshot_202608.md` và `docs/guide/cost-management.md` trong phần triển khai.
- Không sửa `pricing.yaml`, `models.yaml`, adapter, routing, cost calculator hoặc test runtime.
- Ngày thu thập của snapshot là `2026-08-13`.
- Chỉ dùng URL chính thức từ Google AI for Developers, GroqDocs và OpenAI Developers.
- Giá trong snapshot phải bằng đúng `input_per_1m_usd` và `output_per_1m_usd` trong YAML.
- Giá scalar là paid-tier, standard/on-demand, text-token, USD trên 1 triệu token.
- Model đã hoặc sắp ngừng cung cấp phải được ghi trạng thái, không được mô tả là có giá hiện hành.

---

### Task 1: Tạo pricing snapshot và đối chiếu YAML

**Files:**
- Create: `src/evals/pricing_snapshot_202608.md`
- Track: `docs/superpowers/plans/2026-08-13-pricing-snapshot.md`
- Read: `src/gateway/app/config/pricing.yaml`
- Read: `src/gateway/app/adapters/gemini_adapter.py`
- Read: `src/gateway/app/adapters/groq_adapter.py`
- Read: `src/gateway/app/adapters/openai_adapter.py`

**Interfaces:**
- Consumes: Các internal model ID và scalar giá trong `pricing.yaml`; ánh xạ provider ID trong ba adapter.
- Produces: Một bảng Markdown có thể được parse, mỗi model non-mock có đúng một hàng với 9 cột: internal ID, provider, API ID, mốc giá, input, output, chế độ, trạng thái, ngày thu thập; URL chính thức được liên kết trong mốc giá hoặc trạng thái.

- [ ] **Step 1: Chạy kiểm tra trước khi tạo file để xác nhận trạng thái thiếu snapshot**

```powershell
@'
from pathlib import Path

snapshot = Path("src/evals/pricing_snapshot_202608.md")
assert snapshot.exists(), f"Missing {snapshot}"
'@ | python -
```

Expected: FAIL với `Missing src/evals/pricing_snapshot_202608.md`.

- [ ] **Step 2: Tạo snapshot với cấu trúc và số liệu đã duyệt**

Tạo `src/evals/pricing_snapshot_202608.md` gồm:

- Mục đích và quy ước scalar.
- Bảng đối chiếu bảy model non-mock với các giá YAML sau:

| Internal ID | Provider | Input | Output |
|---|---:|---:|---:|
| `gemini-flash-lite` | google | `$0.25` | `$1.50` |
| `gemini-flash` | google | `$1.50` | `$9.00` |
| `gemini-pro` | google | `$1.25` | `$10.00` |
| `llama-3.3-70b` | groq | `$0.59` | `$0.79` |
| `deepseek-r1-distill-llama-70b` | groq | `$0.59` | `$0.79` |
| `gpt-4o-mini` | openai | `$0.15` | `$0.60` |
| `gpt-4o` | openai | `$2.50` | `$10.00` |

- Ánh xạ API/mốc giá đúng theo design spec:
  - `gemini-flash-lite-latest` / `gemini-3.1-flash-lite`.
  - `gemini-flash-latest` / `gemini-3.5-flash`.
  - `gemini-pro-latest` / `gemini-2.5-pro` với prompt không quá 200K token.
  - `llama-3.3-70b-versatile` / cùng model ID.
  - `deepseek-r1-distill-llama-70b` / giá trị lịch sử trong YAML.
  - `gpt-4o-mini` / cùng model ID.
  - `gpt-4o` / cùng model ID.
- URL chính thức:
  - `https://ai.google.dev/gemini-api/docs/pricing`
  - `https://console.groq.com/docs/models`
  - `https://console.groq.com/docs/deprecations`
  - `https://developers.openai.com/api/docs/models/gpt-4o-mini`
  - `https://developers.openai.com/api/docs/models/gpt-4o`
- Mục giá có điều kiện ghi Gemini 2.5 Pro standard trên 200K là `$2.50` input / `$15.00` output; các chế độ batch, flex, priority, cached input, cache storage, audio, image, grounding và free tier không được CostCalculator áp dụng.
- Mục trạng thái ghi DeepSeek đã shutdown và Llama 3.3 70B shutdown ngày `2026-08-16` trên free/developer tier.
- Mục owner ghi `Member 2 — Trung Hiếu`, lịch rà soát tuần đầu mỗi tháng và các trigger ngoài lịch.
- Checklist cập nhật sáu bước đã ghi trong design spec.

- [ ] **Step 3: Chạy kiểm tra tập model và scalar giá**

```powershell
@'
from pathlib import Path
import yaml

pricing = yaml.safe_load(Path("src/gateway/app/config/pricing.yaml").read_text(encoding="utf-8"))["models"]
snapshot = Path("src/evals/pricing_snapshot_202608.md").read_text(encoding="utf-8")

expected = {model: data for model, data in pricing.items() if data["provider"] != "mock"}
rows = {}
for line in snapshot.splitlines():
    cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
    if len(cells) >= 6 and cells[0] in expected:
        rows[cells[0]] = cells

assert set(rows) == set(expected), (set(expected) - set(rows), set(rows) - set(expected))
for model, data in expected.items():
    cells = rows[model]
    assert cells[1] == data["provider"], (model, cells[1], data["provider"])
    assert float(cells[4].removeprefix("$")) == float(data["input_per_1m_usd"]), model
    assert float(cells[5].removeprefix("$")) == float(data["output_per_1m_usd"]), model
    assert "2026-08-13" in cells, model
'@ | python -
```

Expected: PASS, không có output.

- [ ] **Step 4: Kiểm tra các điều kiện provenance bắt buộc**

```powershell
rg -n "200K|2\.50|15\.00|batch|cached|shutdown|2026-08-16|Member 2|Trung Hiếu|ai\.google\.dev|console\.groq\.com|developers\.openai\.com" src/evals/pricing_snapshot_202608.md
```

Expected: tất cả nhóm dữ liệu xuất hiện trong snapshot.

- [ ] **Step 5: Commit snapshot**

```powershell
git add src/evals/pricing_snapshot_202608.md docs/superpowers/plans/2026-08-13-pricing-snapshot.md
git commit -m "docs: add August 2026 pricing snapshot"
```

### Task 2: Liên kết snapshot và hướng dẫn cập nhật trong repository guide

**Files:**
- Modify: `docs/guide/cost-management.md`
- Read: `src/evals/pricing_snapshot_202608.md`

**Interfaces:**
- Consumes: Đường dẫn và chính sách owner/update từ snapshot.
- Produces: Repository guide có liên kết tương đối `../../src/evals/pricing_snapshot_202608.md` và checklist cập nhật thống nhất với snapshot.

- [ ] **Step 1: Chạy kiểm tra guide trước thay đổi**

```powershell
@'
from pathlib import Path

guide = Path("docs/guide/cost-management.md").read_text(encoding="utf-8")
assert "../../src/evals/pricing_snapshot_202608.md" in guide
assert "Trung Hi\u1ebfu" in guide
assert "pricing.yaml" in guide and "adapter" in guide
'@ | python -
```

Expected: FAIL do guide chưa liên kết snapshot.

- [ ] **Step 2: Thêm mục nguồn giá và quy trình cập nhật**

Ngay sau phần giới thiệu của `docs/guide/cost-management.md`, thêm mục `## Nguồn giá được gateway sử dụng` gồm:

- Link Markdown tới `[Pricing snapshot 08/2026](../../src/evals/pricing_snapshot_202608.md)`.
- Giải thích `pricing.yaml` là scalar runtime còn snapshot là provenance/versioned evidence.
- Owner `Member 2 — Trung Hiếu`.
- Lịch rà soát tuần đầu mỗi tháng, khi có thông báo đổi giá/deprecation và trước khi chốt eval.
- Checklist: mở nguồn chính thức; so adapter/model mapping; đối chiếu model non-mock và giá; cập nhật tier/deprecation; chạy kiểm tra; ghi thay đổi trong PR và có reviewer xác nhận.

- [ ] **Step 3: Chạy lại kiểm tra guide**

```powershell
@'
from pathlib import Path

guide_path = Path("docs/guide/cost-management.md")
guide = guide_path.read_text(encoding="utf-8")
snapshot = (guide_path.parent / "../../src/evals/pricing_snapshot_202608.md").resolve()

assert "../../src/evals/pricing_snapshot_202608.md" in guide
assert snapshot.exists(), snapshot
assert "Trung Hi\u1ebfu" in guide
assert "pricing.yaml" in guide and "adapter" in guide
assert "tu\u1ea7n \u0111\u1ea7u m\u1ed7i th\u00e1ng" in guide
'@ | python -
```

Expected: PASS, không có output.

- [ ] **Step 4: Chạy xác minh cuối cùng**

```powershell
git diff --check
python -m pytest src/gateway/tests/test_cost.py -q
git status --short
```

Expected: `git diff --check` không có lỗi; test cost PASS; status chỉ chứa thay đổi guide trước commit.

- [ ] **Step 5: Commit repository guide**

```powershell
git add docs/guide/cost-management.md docs/superpowers/plans/2026-08-13-pricing-snapshot.md
git commit -m "docs: link pricing snapshot update process"
```

- [ ] **Step 6: Xác nhận trạng thái cuối**

```powershell
git status --short
git log -3 --oneline
```

Expected: worktree sạch; các commit gần nhất gồm design spec, pricing snapshot kèm implementation plan và guide update.
