import hashlib
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from src.gateway.app.core.api_keys import verify_db_api_key
from src.gateway.app.db.models import APIKey, RequestLog
from src.gateway.app.db.models import Session as SessionModel
from src.gateway.app.db.session import SessionLocal, get_db
from src.gateway.app.main import app

ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}


def _override_get_db():
    with SessionLocal() as db:
        yield db


def _remove_keys(name_prefix: str):
    with SessionLocal() as db:
        db.query(APIKey).filter(APIKey.name.ilike(f"{name_prefix}%")).delete(synchronize_session=False)
        db.commit()


def test_admin_key_lifecycle(monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "test-admin-key")
    admin_headers = {"X-Admin-Key": "test-admin-key"}
    with SessionLocal() as s:
        s.query(SessionModel).update({"api_key_id": None})
        s.query(APIKey).delete()
        s.commit()

    def override_get_db():
        with SessionLocal() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/admin/keys",
                json={"name": "app-web", "rate_limit_per_min": 2},
                headers=admin_headers,
            )
            assert response.status_code == 201
            created = response.json()
            raw_key = created["key"]
            assert raw_key.startswith("sr-")
            assert len(raw_key) == 35
            assert created["key_masked"] == "sr-" + "*" * 4 + raw_key[-4:]

            listing = client.get("/admin/keys", headers=admin_headers)
            assert listing.status_code == 200
            assert raw_key not in listing.text
            assert listing.json()["items"][0]["total_requests"] == 0

            with SessionLocal() as db:
                stored = verify_db_api_key(raw_key, db)
                assert stored.key_hash == hashlib.sha256(raw_key.encode()).hexdigest()
                db.add(RequestLog(api_key_id=stored.id, status="ok"))
                db.commit()

            listing = client.get("/admin/keys", headers=admin_headers)
            assert listing.json()["items"][0]["total_requests"] == 1

            revoked = client.delete("/admin/keys/" + str(created["id"]), headers=admin_headers)
            assert revoked.status_code == 200
            assert revoked.json() == {"ok": True}
            with SessionLocal() as db:
                assert verify_db_api_key(raw_key, db) is None
    finally:
        app.dependency_overrides.clear()


def test_admin_key_name_is_trimmed_before_validation(monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "test-admin-key")
    prefix = f"normalized-{uuid.uuid4().hex}"
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            created = client.post(
                "/admin/keys",
                json={"name": f"  {prefix}  ", "rate_limit_per_min": 1000},
                headers=ADMIN_HEADERS,
            )
            assert created.status_code == 201
            assert created.json()["name"] == prefix

            empty = client.post(
                "/admin/keys",
                json={"name": "   ", "rate_limit_per_min": 60},
                headers=ADMIN_HEADERS,
            )
            assert empty.status_code == 422
            assert empty.json()["error"]["code"] == "validation_error"
            assert empty.json()["error"]["details"]["loc"][-1] == "name"

            too_high = client.post(
                "/admin/keys",
                json={"name": f"{prefix}-rpm", "rate_limit_per_min": 1001},
                headers=ADMIN_HEADERS,
            )
            assert too_high.status_code == 422
            assert too_high.json()["error"]["details"]["loc"][-1] == "rate_limit_per_min"
    finally:
        app.dependency_overrides.clear()
        _remove_keys(prefix)


def test_admin_key_name_is_unique_case_insensitively(monkeypatch):
    monkeypatch.setenv("ADMIN_KEY", "test-admin-key")
    prefix = f"duplicate-{uuid.uuid4().hex}"
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as client:
            first = client.post(
                "/admin/keys",
                json={"name": prefix.upper()},
                headers=ADMIN_HEADERS,
            )
            duplicate = client.post(
                "/admin/keys",
                json={"name": f"  {prefix.lower()}  "},
                headers=ADMIN_HEADERS,
            )

        assert first.status_code == 201
        assert duplicate.status_code == 409
        error = duplicate.json()["error"]
        assert error["code"] == "duplicate_api_key_name"
        assert error["details"] == {"field": "name"}
    finally:
        app.dependency_overrides.clear()
        _remove_keys(prefix)


def test_database_rejects_concurrent_duplicate_key_names():
    prefix = f"concurrent-{uuid.uuid4().hex}"
    barrier = threading.Barrier(2)

    def insert(name: str) -> str:
        with SessionLocal() as db:
            db.add(
                APIKey(
                    name=name,
                    key_hash=uuid.uuid4().hex,
                    key_masked=f"sr-****{uuid.uuid4().hex[:4]}",
                    rate_limit=60,
                )
            )
            barrier.wait()
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return "duplicate"
            return "created"

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(insert, [prefix.upper(), prefix.lower()]))
        assert sorted(results) == ["created", "duplicate"]
    finally:
        _remove_keys(prefix)


def test_database_rejects_rate_limit_outside_safe_bounds():
    key = APIKey(
        name=f"invalid-rpm-{uuid.uuid4().hex}",
        key_hash=uuid.uuid4().hex,
        key_masked="sr-****test",
        rate_limit=1001,
    )
    with SessionLocal() as db:
        db.add(key)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
