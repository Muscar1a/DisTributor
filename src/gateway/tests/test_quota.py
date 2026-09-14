"""Tests cho GET /admin/usage/quota (07_quota_tracking.md)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.gateway.app.api.admin import router as admin_router
from src.gateway.app.db.session import get_db


def _mock_db():
    return MagicMock()


def _make_client():
    app = FastAPI()
    app.include_router(admin_router, prefix="/admin")
    app.dependency_overrides[get_db] = lambda: _mock_db()
    return TestClient(app, raise_server_exceptions=False)


_QUOTA_CONFIG = [
    {"group": "premium", "limit_tokens": 250000, "models": ["gpt-5.4", "gpt-4o"]},
    {"group": "standard", "limit_tokens": 2500000, "models": ["gpt-5-nano", "gpt-4o-mini"]},
]


@pytest.fixture(autouse=True)
def patch_quota(monkeypatch):
    """Dùng quota config tối giản, không đọc file thật."""
    import src.gateway.app.api.admin as admin_module

    admin_module._load_quota.cache_clear()
    monkeypatch.setattr(admin_module, "_load_quota", lambda: _QUOTA_CONFIG)


def test_ac1_no_date_returns_today():
    """AC-1: không truyền date → trả ngày hôm nay."""
    with patch("src.gateway.app.api.admin.sum_tokens_by_model", return_value={}):
        resp = _make_client().get("/admin/usage/quota")
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == datetime.now(UTC).date().isoformat()


def test_ac2_specific_date():
    """AC-2: truyền date cụ thể → trả đúng ngày."""
    with patch("src.gateway.app.api.admin.sum_tokens_by_model", return_value={}):
        resp = _make_client().get("/admin/usage/quota?date=2026-08-01")
    assert resp.status_code == 200
    assert resp.json()["date"] == "2026-08-01"


def test_ac3_used_tokens_aggregated():
    """AC-3: used_tokens = tổng token của các model thuộc nhóm."""
    usage = {"gpt-5.4": 50000, "gpt-4o": 37400, "gpt-5-nano": 310000}
    with patch("src.gateway.app.api.admin.sum_tokens_by_model", return_value=usage):
        resp = _make_client().get("/admin/usage/quota")
    body = resp.json()
    premium = next(q for q in body["quotas"] if q["group"] == "premium")
    assert premium["used_tokens"] == 87400
    assert premium["remaining_tokens"] == 250000 - 87400
    assert premium["used_pct"] == round(87400 / 250000 * 100, 2)


def test_ac4_breakdown_only_nonzero():
    """AC-4: breakdown chỉ chứa model có used_tokens > 0."""
    usage = {"gpt-5.4": 50000}
    with patch("src.gateway.app.api.admin.sum_tokens_by_model", return_value=usage):
        resp = _make_client().get("/admin/usage/quota")
    premium = next(q for q in resp.json()["quotas"] if q["group"] == "premium")
    assert "gpt-5.4" in premium["breakdown"]
    assert "gpt-4o" not in premium["breakdown"]


def test_ac5_invalid_date_returns_400():
    """AC-5: date sai định dạng → 400."""
    with patch("src.gateway.app.api.admin.sum_tokens_by_model", return_value={}):
        resp = _make_client().get("/admin/usage/quota?date=19-08-2026")
    assert resp.status_code == 400


def test_ac6_no_requests_returns_zero():
    """AC-6: không có request nào → used_tokens=0, breakdown={}."""
    with patch("src.gateway.app.api.admin.sum_tokens_by_model", return_value={}):
        resp = _make_client().get("/admin/usage/quota")
    for q in resp.json()["quotas"]:
        assert q["used_tokens"] == 0
        assert q["breakdown"] == {}
