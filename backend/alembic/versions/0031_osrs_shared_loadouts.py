"""Add workspace-scoped OSRS loadouts and thread bindings."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0031_osrs_shared_loadouts"
down_revision = "0030_osrs_dps_gear_optimizer"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("osrs_loadouts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False), sa.Column("description", sa.String(2000)),
        sa.Column("payload", postgresql.JSONB, nullable=False), sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("source_type", sa.String(16), nullable=False, server_default="manual"), sa.Column("source_ref", sa.String(2000)),
        sa.Column("engine_revision", sa.String(255)), sa.Column("created_by_actor_type", sa.String(32), nullable=False), sa.Column("created_by_actor_id", sa.String(255), nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("schema_version = 1", name="ck_osrs_loadouts_schema_version"),
        sa.CheckConstraint("source_type IN ('manual', 'wiki', 'clone')", name="ck_osrs_loadouts_source_type"),
        sa.CheckConstraint("revision > 0", name="ck_osrs_loadouts_revision"))
    op.create_index("idx_osrs_loadouts_workspace", "osrs_loadouts", ["workspace_id"])
    op.create_index("uq_osrs_loadouts_workspace_name", "osrs_loadouts", ["workspace_id", sa.text("lower(name)")], unique=True)
    op.create_index("uq_osrs_loadouts_workspace_default", "osrs_loadouts", ["workspace_id"], unique=True, postgresql_where=sa.text("is_default = true"))
    op.create_table("thread_osrs_loadouts", sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("loadout_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("osrs_loadouts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("workspace_id", "thread_id", name="uq_thread_osrs_loadout_thread"))
    op.create_index("idx_thread_osrs_loadouts_thread", "thread_osrs_loadouts", ["workspace_id", "thread_id"])

def downgrade():
    op.drop_table("thread_osrs_loadouts"); op.drop_table("osrs_loadouts")
