# ---- Stage 1: Build ----
FROM python:3.11-slim AS builder

WORKDIR /app

# In development, we can copy requirements from the root or within the component
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: Production ----
FROM python:3.11-slim

ARG APP_VERSION=0.1.0
ARG GIT_COMMIT_SHA
ARG BUILD_TIMESTAMP

ENV APP_VERSION="${APP_VERSION}" \
    GIT_COMMIT_SHA="${GIT_COMMIT_SHA}" \
    BUILD_TIMESTAMP="${BUILD_TIMESTAMP}"

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local /usr/local

# Security: run as non-root user
RUN useradd -m appuser

# Copy application code
COPY . .

# Create data directory with correct ownership
RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["uvicorn", "src.gateway.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
