import os
import threading

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session as _SASession

load_dotenv()


def build_sync_database_url(database_url: str, *, require_ssl: bool | None = None) -> str:
    url = make_url(database_url)
    if url.drivername in {"postgresql+asyncpg", "postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg2")

    is_postgres = url.drivername.startswith("postgresql")
    if require_ssl is None:
        require_ssl = os.getenv("APP_ENV", "development").lower() in {"production", "prod"}
    if is_postgres and require_ssl and url.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
        url = url.update_query_dict({"sslmode": "require"})
    return url.render_as_string(hide_password=False)


def _make_engine():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")
    sync_url = build_sync_database_url(database_url)
    return create_engine(sync_url, pool_pre_ping=True, pool_recycle=300)


class _LazyEngine:
    """Defers engine creation until first attribute access."""

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def _get(self):
        if self._engine is None:
            with self._lock:
                if self._engine is None:
                    self._engine = _make_engine()
        return self._engine

    def __getattr__(self, name):
        return getattr(self._get(), name)


engine = _LazyEngine()


def SessionLocal() -> _SASession:  # noqa: N802
    # SA 2.0: pass the real engine directly so the session tracks one connection.
    return _SASession(engine._get(), autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
