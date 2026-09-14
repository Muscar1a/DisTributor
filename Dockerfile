FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim AS runtime

ARG APP_VERSION=0.1.0
ARG GIT_COMMIT_SHA
ARG BUILD_TIMESTAMP

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL="postgresql+psycopg2://sr:smartroute@db:5432/smartroute" \
    PATH="/opt/venv/bin:$PATH" \
    APP_VERSION="${APP_VERSION}" \
    GIT_COMMIT_SHA="${GIT_COMMIT_SHA}" \
    BUILD_TIMESTAMP="${BUILD_TIMESTAMP}"
WORKDIR /app

RUN python -m venv /opt/venv \
    && useradd --create-home --shell /usr/sbin/nologin appuser

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

COPY --chown=appuser:appuser alembic.ini ./
COPY --chown=appuser:appuser src ./src

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=3)"

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn src.gateway.app.main:app --host 0.0.0.0 --port 8000"]
