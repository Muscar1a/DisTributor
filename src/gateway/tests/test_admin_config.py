"""Integration test cho GET/PUT /admin/config (F2 hot-reload)."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    os.environ.setdefault("USE_MOCK_PROVIDERS", "true")
    old_admin_key = os.environ.get("ADMIN_KEY")
    os.environ["ADMIN_KEY"] = "test-admin-key"
    # Admin endpoints always require an explicit key, including in tests.
    from src.gateway.app.db.models import ConfigSetting
    from src.gateway.app.db.session import SessionLocal

    # Xoá override từ lần chạy trước — nếu không lifespan sẽ load t1_max=25 vào app.state.config
    with SessionLocal() as s:
        s.query(ConfigSetting).filter(ConfigSetting.key == "routing_overrides").delete()
        s.commit()

    from src.gateway.app.main import app

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    if old_admin_key is None:
        os.environ.pop("ADMIN_KEY", None)
    else:
        os.environ["ADMIN_KEY"] = old_admin_key


ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


def test_get_config_tra_ve_dung_truong(client):
    r = client.get("/admin/config", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["default_policy"] == "balanced"
    assert body["t1_max"] == 30
    assert body["t2_max"] == 60
    assert "balanced" in body["policies"]
    assert body["policies"]["balanced"]["tier_shift"] == 0


def test_put_config_cap_nhat_thanh_cong(client):
    r = client.put("/admin/config", json={"t1_max": 25, "t2_max": 55}, headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Xác nhận live config đã đổi
    r2 = client.get("/admin/config", headers=ADMIN_HEADERS)
    assert r2.json()["t1_max"] == 25
    assert r2.json()["t2_max"] == 55

    # Reset về mặc định (models.yaml) để không nhiễm test khác cùng module
    reset = client.put("/admin/config", json={"t1_max": 30, "t2_max": 60}, headers=ADMIN_HEADERS)
    assert reset.status_code == 200


def test_put_config_vi_pham_cross_constraint_tra_422(client):
    r = client.put("/admin/config", json={"t1_max": 60, "t2_max": 40}, headers=ADMIN_HEADERS)
    assert r.status_code == 422


def test_put_config_policy_khong_ton_tai_tra_422(client):
    r = client.put("/admin/config", json={"default_policy": "khong-co-that"}, headers=ADMIN_HEADERS)
    assert r.status_code == 422


def test_put_config_extra_field_tra_422(client):
    r = client.put("/admin/config", json={"order_by": "latency"}, headers=ADMIN_HEADERS)
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "validation_error"
