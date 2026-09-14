# DisTributor Gateway — Architecture Diagrams

> Nguồn kiến trúc chuẩn: [`docs/design/06_architecture.md`](design/06_architecture.md)  
> Tài liệu này tổng hợp toàn bộ các sơ đồ kiến trúc (System Boundary, Module View, Runtime Flows, State Machine, ERD, Deployment) và luồng dữ liệu của hệ thống **DisTributor Gateway**.

---

## 1. System Boundary & Interactions (Sơ đồ Biên Hệ thống)

Hệ thống đóng vai trò reverse-proxy thông minh đặt giữa ứng dụng client và các nhà cung cấp LLM:

```mermaid
flowchart LR
    APP["Ứng dụng khách<br/>SDK OpenAI"]
    ADM["Admin / PM"]
    EVAL["Eval harness<br/>script trong repo"]

    subgraph SYS["System boundary — team build"]
        DASH["Dashboard<br/>React SPA"]
        GW["Gateway — modular monolith<br/>API · Orchestrator · Core · Adapters"]
        DB[("PostgreSQL / SQLite<br/>requests · feedback · keys · config")]
        CFG[/"Config YAML<br/>models · pricing · policies"/]
    end

    LLM["LLM providers<br/>Gemini · Groq · OpenAI · Mock"]

    APP -->|"HTTPS/JSON: sync · Bearer sr-key"| GW
    ADM -->|"HTTPS: thao tác UI"| DASH
    DASH -->|"HTTPS/JSON: sync · X-Admin-Key"| GW
    EVAL -->|"HTTPS/JSON: sync · force_model"| GW
    GW -->|"SQL: sync · insert bản ghi pending (Phase 1)"| DB
    GW -.->|"SQL: async background · update usage/cost (Phase 2)"| DB
    GW -.->|"đọc lúc boot · hot-swap khi PUT config"| CFG
    GW -->|"HTTPS/JSON: sync · httpx, timeout mỗi lần gọi"| LLM
```

---

## 2. Modular Monolith Architecture (Module View & Dependency Boundary)

Thiết kế theo mô hình **Modular Monolith** với nguyên tắc **Dependency Inversion**: Tầng HTTP Controller và Infrastructure phụ thuộc vào abstract ports của Domain Core, không có chiều ngược lại.

```mermaid
flowchart LR
    HTTP["HTTP Controllers<br/>/v1/chat/completions"] --> ORC["RequestOrchestrator"]
    ADMIN["Admin Controllers<br/>/admin/*"] --> REPO["Repository ports"]
    ADMIN --> CFL["ConfigLoader"]

    ORC --> CLP["BaseClassifier<br/>(abstract port)"]
    ORC --> PEP["BasePolicyEngine<br/>(abstract port)"]
    ORC --> ADP["BaseAdapter<br/>(abstract port)"]
    ORC --> COST["CostCalculator"]
    ORC --> CBK["CircuitBreaker"]
    ORC -.->|background| REPO

    INFRA["Infrastructure Layer"] --> CLP
    INFRA --> ADP
    INFRA --> REPO
    CFL --> PEP
    CFL --> COST

    subgraph ADAPTERS["Concrete Adapters"]
        GEMINI["GeminiAdapter"]
        GROQ["GroqAdapter"]
        OAI["OpenAIAdapter"]
        MOCK["MockAdapter"]
    end
    GEMINI --> ADP
    GROQ --> ADP
    OAI --> ADP
    MOCK --> ADP
```

---

## 3. Runtime Flow A: Định tuyến một Request (Happy Path)

Quy trình xử lý tuần tự từ khi Client gửi request đến khi nhận câu trả lời và cập nhật log 2 pha (ADR-008):

```mermaid
sequenceDiagram
    autonumber
    participant C as Client (OpenAI SDK)
    participant MW as Middleware
    participant O as Orchestrator
    participant CL as Classifier
    participant PE as PolicyEngine
    participant AD as Adapter
    participant P as Provider (Gemini/Groq)
    participant DB as Repository (DB)

    C->>MW: POST /v1/chat/completions
    MW->>MW: auth key · validate whitelist & giới hạn input · gán request_id
    MW->>O: handle(request)
    O->>CL: classify(messages)
    CL-->>O: score 72 · T3 · signals[] (không bao giờ raise)
    O->>PE: select(T3, policy, required_capabilities, exclude=CB.open_set())
    PE-->>O: chain = [primary, fallback1, fallback2]
    O->>DB: INSERT bản ghi tối thiểu — status=pending (đồng bộ Phase 1)
    O->>AD: complete(chain[0], messages, params)
    AD->>P: HTTPS (đã convert format)
    P-->>AD: raw response
    AD-->>O: CompletionResult{content, usage, dropped_params}
    O->>O: cost = CostCalculator.calc(model, usage)
    O-->>C: 200 OpenAI format + DisTributor + X-SR-* headers
    O--)DB: background: UPDATE usage · cost · latency → status=ok (Phase 2)
```

---

## 4. Runtime Flow B: Fallback & Circuit Breaker (Xử lý Lỗi & Dự phòng)

Orchestrator là **owner duy nhất** của retry/fallback. Adapter không tự retry.

```mermaid
sequenceDiagram
    autonumber
    participant O as Orchestrator
    participant CB as CircuitBreaker
    participant AD as Adapter
    participant P as Provider

    loop từng ModelRef trong chain, còn trong budget tổng
        O->>AD: complete(ref)
        AD->>P: HTTPS
        alt lỗi retryable — 429 / 5xx / timeout
            AD-->>O: RateLimitError · ProviderUnavailable · ProviderTimeout
            O->>CB: record_error(ref) → có thể chuyển OPEN (5 lỗi liên tiếp)
            Note over O: fallback_count++ · ghi vào chain_attempted · thử ref kế tiếp
        else lỗi không retryable — content filter · mapping sai
            AD-->>O: ContentFilteredError · BadRequestToProvider
            Note over O: DỪNG NGAY, không thử tiếp (ADR-010)
        else thành công
            AD-->>O: CompletionResult
            O->>CB: record_success(ref)
        end
    end
    Note over O: hết chain hoặc hết budget → 502 provider_error kèm chain_attempted
```

---

## 5. Runtime Flow C: Cập nhật Cấu hình Nóng (Hot-swap Config)

Đổi config từ Admin Dashboard mà không cần khởi động lại server:

```mermaid
sequenceDiagram
    autonumber
    participant A as Admin (Dashboard)
    participant API as Admin API (/admin/config)
    participant CFL as ConfigLoader
    participant DB as Repository (DB)

    A->>API: PUT /admin/config
    API->>CFL: validate(payload) — pydantic + ràng buộc chéo
    alt không hợp lệ
        CFL-->>API: danh sách {path, message}
        API-->>A: 422 — snapshot cũ nguyên vẹn
    else hợp lệ
        CFL->>DB: ghi bảng config (transaction)
        CFL->>CFL: dựng snapshot bất biến mới · hoán con trỏ atomic
        API-->>A: 200 {ok, applied_at}
    end
```

---

## 6. Vòng đời Bản ghi Log (2-Phase Logging Lifecycle)

```mermaid
stateDiagram-v2
    [*] --> pending: INSERT đồng bộ, trước khi gọi Provider
    pending --> ok: background UPDATE thành công (usage, cost, latency)
    pending --> error: request thất bại, ghi error + chain_attempted
    pending --> incomplete: reconciler quét bản ghi mồ côi (khi crash/restart)
```

---

## 7. Database Entity Relationship Diagram (ERD)

```mermaid
erDiagram
    API_KEYS ||--o{ REQUESTS : "creates"
    REQUESTS ||--o| FEEDBACK : "receives"

    API_KEYS {
        int id PK
        string name
        string key_hash "SHA-256"
        int rate_limit
        datetime created_at
        bool active
    }

    REQUESTS {
        uuid id PK "request_id"
        datetime ts
        int api_key_id FK
        int difficulty_score
        string tier "T1 / T2 / T3"
        string policy "balanced / cost_first / quality_first"
        json signals
        string classifier_version "heuristic-v1"
        string model
        string provider "google / groq / openai / mock"
        json chain_attempted
        int prompt_tokens
        int completion_tokens
        bool usage_estimated
        numeric cost_usd
        int latency_total_ms
        int latency_router_ms
        string status "pending / ok / error / incomplete"
        int fallback_count
        string error
        bool stream
    }

    FEEDBACK {
        uuid request_id PK, FK
        json tags
        string note
        datetime ts
    }

    CONFIG {
        string key PK
        json value
        datetime updated_at
    }
```

---

## 8. Deployment Architecture

```mermaid
flowchart LR
    B["Browser (User / Admin)"] -->|HTTPS| D["dashboard<br/>nginx :80 / vite :5173"]
    CLI["Client ngoài / Eval harness"] -->|":8000"| G
    D --> G["gateway<br/>uvicorn :8000"]
    G --> P[("postgres / sqlite<br/>volume / DB file")]
    G --> X["LLM providers<br/>(Gemini, Groq, OpenAI)"]
```

---

## 9. Bảng Trách nhiệm các Thành phần (Component Responsibilities)

| Thành phần | Trách nhiệm chính | **Không** chịu trách nhiệm |
|---|---|---|
| **Dashboard** | Render playground chat, biểu đồ stats, logs audit, config editor | Không tính toán business logic; không gọi trực tiếp LLM provider |
| **API Layer** | Xác thực key, validate input whitelist & limits (16k tokens, 50 msgs), đóng gói response chuẩn OpenAI | Không chứa logic chọn model; không xử lý taxonomy lỗi riêng của provider |
| **Orchestrator** | Điều phối toàn bộ luồng: classify $\rightarrow$ select $\rightarrow$ execute chain $\rightarrow$ cost $\rightarrow$ log; **owner duy nhất của retry/fallback** | Không biết schema riêng của từng provider; không ghi DB đồng bộ ngoài bản ghi `pending` |
| **Core Domain** | Chấm độ khó (Classifier), chọn chain theo policy (PolicyEngine), tính giá (CostCalculator), đếm lỗi provider (CircuitBreaker) | Không import FastAPI/SQLAlchemy; không I/O; không truy cập DB trực tiếp |
| **Adapters** | Chuyển đổi format 2 chiều giữa Gateway và API riêng của từng Provider, map taxonomy lỗi | **Không tự retry**; không chứa quy tắc chọn tier/policy; không quyết định outcome |
| **Repository** | Thao tác CRUD và SQL Aggregation cho `/admin/stats` | Không chứa business rule; không tự vá dữ liệu thiếu |
| **ConfigLoader** | Đọc DB override $\rightarrow$ fallback YAML, validate fail-fast, hoán con trỏ snapshot atomic | Không cho phép trạng thái nửa vời (sai 1 cấu hình là giữ nguyên snapshot cũ) |
