"""persist workspace scoped SLO observations

Revision ID: 0017_slo_metrics
Revises: 0016_phase4_canary_assignment_workspace
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017_slo_metrics"
down_revision = "0016_phase4_canary_assignment_workspace"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "slo_metrics",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("idx_slo_metrics_workspace_metric", "slo_metrics", ["workspace_id", "metric", "observed_at"])


def downgrade():
    op.drop_index("idx_slo_metrics_workspace_metric", table_name="slo_metrics")
    op.drop_table("slo_metrics")
