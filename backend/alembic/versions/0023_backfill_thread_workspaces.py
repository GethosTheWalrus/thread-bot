"""Assign legacy threads to the default workspace.

Revision 0020 intentionally left agentless legacy threads without an owner, but
thread listing is workspace-scoped. Backfill those rows before making ownership
required so existing conversations remain visible after an upgrade.
"""
from alembic import op
import sqlalchemy as sa


revision = "0023_backfill_thread_workspaces"
down_revision = "0022_agent_heartbeats"
branch_labels = None
depends_on = None


DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE threads SET workspace_id = :workspace_id WHERE workspace_id IS NULL"
    ), {"workspace_id": DEFAULT_WORKSPACE_ID})
    op.alter_column("threads", "workspace_id", existing_type=sa.UUID(), nullable=False)


def downgrade():
    raise RuntimeError("Thread workspace ownership migration is forward-only")
