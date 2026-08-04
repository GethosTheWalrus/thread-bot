"""Complete credential version reference and approval display metadata."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0011_credential_fk_approval"
down_revision = "0010_phase2_replay_and_routes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    op.execute(sa.text("UPDATE credentials SET active_version_id = NULL WHERE active_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM credential_versions v WHERE v.id = credentials.active_version_id)"))
    op.add_column("approval_requests", sa.Column("tool_identity", sa.String(512)))
    op.create_foreign_key("fk_credentials_active_version_id_credential_versions", "credentials", "credential_versions", ["active_version_id"], ["id"], ondelete="SET NULL", use_alter=True)


def downgrade():
    raise RuntimeError("Autonomy migrations are forward-only")
