"""Reconcile multi-agent indexes, constraints, and route nullability.

This revision is additive and forward-only.  The guards are needed because the
autonomy tables are created from ORM metadata on a fresh database.
"""
from alembic import op
import sqlalchemy as sa


revision = "0021_reconcile_multi_agent_schema"
down_revision = "0020_multi_agent_threads"
branch_labels = None
depends_on = None


def _index_names(table):
    return {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes(table)}


def _ensure_index(name, table, expression):
    if name not in _index_names(table):
        op.get_bind().execute(sa.text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({expression})"))


def _drop_legacy_agent_name_uniqueness():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {"workspace_id", "name"}
    for constraint in inspector.get_unique_constraints("agents"):
        if set(constraint.get("column_names") or ()) == columns and constraint.get("name"):
            op.drop_constraint(constraint["name"], "agents", type_="unique")

    # Some PostgreSQL installations expose the old uniqueness as a unique
    # index rather than a table constraint.
    for index in sa.inspect(bind).get_indexes("agents"):
        if index.get("unique") and set(index.get("column_names") or ()) == columns and index.get("name"):
            op.drop_index(index["name"], table_name="agents")


def upgrade():
    bind = op.get_bind()

    bind.execute(sa.text("UPDATE agent_runs SET route = 'user' WHERE route IS NULL"))
    bind.execute(sa.text("ALTER TABLE agent_runs ALTER COLUMN route SET DEFAULT 'user'"))
    bind.execute(sa.text("ALTER TABLE agent_runs ALTER COLUMN route SET NOT NULL"))

    _drop_legacy_agent_name_uniqueness()
    _ensure_index("idx_agent_runs_thread_route", "agent_runs", "thread_id, route, queued_at")
    _ensure_index("idx_messages_agent_handle", "messages", "thread_id, agent_handle")
    _ensure_index("idx_agent_runs_parent_root", "agent_runs", "parent_run_id, root_run_id, depth")
    _ensure_index("idx_messages_agent_run", "messages", "agent_run_id")
    _ensure_index("idx_threads_workspace_updated", "threads", "workspace_id, updated_at DESC")


def downgrade():
    raise RuntimeError("Schema reconciliation is forward-only")
