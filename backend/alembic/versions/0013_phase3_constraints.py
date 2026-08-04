"""Complete Phase 3 constraints and operational indexes."""
from alembic import op
import sqlalchemy as sa
revision = "0013_phase3_constraints"; down_revision = "0012_phase3"; branch_labels = None; depends_on = None
def upgrade():
    op.create_index("idx_handoffs_target_status", "agent_handoffs", ["target_agent_id", "status"])
    op.create_foreign_key("fk_policy_recommendations_workspace", "policy_recommendations", "workspaces", ["workspace_id"], ["id"], ondelete="CASCADE")
def downgrade(): raise RuntimeError("Autonomy migrations are forward-only")
