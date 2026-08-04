"""Durable approval projections and dry-run action state."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

revision = "0008_approvals_and_simulation"
down_revision = "0007_runtime_config_snapshots"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    has_simulated = bind.exec_driver_sql("SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'agent_actions' AND column_name = 'simulated'").scalar() is not None
    if not has_simulated:
        op.add_column("agent_actions", sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.false()))
    checks = inspect(bind).get_check_constraints("agent_actions")
    for check in checks:
        if "status" in (check.get("sqltext") or "") and check.get("name") != "ck_agent_actions_status_v2":
            op.drop_constraint(check["name"], "agent_actions", type_="check")
    if not any(check.get("name") == "ck_agent_actions_status_v2" for check in inspect(bind).get_check_constraints("agent_actions")):
        op.create_check_constraint("ck_agent_actions_status_v2", "agent_actions", "status IN ('planned','policy_denied','awaiting_approval','authorized','denied','expired','cancelled','executing','simulated','succeeded','failed','outcome_unknown','reconciled_succeeded','reconciled_failed','operator_closed')")
    if "approval_requests" not in inspect(bind).get_table_names():
        op.create_table(
        "approval_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.String(128), nullable=False), sa.Column("action_revision", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("policy_ref", sa.String(255)), sa.Column("credential_ref", sa.String(255)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("run_id", "action_id", "action_revision", name="uq_approval_requests_action"),
        )
    if "approval_decisions" not in inspect(bind).get_table_names():
        op.create_table(
        "approval_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False), sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text()), sa.Column("provider_interaction_id", sa.String(255)), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("request_id", name="uq_approval_decisions_request"),
        )

def downgrade() -> None:
    raise RuntimeError("Autonomy migrations are forward-only")
