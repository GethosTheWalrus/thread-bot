"""Add thread-local agent rosters and durable turn linkage.

This migration is intentionally forward-only.  Every alteration is guarded because
0005 creates autonomy tables from ORM metadata on a fresh database.
"""
from alembic import op
import sqlalchemy as sa

revision = "0020_multi_agent_threads"
down_revision = "0019_thread_modes"
branch_labels = None
depends_on = None


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _add(table, column):
    if column.name not in _columns(table):
        op.add_column(table, column)


def _fk(table, name, columns, referred_table, referred_columns, ondelete="SET NULL"):
    names = {item.get("name") for item in sa.inspect(op.get_bind()).get_foreign_keys(table)}
    if name not in names:
        op.create_foreign_key(name, table, referred_table, columns, referred_columns, ondelete=ondelete)


def upgrade():
    bind = op.get_bind()
    _add("threads", sa.Column("workspace_id", sa.UUID(), nullable=True))
    _add("threads", sa.Column("agent_turn_limit", sa.Integer(), nullable=False, server_default="4"))
    _add("agents", sa.Column("handle", sa.String(255), nullable=False, server_default="moderator"))
    _add("agents", sa.Column("is_moderator", sa.Boolean(), nullable=False, server_default=sa.false()))
    for name, typ in (("agent_id", sa.UUID()), ("agent_version_id", sa.UUID()), ("agent_run_id", sa.UUID()), ("agent_handle", sa.String(255))):
        _add("messages", sa.Column(name, typ, nullable=True))
    for name, typ, default in (
        ("input_message_id", sa.UUID(), None), ("parent_run_id", sa.UUID(), None),
        ("root_run_id", sa.UUID(), None), ("depth", sa.Integer(), "0"),
        ("route", sa.String(32), "'user'"), ("origin_id", sa.String(255), None),
        ("origin_message_id", sa.String(255), None),
    ):
        _add("agent_runs", sa.Column(name, typ, nullable=False if name == "depth" else True, server_default=default))
    _fk("threads", "fk_threads_workspace_id_workspaces", ["workspace_id"], "workspaces", ["id"], "CASCADE")
    _fk("messages", "fk_messages_agent_id_agents", ["agent_id"], "agents", ["id"])
    _fk("messages", "fk_messages_agent_version_id_agent_versions", ["agent_version_id"], "agent_versions", ["id"])
    _fk("messages", "fk_messages_agent_run_id_agent_runs", ["agent_run_id"], "agent_runs", ["id"])
    _fk("agent_runs", "fk_agent_runs_input_message_id_messages", ["input_message_id"], "messages", ["id"])
    _fk("agent_runs", "fk_agent_runs_parent_run_id_agent_runs", ["parent_run_id"], "agent_runs", ["id"])
    _fk("agent_runs", "fk_agent_runs_root_run_id_agent_runs", ["root_run_id"], "agent_runs", ["id"])

    # Existing installations have one agent per thread.  Keep that agent as the
    # moderator and use its stable name as the initial textual handle.
    bind.execute(sa.text("UPDATE agents SET handle = COALESCE(NULLIF(regexp_replace(lower(name), '[^a-z0-9_]+', '_', 'g'), ''), 'moderator') WHERE handle IS NULL"))
    bind.execute(sa.text("UPDATE agents SET is_moderator = true WHERE thread_id IN (SELECT thread_id FROM agents GROUP BY thread_id HAVING count(*) = 1)"))
    bind.execute(sa.text("UPDATE threads t SET workspace_id = a.workspace_id FROM agents a WHERE a.thread_id = t.id AND t.workspace_id IS NULL"))
    bind.execute(sa.text("UPDATE threads SET agent_turn_limit = 4 WHERE agent_turn_limit IS NULL OR agent_turn_limit < 1"))
    # Legacy chat threads may not have an autonomy workspace.  Ownership stays
    # nullable for those rows; new thread creation always supplies it.
    bind.execute(sa.text("UPDATE messages m SET agent_id = a.id, agent_handle = a.handle FROM agents a WHERE m.metadata->>'autonomy_run_id' IS NOT NULL AND m.metadata->>'autonomy_run_id' IN (SELECT id::text FROM agent_runs WHERE agent_id = a.id)"))
    bind.execute(sa.text("UPDATE messages m SET agent_run_id = (m.metadata->>'autonomy_run_id')::uuid WHERE (m.metadata->>'autonomy_run_id') ~ '^[0-9a-fA-F-]{36}$' AND EXISTS (SELECT 1 FROM agent_runs r WHERE r.id = (m.metadata->>'autonomy_run_id')::uuid)"))
    bind.execute(sa.text("UPDATE agent_runs r SET input_message_id = m.id FROM messages m WHERE m.metadata->>'autonomy_run_id' = r.id::text AND r.input_message_id IS NULL"))
    bind.execute(sa.text("UPDATE agent_runs SET root_run_id = COALESCE(root_run_id, id) WHERE root_run_id IS NULL"))
    # Replace 0019's one-agent constraint with case-insensitive, thread-local
    # handle uniqueness.  The moderator invariant is enforced by the service
    # while the partial unique index protects concurrent writes.
    bind.execute(sa.text("ALTER TABLE agents DROP CONSTRAINT IF EXISTS uq_agents_thread_id"))
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agents_thread_handle_ci ON agents (thread_id, lower(handle))"))
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS uq_agents_thread_moderator ON agents (thread_id) WHERE is_moderator"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_threads_workspace_updated ON threads (workspace_id, updated_at DESC)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_messages_agent_run ON messages (agent_run_id)"))
    bind.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_agent_runs_parent_root ON agent_runs (parent_run_id, root_run_id, depth)"))


def downgrade():
    raise RuntimeError("Multi-agent thread migration is forward-only")
