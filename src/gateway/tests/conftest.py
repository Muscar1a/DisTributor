import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# BẮT BUỘC: Đặt môi trường TEST và Database Test độc lập trước khi import gateway modules
# Nhờ vậy pytest KHÔNG BAO GIỜ chạm vào hoặc xóa Database dev (smartroute)
os.environ["APP_ENV"] = "test"
test_db_url = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg2://sr:smartroute@localhost:5432/smartroute_test")
os.environ["DATABASE_URL"] = test_db_url

import pytest  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from src.gateway.app.core.interfaces import Message  # noqa: E402
from src.gateway.app.db.models import Base  # noqa: E402
from src.gateway.app.db.session import engine  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _create_shared_tables():
    database_url = make_url(os.environ["DATABASE_URL"])
    remote_host = database_url.host and database_url.host not in {"localhost", "127.0.0.1", "::1"}
    if remote_host and os.getenv("APP_ENV", "").lower() != "test":
        raise RuntimeError(
            "Refusing to run gateway tests against a remote database unless APP_ENV=test is set explicitly."
        )
    Base.metadata.create_all(engine._get())


@pytest.fixture
def mock_messages():
    return [Message(role="user", content="Hello, what is 2+2?")]
