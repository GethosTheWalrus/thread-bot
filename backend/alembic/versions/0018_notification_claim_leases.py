"""Add leases for in-flight notification deliveries."""
from alembic import op
import sqlalchemy as sa

revision = "0018_notification_claim_leases"
down_revision = "0017_slo_metrics"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notification_deliveries", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.add_column("notification_deliveries", sa.Column("claim_expires_at", sa.DateTime(timezone=True)))
    op.create_index(
        "idx_notification_deliveries_claim_expiry",
        "notification_deliveries",
        ["status", "claim_expires_at"],
    )


def downgrade():
    raise RuntimeError("Autonomy migrations are forward-only")
