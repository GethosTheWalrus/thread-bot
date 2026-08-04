"""Phase 4 replay, rollout, forecasting and operator control projections."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0015_phase4_replay_rollout_observability"
down_revision = "0014_phase3_contract_lifecycle"
branch_labels = None
depends_on = None

def _json():
    return postgresql.JSONB(astext_type=sa.Text())

def upgrade():
    op.alter_column(
        "alembic_version",
        "version_num",
        type_=sa.String(length=255),
        existing_type=sa.String(length=32),
        existing_nullable=False,
    )
    op.create_table("replay_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_run_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("replay_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("agent_version_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("effect_free", sa.Boolean(), nullable=False, server_default=sa.text("true")), sa.Column("timeline", _json(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("comparison", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["source_run_id"], ["agent_runs.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["replay_run_id"], ["agent_runs.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["agent_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("mode IN ('recorded','reexecution')"))
    op.create_index("idx_replay_sessions_source", "replay_sessions", ["workspace_id", "source_run_id"])
    op.create_table("canary_deployments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stable_version_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("candidate_version_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("cohort", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("status", sa.String(16), nullable=False, server_default="draft"), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["stable_version_id"], ["agent_versions.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["candidate_version_id"], ["agent_versions.id"], ondelete="RESTRICT"), sa.CheckConstraint("status IN ('draft','active','promoted','rolled_back','paused')"))
    op.create_index("idx_canary_deployments_agent_status", "canary_deployments", ["agent_id", "status"])
    op.create_table("canary_assignments", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("deployment_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("bucket", sa.String(64), nullable=False), sa.Column("assigned_version_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["deployment_id"], ["canary_deployments.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["run_id"], ["agent_runs.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["assigned_version_id"], ["agent_versions.id"], ondelete="RESTRICT"), sa.UniqueConstraint("deployment_id", "run_id"))
    op.create_table("canary_comparisons", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("deployment_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("candidate_run_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("stable_run_id", postgresql.UUID(as_uuid=True)), sa.Column("metrics", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["deployment_id"], ["canary_deployments.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["candidate_run_id"], ["agent_runs.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["stable_run_id"], ["agent_runs.id"], ondelete="RESTRICT"), sa.UniqueConstraint("deployment_id", "candidate_run_id", "stable_run_id"))
    op.create_index("idx_canary_comparisons_deployment", "canary_comparisons", ["deployment_id", "created_at"])
    op.create_table("forecast_snapshots", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("horizon_hours", sa.Integer(), nullable=False), sa.Column("forecast", _json(), nullable=False), sa.Column("assumptions", _json(), nullable=False, server_default=sa.text("'[]'::jsonb")), sa.Column("confidence", sa.String(16), nullable=False, server_default="low"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"))
    op.create_table("recovery_operations", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("actor_id", sa.String(255), nullable=False), sa.Column("operation", sa.String(64), nullable=False), sa.Column("resource_type", sa.String(64), nullable=False), sa.Column("resource_id", sa.String(255), nullable=False), sa.Column("details", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"))
    op.create_index("idx_recovery_operations_workspace", "recovery_operations", ["workspace_id", "created_at"])
    op.create_table("slo_alerts", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("alert_key", sa.String(255), nullable=False), sa.Column("metric", sa.String(64), nullable=False), sa.Column("threshold", sa.Integer(), nullable=False), sa.Column("status", sa.String(16), nullable=False, server_default="ok"), sa.Column("details", _json(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.UniqueConstraint("workspace_id", "alert_key"))
    op.create_table("queue_controls", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False), sa.Column("queue_name", sa.String(255), nullable=False), sa.Column("state", sa.String(16), nullable=False, server_default="running"), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"), sa.UniqueConstraint("workspace_id", "queue_name"))

def downgrade():
    raise RuntimeError("Autonomy migrations are forward-only")
