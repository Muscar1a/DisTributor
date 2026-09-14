"""Normalize API key names and enforce key creation limits."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260901_0007"
down_revision: str = "20260822_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_NAME_LENGTH = 255
MAX_API_KEY_RPM = 1_000


def _deduplicated_name(raw_name: str | None, key_id: int, used: set[str]) -> str:
    """Return a trimmed, non-empty, case-insensitively unique legacy name."""
    base = (raw_name or "").strip() or f"unnamed-key-{key_id}"
    candidate = base[:MAX_NAME_LENGTH]
    if candidate.lower() not in used:
        return candidate

    attempt = 1
    while True:
        suffix = f"-{key_id}" if attempt == 1 else f"-{key_id}-{attempt}"
        candidate = f"{base[: MAX_NAME_LENGTH - len(suffix)]}{suffix}"
        if candidate.lower() not in used:
            return candidate
        attempt += 1


def upgrade() -> None:
    bind = op.get_bind()
    api_keys = sa.table(
        "api_keys",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("rate_limit", sa.Integer()),
    )

    used: set[str] = set()
    rows = bind.execute(sa.select(api_keys.c.id, api_keys.c.name).order_by(api_keys.c.id)).all()
    for key_id, raw_name in rows:
        name = _deduplicated_name(raw_name, key_id, used)
        used.add(name.lower())
        if name != raw_name:
            bind.execute(api_keys.update().where(api_keys.c.id == key_id).values(name=name))

    bind.execute(
        api_keys.update()
        .where(api_keys.c.rate_limit < 1)
        .values(rate_limit=1)
    )
    bind.execute(
        api_keys.update()
        .where(api_keys.c.rate_limit > MAX_API_KEY_RPM)
        .values(rate_limit=MAX_API_KEY_RPM)
    )

    op.create_index("uq_api_keys_name_ci", "api_keys", [sa.text("lower(name)")], unique=True)
    op.create_check_constraint(
        "ck_api_keys_rate_limit_bounds",
        "api_keys",
        f"rate_limit >= 1 AND rate_limit <= {MAX_API_KEY_RPM}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_api_keys_rate_limit_bounds", "api_keys", type_="check")
    op.drop_index("uq_api_keys_name_ci", table_name="api_keys")
