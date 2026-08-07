"""Create a protected routing-only moderator for every Agent Thread."""
from alembic import op
import hashlib
import json
import uuid
import sqlalchemy as sa


revision = "0024_system_moderators"
down_revision = "0023_backfill_thread_workspaces"
branch_labels = None
depends_on = None


PROMPT = (
    "You are ThreadBot's system-managed routing moderator. You never answer the user's question, "
    "offer commentary, or speak to the Thread. Select exactly one active participant Agent whose "
    "mandate best matches the latest user request. Return only that Agent's @handle and no other text."
)


def _hash(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {item["name"] for item in inspector.get_columns("agents")}
    if "is_system" not in columns:
        op.add_column("agents", sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()))
    threads = bind.execute(sa.text(
        "SELECT id, workspace_id FROM threads WHERE mode = 'agent' ORDER BY created_at, id"
    )).all()
    payload = {
        "schema_version": 1, "config": {"routing_only": True},
        "prompt_template": PROMPT, "tool_selection": [], "skill_selection": [],
        "credential_bindings": [],
    }
    for thread_id, workspace_id in threads:
        bind.execute(sa.text(
            "UPDATE agents SET is_moderator = false WHERE thread_id = :thread_id"
        ), {"thread_id": thread_id})
        bind.execute(sa.text("""
            UPDATE agents
            SET handle = 'agent_' || substring(replace(id::text, '-', ''), 1, 20)
            WHERE thread_id = :thread_id AND lower(handle) = 'moderator'
        """), {"thread_id": thread_id})
        agent_id, version_id = uuid.uuid4(), uuid.uuid4()
        bind.execute(sa.text("""
            INSERT INTO agents (
                id, workspace_id, thread_id, name, handle, description, status,
                execution_mode, is_moderator, is_system, concurrency_limit,
                queue_limit, created_by_type, created_by_id
            ) VALUES (
                :id, :workspace_id, :thread_id, 'Thread moderator', 'moderator',
                'Automatically routes requests to the best participant Agent.',
                'active', 'act', true, true, 1, 100, 'system', 'thread-moderator'
            )
        """), {"id": agent_id, "workspace_id": workspace_id, "thread_id": thread_id})
        bind.execute(sa.text("""
            INSERT INTO agent_versions (
                id, agent_id, version, schema_version, config, prompt_template,
                tool_selection, skill_selection, credential_bindings, config_hash,
                created_by_type, created_by_id
            ) VALUES (
                :id, :agent_id, 1, 1, CAST(:config AS jsonb), :prompt,
                CAST('[]' AS jsonb), CAST('[]' AS jsonb), CAST('[]' AS jsonb),
                :config_hash, 'system', 'thread-moderator'
            )
        """), {
            "id": version_id, "agent_id": agent_id,
            "config": json.dumps({"routing_only": True}), "prompt": PROMPT,
            "config_hash": _hash(payload),
        })
        bind.execute(sa.text(
            "UPDATE agents SET active_version_id = :version_id WHERE id = :agent_id"
        ), {"version_id": version_id, "agent_id": agent_id})
    inspector = sa.inspect(bind)
    indexes = {item["name"] for item in inspector.get_indexes("agents")}
    if "uq_agents_system_thread" not in indexes:
        op.create_index(
            "uq_agents_system_thread", "agents", ["thread_id"], unique=True,
            postgresql_where=sa.text("is_system"),
        )
    checks = {item["name"] for item in inspector.get_check_constraints("agents")}
    if "ck_agents_system_is_moderator" not in checks:
        op.create_check_constraint(
            "ck_agents_system_is_moderator", "agents", "NOT is_system OR is_moderator"
        )


def downgrade():
    raise RuntimeError("System moderator migration is forward-only")
