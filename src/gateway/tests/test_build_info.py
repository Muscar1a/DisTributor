from src.gateway.app.core.build_info import get_build_metadata

BUILD_ENV_NAMES = (
    "APP_VERSION",
    "GIT_COMMIT_SHA",
    "RENDER_GIT_COMMIT",
    "BUILD_TIMESTAMP",
)


def _clear_build_environment(monkeypatch):
    for name in BUILD_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_build_metadata_has_safe_local_defaults(monkeypatch):
    _clear_build_environment(monkeypatch)

    assert get_build_metadata() == {
        "version": "0.1.0",
        "commit_sha": "unknown",
        "build_timestamp": "unknown",
    }


def test_git_commit_sha_takes_precedence_and_is_shortened(monkeypatch):
    _clear_build_environment(monkeypatch)
    monkeypatch.setenv("GIT_COMMIT_SHA", "18BFBAA1234567890ABCDEF1234567890ABCDEF1")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef0123456789abcdef0123456789abcdef01")

    assert get_build_metadata()["commit_sha"] == "18bfbaa"


def test_render_commit_is_used_as_fallback(monkeypatch):
    _clear_build_environment(monkeypatch)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef0123456789abcdef0123456789abcdef01")

    assert get_build_metadata()["commit_sha"] == "abcdef0"


def test_build_metadata_normalizes_utc_timestamp(monkeypatch):
    _clear_build_environment(monkeypatch)
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    monkeypatch.setenv("BUILD_TIMESTAMP", "2026-08-29T07:00:00+07:00")

    metadata = get_build_metadata()
    assert metadata["version"] == "1.2.3"
    assert metadata["build_timestamp"] == "2026-08-29T00:00:00Z"


def test_invalid_public_metadata_is_not_echoed(monkeypatch):
    _clear_build_environment(monkeypatch)
    monkeypatch.setenv("GIT_COMMIT_SHA", "not-a-commit")
    monkeypatch.setenv("BUILD_TIMESTAMP", "not-a-timestamp")

    metadata = get_build_metadata()
    assert metadata["commit_sha"] == "unknown"
    assert metadata["build_timestamp"] == "unknown"
