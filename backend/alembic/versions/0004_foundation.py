"""Complete foundation indexes and outbox claim state.

Revision ID: 0004_foundation
Revises: 0003_foundation
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_foundation"
down_revision = "0003_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_principals_workspace", "principals", ["workspace_id"])
    op.add_column("outbox_messages", sa.Column("status", sa.String(32), nullable=False, server_default="pending"))
    op.add_column("outbox_messages", sa.Column("claimed_by", sa.String(255), nullable=True))
    op.add_column("outbox_messages", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("outbox_messages", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_outbox_claimable", "outbox_messages", ["status", "available_at", "locked_at"])


def downgrade() -> None:
    raise RuntimeError("Foundation migration is intentionally irreversible; restore a database backup instead.")
