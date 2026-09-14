"""Add messages (JSON) and response_content (Text) to requests table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260818_0004"
down_revision: str = "20260816_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("messages", sa.JSON(), nullable=True))
    op.add_column("requests", sa.Column("response_content", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("requests", "response_content")
    op.drop_column("requests", "messages")
