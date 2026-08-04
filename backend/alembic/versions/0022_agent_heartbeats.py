"""Add adaptive agent heartbeat supervision table.

Forward-only.  Stores per-agent adaptive wake configuration, operational status,
and last decision so a durable Temporal workflow can wake the agent without a
trigger event, evaluate the immutable agent version against thread context,
and schedule a bounded next wake.  No user message is ever synthesized for a
heartbeat run.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "0022_agent_heartbeats"
down_revision = "0021_reconcile_multi_agent_schema"
branch_labels = None
depends_on = None


def _table_exists(bind, name):
    return name in sa.inspect(bind).get_table_names()


def upgrade():
    bind = op.get_bind()

    if not _table_exists(bind, "agent_heartbeats"):
        op.create_table(
            "agent_heartbeats",
            sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("workspace_id", UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
            sa.Column("thread_id", UUID(as_uuid=True), sa.ForeignKey("threads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("enabled", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("min_wake_seconds", sa.Integer, nullable=False, server_default="300"),
            sa.Column("max_wake_seconds", sa.Integer, nullable=False, server_default="3600"),
            sa.Column("idle_backoff_factor", sa.Numeric(5, 2), nullable=False, server_default="2.0"),
            sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
            sa.Column("operational_status", sa.String(32), nullable=False, server_default="disabled"),
            sa.Column("workflow_id", sa.String(255), nullable=True),
            sa.Column("last_wake_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("next_wake_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_decision", sa.String(32), nullable=True),
            sa.Column("last_run_id", UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("consecutive_noops", sa.Integer, nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint("min_wake_seconds BETWEEN 30 AND 86400", name="ck_agent_heartbeats_min_wake"),
            sa.CheckConstraint("max_wake_seconds BETWEEN 30 AND 604800", name="ck_agent_heartbeats_max_wake"),
            sa.CheckConstraint("min_wake_seconds <= max_wake_seconds", name="ck_agent_heartbeats_min_le_max"),
            sa.CheckConstraint("idle_backoff_factor BETWEEN 1.0 AND 10.0", name="ck_agent_heartbeats_backoff"),
            sa.CheckConstraint("consecutive_noops >= 0", name="ck_agent_heartbeats_noops"),
            sa.CheckConstraint(
                "operational_status IN ('disabled','scheduled','evaluating','paused',"
                "'blocked_mode','blocked_archived','blocked_global','error')",
                name="ck_agent_heartbeats_status",
            ),
            sa.CheckConstraint(
                "last_decision IS NULL OR last_decision IN ('response','action','delegate','no_op')",
                name="ck_agent_heartbeats_decision",
            ),
        )

    # Indexes (idempotent)
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_status_wake "
            "ON agent_heartbeats (workspace_id, operational_status, next_wake_at)"
        )
    )
    bind.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS idx_agent_heartbeats_thread_enabled "
            "ON agent_heartbeats (thread_id, enabled)"
        )
    )


def downgrade():
    raise RuntimeError("Schema reconciliation is forward-only")