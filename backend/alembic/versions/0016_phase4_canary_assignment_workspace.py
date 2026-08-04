"""Add tenant ownership and integrity constraints to canary assignments."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0016_phase4_canary_assignment_workspace"
down_revision = "0015_phase4_replay_rollout_observability"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("canary_assignments", sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.execute("UPDATE canary_assignments a SET workspace_id = d.workspace_id FROM canary_deployments d WHERE d.id = a.deployment_id")
    op.alter_column("canary_assignments", "workspace_id", nullable=False)
    op.create_foreign_key("fk_canary_assignments_workspace", "canary_assignments", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE")
    op.create_index("idx_canary_assignments_workspace", "canary_assignments", ["workspace_id", "deployment_id"])
    op.create_check_constraint("ck_canary_assignments_bucket", "canary_assignments", "length(trim(bucket)) > 0")


def downgrade():
    raise RuntimeError("Autonomy migrations are forward-only")
