"""Durable webhook replay protection, connector suppression and notification routes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_phase2_replay_and_routes"
down_revision = "0009_phase2_control_plane"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("connector_cursors", sa.Column("last_event_at", sa.DateTime(timezone=True)))
    op.add_column("connector_cursors", sa.Column("cooldown_until", sa.DateTime(timezone=True)))
    op.add_column("connector_cursors", sa.Column("suppressed_count", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("webhook_nonces", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("connector_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False), sa.Column("nonce", sa.String(255), nullable=False), sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("connector_id", "nonce", name="uq_webhook_nonces_connector_nonce"))
    op.create_index("idx_webhook_nonces_expires", "webhook_nonces", ["expires_at"])
    op.create_index("idx_state_diffs_run_created", "state_diffs", ["run_id", "created_at"])
    op.create_table("notification_routes", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True), sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("profile_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("notification_profiles.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("channel", sa.String(32), nullable=False), sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("filters", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("credential_binding_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credential_bindings.id", ondelete="SET NULL")), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("profile_id", "name", name="uq_notification_routes_profile_name"))


def downgrade():
    raise RuntimeError("Autonomy migrations are forward-only")
