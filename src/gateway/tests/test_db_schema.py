from sqlalchemy import inspect

from src.gateway.app.db.models import APIKey, Base, User
from src.gateway.app.db.session import engine


def test_metadata_creates_expected_tables_and_indexes():
    real_engine = engine._get()
    Base.metadata.create_all(bind=real_engine)
    inspector = inspect(real_engine)

    assert {"users", "api_keys", "config", "feedback", "requests", "sessions", "session_feedback"} <= set(
        inspector.get_table_names()
    )
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    assert {"email", "password_hash", "preferences", "active"} <= user_columns
    user_indexes = {index.name for index in User.__table__.indexes}
    assert "uq_users_email_ci" in user_indexes

    api_key_columns = {column["name"] for column in inspector.get_columns("api_keys")}
    assert "key_masked" in api_key_columns
    assert "user_id" in api_key_columns
    # SQLite cannot reflect expression-based indexes, so assert the declared
    # schema here; duplicate-insert tests separately prove enforcement.
    api_key_indexes = {index.name for index in APIKey.__table__.indexes}
    assert "uq_api_keys_name_ci" in api_key_indexes
    api_key_checks = {constraint["name"] for constraint in inspector.get_check_constraints("api_keys")}
    assert "ck_api_keys_rate_limit_bounds" in api_key_checks
    request_columns = {column["name"] for column in inspector.get_columns("requests")}
    assert {"difficulty_score", "signals", "chain_attempted", "status", "session_id"} <= request_columns

    request_indexes = {index["name"] for index in inspector.get_indexes("requests")}
    assert {
        "ix_requests_api_key_id_ts",
        "ix_requests_provider",
        "ix_requests_tier",
        "ix_requests_ts",
    } <= request_indexes
