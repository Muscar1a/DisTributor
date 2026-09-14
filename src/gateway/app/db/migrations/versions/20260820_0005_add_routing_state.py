"""Add routing_state JSONB column to sessions table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0005"
down_revision: str = "20260818_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("routing_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "routing_state")
