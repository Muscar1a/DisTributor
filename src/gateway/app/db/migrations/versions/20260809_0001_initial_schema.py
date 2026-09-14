"""Create the initial gateway database schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260809_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column("rate_limit", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_api_keys_id", "api_keys", ["id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "config",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
        sa.Column("api_key_id", sa.Integer(), sa.ForeignKey("api_keys.id")),
        sa.Column("difficulty_score", sa.Integer()),
        sa.Column("tier", sa.String()),
        sa.Column("policy", sa.String()),
        sa.Column("signals", sa.JSON()),
        sa.Column("classifier_version", sa.String()),
        sa.Column("model", sa.String()),
        sa.Column("provider", sa.String()),
        sa.Column("chain_attempted", sa.JSON()),
        sa.Column("prompt_tokens", sa.Integer()),
        sa.Column("completion_tokens", sa.Integer()),
        sa.Column("usage_estimated", sa.Boolean(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6)),
        sa.Column("latency_total_ms", sa.Integer()),
        sa.Column("latency_router_ms", sa.Integer()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("fallback_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.String()),
        sa.Column("stream", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_requests_ts", "requests", ["ts"])
    op.create_index("ix_requests_tier", "requests", ["tier"])
    op.create_index("ix_requests_provider", "requests", ["provider"])
    op.create_index("ix_requests_api_key_id_ts", "requests", ["api_key_id", "ts"])

    op.create_table(
        "feedback",
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requests.id"),
            primary_key=True,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("note", sa.String()),
        sa.Column("ts", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_index("ix_requests_api_key_id_ts", table_name="requests")
    op.drop_index("ix_requests_provider", table_name="requests")
    op.drop_index("ix_requests_tier", table_name="requests")
    op.drop_index("ix_requests_ts", table_name="requests")
    op.drop_table("requests")
    op.drop_table("config")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_id", table_name="api_keys")
    op.drop_table("api_keys")
