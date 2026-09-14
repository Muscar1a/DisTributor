import importlib

migration = importlib.import_module(
    "src.gateway.app.db.migrations.versions.20260901_0007_normalize_api_key_names"
)


def test_legacy_names_become_non_empty_and_case_insensitively_unique():
    used: set[str] = set()
    legacy_rows = [(1, "   "), (2, " Production "), (3, "production"), (4, None)]

    migrated = []
    for key_id, raw_name in legacy_rows:
        name = migration._deduplicated_name(raw_name, key_id, used)
        used.add(name.lower())
        migrated.append(name)

    assert migrated == ["unnamed-key-1", "Production", "production-3", "unnamed-key-4"]


def test_legacy_duplicate_suffix_stays_within_column_length():
    used = {"a" * migration.MAX_NAME_LENGTH}
    name = migration._deduplicated_name("a" * 300, 42, used)

    assert len(name) == migration.MAX_NAME_LENGTH
    assert name.endswith("-42")

