"""Add sessions table, session_feedback table, fix feedback (rating -> tags)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260816_0003"
down_revision: str = "20260810_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("api_key_id", sa.Integer(), sa.ForeignKey("api_keys.id"), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(), nullable=False),
    )

    op.add_column("requests", sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_requests_session_id", "requests", "sessions", ["session_id"], ["id"])
    op.create_index("ix_requests_session_id", "requests", ["session_id"])

    op.drop_column("feedback", "rating")
    op.add_column("feedback", sa.Column("tags", sa.JSON(), nullable=True))

    op.create_table(
        "session_feedback",
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id"),
            primary_key=True,
        ),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column("ts", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("session_feedback")
    op.drop_column("feedback", "tags")
    op.add_column("feedback", sa.Column("rating", sa.Integer(), nullable=False, server_default="1"))
    op.drop_index("ix_requests_session_id", table_name="requests")
    op.drop_constraint("fk_requests_session_id", "requests", type_="foreignkey")
    op.drop_column("requests", "session_id")
    op.drop_table("sessions")
