# infra: Thiết lập Hạ tầng Docker & Cấu hình CI Gate kiểm tra OpenAPI Spec
* **GitHub Issue:** #26
* **Assignee:** @nairyuuu


## 👥 User Stories
- **US-01:** Là dev, tôi muốn trỏ SDK OpenAI sang gateway (đổi `base_url`) mà không sửa code nghiệp vụ

## 🎯 Goal / Problem Description
Thiết lập hạ tầng triển khai local chuẩn hóa cho Gateway và cấu hình kiểm tra tự động OpenAPI Spec qua PR.

## 📋 Acceptance Criteria (Definition of Done)
- [ ] **AC-1 (Dockerfile):** Có Dockerfile tối ưu hóa chạy được FastAPI Gateway ổn định.
- [ ] **AC-2 (Docker Compose):** Khởi chạy đồng thời Gateway và Database PostgreSQL thành công thông qua `docker compose up`.
- [ ] **AC-3 (CI Gate):** Thiết lập GitHub Actions workflow `contract.yml` chạy tự động khi tạo PR để so sánh Swagger tự động sinh từ FastAPI với file spec `v1_f1.yaml`.

## 🛠️ Proposed Implementation details
- File `Dockerfile` tối ưu hóa chạy python app.
- File `docker-compose.yml` định nghĩa service gateway và postgres db.
- File `.github/workflows/contract.yml` chạy schema validation.

## 🔗 Related Documents
- [06_architecture.md](file:///d:/AI_ThucChien_Build/docs/design/06_architecture.md)
- [02_prd.md](file:///d:/AI_ThucChien_Build/docs/design/02_prd.md)
- [04_repo_setup_ai_log.md](file:///d:/AI_ThucChien_Build/docs/design/04_repo_setup_ai_log.md)
