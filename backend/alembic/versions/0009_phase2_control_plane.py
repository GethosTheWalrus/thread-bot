"""Phase 2 connectors, notification delivery, state diffs and dead letters."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_phase2_control_plane"
down_revision = "0008_approvals_and_simulation"
branch_labels = None
depends_on = None


def _uuid():
    return postgresql.UUID(as_uuid=True)


def upgrade():
    op.add_column("approval_requests", sa.Column("risk_level", sa.String(32), nullable=False, server_default="unknown"))
    op.add_column("approval_requests", sa.Column("target", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("approval_requests", sa.Column("redacted_arguments", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("approval_requests", sa.Column("policy_explanation", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("approval_decisions", sa.Column("actor_type", sa.String(32), nullable=False, server_default="human"))
    op.add_column("approval_decisions", sa.Column("channel", sa.String(32), nullable=False, server_default="web"))
    op.create_table("connectors", sa.Column("id", _uuid(), primary_key=True), sa.Column("workspace_id", _uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("connector_type", sa.String(32), nullable=False), sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("credential_binding_id", _uuid(), sa.ForeignKey("credential_bindings.id", ondelete="SET NULL")), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("workspace_id", "name", name="uq_connectors_workspace_name"))
    op.create_table("connector_cursors", sa.Column("id", _uuid(), primary_key=True), sa.Column("workspace_id", _uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("connector_id", _uuid(), sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False), sa.Column("subject_key", sa.String(512), nullable=False), sa.Column("cursor", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("fingerprint", sa.String(64)), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("connector_id", "subject_key", name="uq_connector_cursors_subject"))
    op.create_table("notification_profiles", sa.Column("id", _uuid(), primary_key=True), sa.Column("workspace_id", _uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("routes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("workspace_id", "name", name="uq_notification_profiles_workspace_name"))
    op.create_table("notification_deliveries", sa.Column("id", _uuid(), primary_key=True), sa.Column("workspace_id", _uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("profile_id", _uuid(), sa.ForeignKey("notification_profiles.id", ondelete="SET NULL")), sa.Column("route", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("event_type", sa.String(255), nullable=False), sa.Column("business_key", sa.String(512), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("status", sa.String(32), nullable=False, server_default="pending"), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("last_error", sa.Text()), sa.Column("delivered_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("workspace_id", "business_key", name="uq_notification_deliveries_business"))
    op.create_index("idx_notification_deliveries_status", "notification_deliveries", ["status", "available_at"])
    op.create_table("dead_letters", sa.Column("id", _uuid(), primary_key=True), sa.Column("workspace_id", _uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("stage", sa.String(64), nullable=False), sa.Column("reason", sa.String(255), nullable=False), sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("status", sa.String(32), nullable=False, server_default="open"), sa.Column("resolution", sa.Text()), sa.Column("resolved_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_index("idx_dead_letters_workspace_status", "dead_letters", ["workspace_id", "status"])
    op.create_table("state_diffs", sa.Column("id", _uuid(), primary_key=True), sa.Column("workspace_id", _uuid(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("run_id", _uuid(), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False), sa.Column("before_hash", sa.String(64), nullable=False), sa.Column("after_hash", sa.String(64), nullable=False), sa.Column("diff", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))


def downgrade():
    raise RuntimeError("Autonomy migrations are forward-only")
