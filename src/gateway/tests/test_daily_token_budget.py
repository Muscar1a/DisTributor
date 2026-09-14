"""AC-2: per-client daily token budget (50k/day). See docs/review/pentest_scoring_and_routing.md."""

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.gateway.app.core.quota import check_daily_token_budget, get_daily_quota_reset
from src.gateway.app.db.crud import create_api_key, sum_tokens_by_api_key
from src.gateway.app.db.models import RequestLog
from src.gateway.app.db.session import SessionLocal

_SUM = "src.gateway.app.core.quota.sum_tokens_by_api_key"


# --- decision logic (mocked sum) -------------------------------------------


def test_budget_blocks_at_or_over_limit():
    with patch(_SUM, return_value=50000):
        assert check_daily_token_budget(object_db := object(), 7, 50000) == 50000
    with patch(_SUM, return_value=60000):
        assert check_daily_token_budget(object_db, 7, 50000) == 60000


def test_budget_allows_under_limit():
    with patch(_SUM, return_value=49999):
        assert check_daily_token_budget(object(), 7, 50000) is None


def test_budget_skips_non_int_key():
    """Open mode (None) / dev key ('dev:..') không có id int -> không áp budget."""
    with patch(_SUM, return_value=999999) as m:
        assert check_daily_token_budget(object(), None, 50000) is None
        assert check_daily_token_budget(object(), "dev:abc", 50000) is None
    m.assert_not_called()


def test_budget_skips_when_limit_zero():
    with patch(_SUM, return_value=999999) as m:
        assert check_daily_token_budget(object(), 7, 0) is None
    m.assert_not_called()


def test_daily_quota_reset_is_next_utc_midnight_and_rounds_up():
    reset_at, retry_after = get_daily_quota_reset(
        datetime(2026, 8, 29, 23, 59, 59, 500_000, tzinfo=UTC)
    )

    assert reset_at == datetime(2026, 8, 30, tzinfo=UTC)
    assert retry_after == 1


# --- crud SUM over real rows ------------------------------------------------


def test_sum_tokens_by_api_key_counts_only_today():
    db = SessionLocal()
    key = create_api_key(db, name=f"budget-{uuid.uuid4().hex[:8]}", key_hash=uuid.uuid4().hex,
                         key_masked="sk-...x", rate_limit=60)
    ids = []
    try:
        now = datetime.utcnow()
        rows = [
            (now, 1000, 500),                       # today
            (now, 2000, 300),                       # today
            (now - timedelta(days=2), 9000, 9000),  # older -> excluded
        ]
        for ts, pt, ct in rows:
            r = RequestLog(id=uuid.uuid4(), ts=ts, api_key_id=key.id,
                           prompt_tokens=pt, completion_tokens=ct, status="ok")
            db.add(r)
            ids.append(r.id)
        db.commit()

        d = now.date()
        start = datetime(d.year, d.month, d.day)
        used = sum_tokens_by_api_key(db, key.id, start, start + timedelta(days=1))
        assert used == 1000 + 500 + 2000 + 300  # older row excluded
    finally:
        for rid in ids:
            db.query(RequestLog).filter(RequestLog.id == rid).delete()
        from src.gateway.app.db.models import APIKey
        db.query(APIKey).filter(APIKey.id == key.id).delete()
        db.commit()
        db.close()


# --- endpoint enforcement ---------------------------------------------------


@pytest.fixture(scope="module")
def client():
    os.environ["USE_MOCK_PROVIDERS"] = "true"
    from src.gateway.app.main import app

    with TestClient(app) as c:
        yield c


def test_endpoint_returns_429_over_budget(client):
    """Handler chặn 429 trước khi gọi provider khi budget đã cạn."""
    reset_at = datetime(2026, 8, 30, tzinfo=UTC)
    with (
        patch("src.gateway.app.api.chat_completions.check_daily_token_budget", return_value=50997),
        patch(
            "src.gateway.app.api.chat_completions.get_daily_quota_reset",
            return_value=(reset_at, 3600),
        ),
    ):
        r = client.post(
            "/v1/chat/completions",
            headers={"Origin": "https://dashboard.example.com"},
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert r.status_code == 429
    err = r.json()["error"]
    assert err["type"] == "quota_exceeded"
    assert err["code"] == "daily_token_budget_exceeded"
    assert err["details"]["limit"] == 50000
    assert err["details"]["used"] == 50997
    assert err["reset_at"] == "2026-08-30T00:00:00Z"
    assert err["retry_after_seconds"] == 3600
    assert r.headers["Retry-After"] == str(err["retry_after_seconds"])
    assert "Retry-After" in r.headers["Access-Control-Expose-Headers"]
