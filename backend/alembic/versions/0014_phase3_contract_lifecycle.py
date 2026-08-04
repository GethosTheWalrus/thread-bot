"""Add lifecycle and optimistic concurrency fields to handoff contracts."""
from alembic import op
import sqlalchemy as sa
revision = "0014_phase3_contract_lifecycle"; down_revision = "0013_phase3_constraints"; branch_labels = None; depends_on = None
def upgrade():
    op.add_column("handoff_contracts", sa.Column("status", sa.String(16), nullable=False, server_default="draft"))
    op.add_column("handoff_contracts", sa.Column("lifecycle_version", sa.Integer, nullable=False, server_default="1"))
    op.add_column("handoff_contracts", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
def downgrade(): raise RuntimeError("Autonomy migrations are forward-only")
