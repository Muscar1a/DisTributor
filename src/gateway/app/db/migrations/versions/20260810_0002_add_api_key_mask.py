import sqlalchemy as sa
from alembic import op

revision = "20260810_0002"
down_revision = "20260809_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "api_keys",
        sa.Column("key_masked", sa.String(), nullable=False, server_default="sr-redacted"),
    )


def downgrade():
    op.drop_column("api_keys", "key_masked")
