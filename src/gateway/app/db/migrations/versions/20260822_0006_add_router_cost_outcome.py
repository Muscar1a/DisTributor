"""Add router_cost_usd and outcome_evidence columns to requests table."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0006"
down_revision: str = "20260820_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("requests", sa.Column("router_cost_usd", sa.Numeric(10, 6), nullable=True))
    op.add_column("requests", sa.Column("outcome_evidence", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("requests", "outcome_evidence")
    op.drop_column("requests", "router_cost_usd")
