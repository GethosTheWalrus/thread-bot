"""Make threads the chat/agent boundary and enforce one agent per thread."""
from alembic import op
import sqlalchemy as sa

revision = "0019_thread_modes"
down_revision = "0018_notification_claim_leases"
branch_labels = None
depends_on = None

def upgrade():
    inspector = sa.inspect(op.get_bind())
    thread_columns = {item["name"] for item in inspector.get_columns("threads")}
    if "mode" not in thread_columns:
        op.add_column("threads", sa.Column("mode", sa.String(16), nullable=False, server_default="chat"))
    if "archived_at" not in thread_columns:
        op.add_column("threads", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    if "ck_threads_mode" not in {item.get("name") for item in inspector.get_check_constraints("threads")}:
        op.create_check_constraint("ck_threads_mode", "threads", "mode IN ('chat', 'agent')")
    op.execute("UPDATE threads SET mode = 'agent' WHERE id IN (SELECT thread_id FROM agents)")
    if "uq_agents_thread_id" not in {item.get("name") for item in inspector.get_unique_constraints("agents")}:
        op.create_unique_constraint("uq_agents_thread_id", "agents", ["thread_id"])
    lease_columns = {item["name"] for item in inspector.get_columns("thread_execution_leases")}
    if "execution_type" not in lease_columns:
        op.add_column("thread_execution_leases", sa.Column("execution_type", sa.String(32), nullable=False, server_default="agent_run"))
    if "execution_id" not in lease_columns:
        op.add_column("thread_execution_leases", sa.Column("execution_id", sa.String(255), nullable=True))

def downgrade():
    raise RuntimeError("Thread mode migration is forward-only")
