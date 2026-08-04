"""Add security, durable events, audit, outbox, and credential references.

Revision ID: 0003_foundation
Revises: 0002_require_created_timestamps
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_foundation"
down_revision = "0002_require_created_timestamps"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSON = postgresql.JSONB()
NOW = sa.text("now()")
EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    op.create_table("workspaces", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
                    sa.Column("name", sa.String(255), nullable=False), sa.Column("slug", sa.String(255), nullable=False, unique=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW))
    op.execute(sa.text("INSERT INTO workspaces (id, name, slug) VALUES ('00000000-0000-0000-0000-000000000001', 'Default workspace', 'default') ON CONFLICT DO NOTHING"))
    op.create_table("principals", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
                    sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
                    sa.Column("actor_type", sa.String(32), nullable=False), sa.Column("actor_id", sa.String(255), nullable=False),
                    sa.Column("display_name", sa.String(255)), sa.Column("roles", JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
                    sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
                    sa.UniqueConstraint("workspace_id", "actor_type", "actor_id"))
    op.execute(sa.text("INSERT INTO principals (workspace_id, actor_type, actor_id, display_name, roles) VALUES ('00000000-0000-0000-0000-000000000001', 'human', 'local-owner', 'Local owner', '[\"owner\",\"admin\"]') ON CONFLICT DO NOTHING"))
    op.create_table("api_tokens", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("actor_id", sa.String(255), nullable=False), sa.Column("token_hash", sa.Text, nullable=False), sa.Column("token_prefix", sa.String(16), nullable=False), sa.Column("roles", JSON, nullable=False, server_default=sa.text("'[\"admin\"]'::jsonb")), sa.Column("expires_at", sa.DateTime(timezone=True)), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW))
    op.create_table("audit_events", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("actor_type", sa.String(32), nullable=False), sa.Column("actor_id", sa.String(255), nullable=False), sa.Column("action", sa.String(255), nullable=False), sa.Column("resource_type", sa.String(255)), sa.Column("resource_id", sa.String(255)), sa.Column("metadata", JSON, nullable=False, server_default=EMPTY), sa.Column("correlation_id", UUID, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW))
    op.create_table("domain_events", sa.Column("sequence", sa.Integer, primary_key=True, autoincrement=True), sa.Column("id", UUID, nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")), sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("event_type", sa.String(255), nullable=False), sa.Column("payload", JSON, nullable=False, server_default=EMPTY), sa.Column("dedupe_key", sa.String(255)), sa.Column("correlation_id", UUID, nullable=False), sa.Column("causation_id", UUID), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW), sa.UniqueConstraint("workspace_id", "dedupe_key"))
    op.create_table("outbox_messages", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("event_id", UUID), sa.Column("topic", sa.String(255), nullable=False), sa.Column("payload", JSON, nullable=False, server_default=EMPTY), sa.Column("idempotency_key", sa.String(255), nullable=False), sa.Column("attempts", sa.Integer, nullable=False, server_default="0"), sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW), sa.Column("locked_at", sa.DateTime(timezone=True)), sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW), sa.UniqueConstraint("workspace_id", "idempotency_key"))
    op.create_table("idempotency_records", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("key", sa.String(255), nullable=False), sa.Column("operation", sa.String(255), nullable=False), sa.Column("status", sa.String(32), nullable=False, server_default="in_progress"), sa.Column("response", JSON), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW), sa.UniqueConstraint("workspace_id", "key"))
    op.create_table("credentials", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("name", sa.String(255), nullable=False), sa.Column("provider", sa.String(255), nullable=False), sa.Column("active_version_id", UUID), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW), sa.UniqueConstraint("workspace_id", "name"))
    op.create_table("credential_versions", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("credential_id", UUID, sa.ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False), sa.Column("version", sa.Integer, nullable=False), sa.Column("ciphertext", sa.Text, nullable=False), sa.Column("algorithm", sa.String(64), nullable=False, server_default="fernet-v1"), sa.Column("key_id", sa.String(255)), sa.Column("has_secret", sa.Boolean, nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW), sa.UniqueConstraint("credential_id", "version"))
    op.create_table("credential_bindings", sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")), sa.Column("workspace_id", UUID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False), sa.Column("credential_id", UUID, sa.ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False), sa.Column("binding_key", sa.String(255), nullable=False), sa.Column("constraints", JSON, nullable=False, server_default=EMPTY), sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW), sa.UniqueConstraint("workspace_id", "credential_id", "binding_key"))
    op.create_index("idx_domain_events_cursor", "domain_events", ["workspace_id", "sequence"])
    op.create_index("idx_outbox_pending", "outbox_messages", ["available_at", "locked_at"])
    op.create_index("idx_api_tokens_workspace", "api_tokens", ["workspace_id"])
    op.create_index("idx_audit_events_workspace_created", "audit_events", ["workspace_id", "created_at"])


def downgrade() -> None:
    raise RuntimeError("Foundation migration is intentionally irreversible; restore a database backup instead.")
