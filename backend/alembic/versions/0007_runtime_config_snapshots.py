"""Immutable, secret-free runtime snapshots and action authorization metadata.

Revision ID: 0007_runtime_config_snapshots
Revises: 0006_core_foreign_keys
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

revision = "0007_runtime_config_snapshots"
down_revision = "0006_core_foreign_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "runtime_config_snapshots" not in inspector.get_table_names():
        op.create_table(
        "runtime_config_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("model_credential_binding_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("credential_bindings.id", ondelete="RESTRICT")),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("workspace_id", "config_hash", name="uq_runtime_snapshots_workspace_hash"),
        )
    def has_column(name):
        return bind.exec_driver_sql(f"SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'agent_actions' AND column_name = '{name}'").scalar() is not None
    if not has_column("authorization_ref"):
        op.add_column("agent_actions", sa.Column("authorization_ref", sa.String(255)))
    if not has_column("authorization_hash"):
        op.add_column("agent_actions", sa.Column("authorization_hash", sa.String(64)))


def downgrade() -> None:
    raise RuntimeError("Autonomy migrations are forward-only; restore a database backup instead.")
