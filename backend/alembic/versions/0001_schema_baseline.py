"""Adopt and create the complete application schema.

Revision ID: 0001_schema_baseline
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

revision = "0001_schema_baseline"
down_revision = None
branch_labels = None
depends_on = None


PROBABILITY_SKILL = """Use this skill for questions like \"what is the probability of X happening\", drop-rate odds, at-least-one-event questions, streaks, cumulative probability, expected value, and similar statistical analysis.

Procedure:
1. Clarify the event, trial count, and whether the user asks about future trials, past trials, or total trials. If the question is ambiguous but can be answered with a reasonable interpretation, state the interpretation.
2. Use web/search/fetch tools to find a reliable source for the event rate. Prefer official docs, primary game wikis, published papers, or clearly maintained reference pages. Quote the source and rate used.
3. Convert the rate to a per-trial probability p. For \"1 in N\", p = 1/N.
4. For at least one success in n independent future trials, use 1 - (1 - p)^n. Existing failures do not change the future probability unless there is pity protection, depletion, replacement, changing odds, or another non-independent mechanic.
5. For probability of already having at least one success after k independent trials, use 1 - (1 - p)^k.
6. For probability of first success occurring within the next n trials after k prior failures under independent fixed odds, use 1 - (1 - p)^n; if asked for total by k+n trials, use 1 - (1 - p)^(k+n).
7. Use calculator for all arithmetic and probability calculations instead of mental math. Prefer structured calculator operations: at_least_one for at least one success in n trials, binomial_pmf/binomial_cdf/binomial_at_least for exact or cumulative binomial questions, geometric_pmf/geometric_cdf for first-success questions, poisson_pmf/poisson_cdf for rate events, normal_cdf/z_score for normal-distribution questions, and chi_square_gof/chi_square_independence/chi_square_survival for chi-squared tests. Show formula, substitutions, final percentage or p-value, and a plain-language interpretation.
8. Mention assumptions: independence, constant drop rate, and whether the source rate applies to the user's exact activity.

Example pattern:
If a drop is 1/400 and the user asks for at least one in the next 10 kills, compute 1 - (399/400)^10 = about 2.47%. If they also mention 500 prior kills, explain that under independent fixed odds the prior 500 kills do not affect the next-10 probability, but the chance of having seen at least one by 500 kills is 1 - (399/400)^500 = about 71.4%."""


def _add_missing_columns(bind):
    expected = {
        "threads": {
            "llm_overrides": "JSONB DEFAULT NULL", "is_pinned": "BOOLEAN NOT NULL DEFAULT FALSE",
            "completed_turns": "INTEGER NOT NULL DEFAULT 0", "conversation_summary": "TEXT",
            "conversation_summary_updated_at": "TIMESTAMPTZ",
            "conversation_summary_turn_count": "INTEGER NOT NULL DEFAULT 0",
        },
        "mcp_servers": {"args": "JSONB DEFAULT '{}'::jsonb", "registry_credentials": "JSONB DEFAULT '{}'::jsonb",
                        "cached_tools": "JSONB DEFAULT NULL", "cached_tools_at": "TIMESTAMPTZ"},
        "discord_thread_links": {"indexed_discord_message_id": "VARCHAR(255)", "indexed_at": "TIMESTAMPTZ",
                                  "indexing_status": "VARCHAR(50)", "indexing_error": "TEXT"},
        "discord_server_tool_overrides": {"tool_name": "VARCHAR(255)"},
    }
    for table, columns in expected.items():
        present = {column["name"] for column in inspect(bind).get_columns(table)}
        for name, definition in columns.items():
            if name not in present:
                bind.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}'))


def _validate_known_types(bind):
    expected = {
        ("threads", "id"): {"uuid"}, ("threads", "title"): {"character varying"},
        ("messages", "id"): {"uuid"}, ("messages", "thread_id"): {"uuid"},
        ("messages", "content"): {"text"}, ("mcp_servers", "id"): {"uuid"},
        ("skills", "id"): {"uuid"}, ("generated_media", "content"): {"bytea"},
    }
    for (table, column), allowed in expected.items():
        row = bind.execute(text("""SELECT data_type, udt_name FROM information_schema.columns
                                 WHERE table_schema = current_schema()
                                   AND table_name = :table AND column_name = :column"""),
                           {"table": table, "column": column}).first()
        if row is None:
            raise RuntimeError(f"Alembic baseline could not find expected column {table}.{column}")
        actual = row.udt_name if row.data_type == "USER-DEFINED" else row.data_type
        if actual not in allowed:
            raise RuntimeError(f"Refusing to adopt incompatible {table}.{column} type {actual}; expected {sorted(allowed)}")


def _normalize_message_fk(bind):
    inspector = inspect(bind)
    fks = [fk for fk in inspector.get_foreign_keys("messages")
           if fk["referred_table"] == "threads" and fk["constrained_columns"] == ["thread_id"]]
    if len(fks) == 1:
        fk = fks[0]
        if (fk["name"] == "fk_messages_thread_id_threads"
                and (fk.get("options") or {}).get("ondelete", "").upper() == "CASCADE"):
            return
    for fk in fks:
        if fk["name"]:
            op.drop_constraint(fk["name"], "messages", type_="foreignkey")
    op.create_foreign_key("fk_messages_thread_id_threads", "messages", "threads", ["thread_id"], ["id"], ondelete="CASCADE")


def _normalize_discord_override_constraint(bind):
    constraints = inspect(bind).get_unique_constraints("discord_server_tool_overrides")
    for constraint in constraints:
        if constraint["column_names"] == ["guild_id", "server_id"]:
            op.drop_constraint(constraint["name"], "discord_server_tool_overrides", type_="unique")
    if not any(set(constraint["column_names"]) == {"guild_id", "server_id", "tool_name"} for constraint in constraints):
        op.create_unique_constraint("uq_discord_server_tool_overrides_scope", "discord_server_tool_overrides", ["guild_id", "server_id", "tool_name"])


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
    existing = set(inspect(bind).get_table_names())

    if "threads" not in existing:
        op.create_table("threads", sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("title", sa.String(255), nullable=False, server_default="New Thread"),
            sa.Column("parent_id", sa.UUID(), sa.ForeignKey("threads.id", ondelete="CASCADE")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("llm_overrides", postgresql.JSONB()), sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("completed_turns", sa.Integer(), nullable=False, server_default="0"), sa.Column("conversation_summary", sa.Text()),
            sa.Column("conversation_summary_updated_at", sa.DateTime(timezone=True)), sa.Column("conversation_summary_turn_count", sa.Integer(), nullable=False, server_default="0"))
    if "messages" not in existing:
        op.create_table("messages", sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
            sa.Column("thread_id", sa.UUID(), nullable=False), sa.Column("role", sa.String(50), nullable=False), sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("metadata", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb")),
            sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], name="fk_messages_thread_id_threads", ondelete="CASCADE"))
    if "settings" not in existing:
        op.create_table("settings", sa.Column("key", sa.String(255), primary_key=True), sa.Column("value", sa.Text(), nullable=False))
    if "mcp_servers" not in existing:
        op.create_table("mcp_servers", sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("image", sa.String(255), nullable=False), sa.Column("env_vars", postgresql.JSONB()), sa.Column("args", postgresql.JSONB()), sa.Column("registry_credentials", postgresql.JSONB()), sa.Column("is_active", sa.Boolean(), server_default=sa.true()), sa.Column("cached_tools", postgresql.JSONB()), sa.Column("cached_tools_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    if "generated_images" not in existing:
        op.create_table("generated_images", sa.Column("filename", sa.String(255), primary_key=True), sa.Column("content", sa.LargeBinary(), nullable=False), sa.Column("content_type", sa.String(100), nullable=False, server_default="image/png"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    if "generated_media" not in existing:
        op.create_table("generated_media", sa.Column("filename", sa.String(255), primary_key=True), sa.Column("content", sa.LargeBinary(), nullable=False), sa.Column("content_type", sa.String(100), nullable=False, server_default="video/mp4"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    if "skills" not in existing:
        op.create_table("skills", sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("description", sa.Text(), server_default=""), sa.Column("content", sa.Text(), nullable=False), sa.Column("is_active", sa.Boolean(), server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    if "thread_tool_overrides" not in existing:
        op.create_table("thread_tool_overrides", sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True), sa.Column("thread_id", sa.UUID(), nullable=False), sa.Column("server_id", sa.UUID(), nullable=False), sa.Column("tool_name", sa.String(255)), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"), sa.UniqueConstraint("thread_id", "server_id", "tool_name"))
    if "thread_skill_overrides" not in existing:
        op.create_table("thread_skill_overrides", sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True), sa.Column("thread_id", sa.UUID(), nullable=False), sa.Column("skill_id", sa.UUID(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"), sa.UniqueConstraint("thread_id", "skill_id"))
    if "discord_thread_links" not in existing:
        op.create_table("discord_thread_links", sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True), sa.Column("thread_id", sa.UUID(), nullable=False), sa.Column("guild_id", sa.String(255), nullable=False), sa.Column("channel_id", sa.String(255), nullable=False), sa.Column("discord_thread_id", sa.String(255), nullable=False), sa.Column("discord_thread_name", sa.String(255), nullable=False), sa.Column("last_discord_message_id", sa.String(255)), sa.Column("indexed_discord_message_id", sa.String(255)), sa.Column("indexed_at", sa.DateTime(timezone=True)), sa.Column("indexing_status", sa.String(50)), sa.Column("indexing_error", sa.Text()), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"), sa.UniqueConstraint("thread_id"), sa.UniqueConstraint("discord_thread_id"))
    if "discord_servers" not in existing:
        op.create_table("discord_servers", sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True), sa.Column("guild_id", sa.String(255), nullable=False), sa.Column("guild_name", sa.String(255), nullable=False), sa.Column("default_channel_id", sa.String(255)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")), sa.UniqueConstraint("guild_id"))
    if "discord_server_tool_overrides" not in existing:
        op.create_table("discord_server_tool_overrides", sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), primary_key=True), sa.Column("guild_id", sa.String(255), nullable=False), sa.Column("server_id", sa.UUID(), nullable=False), sa.Column("tool_name", sa.String(255)), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()), sa.ForeignKeyConstraint(["guild_id"], ["discord_servers.guild_id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["server_id"], ["mcp_servers.id"], ondelete="CASCADE"), sa.UniqueConstraint("guild_id", "server_id", "tool_name", name="uq_discord_server_tool_overrides_scope"))

    _add_missing_columns(bind)
    _validate_known_types(bind)
    if "messages" in existing:
        _normalize_message_fk(bind)
    if "discord_server_tool_overrides" in existing:
        _normalize_discord_override_constraint(bind)
    bind.execute(text("""INSERT INTO discord_servers (id, guild_id, guild_name)
                         SELECT gen_random_uuid(), linked.guild_id, linked.guild_id
                         FROM (SELECT DISTINCT guild_id FROM discord_thread_links) linked
                         ON CONFLICT (guild_id) DO NOTHING"""))
    indexes = [("messages", "idx_messages_thread_id", "thread_id"), ("messages", "idx_messages_created_at", "created_at"), ("threads", "idx_threads_parent_id", "parent_id"), ("thread_tool_overrides", "idx_thread_tool_overrides_thread_id", "thread_id"), ("thread_skill_overrides", "idx_thread_skill_overrides_thread_id", "thread_id"), ("discord_thread_links", "idx_discord_thread_links_thread_id", "thread_id"), ("discord_thread_links", "idx_discord_thread_links_discord_thread_id", "discord_thread_id"), ("discord_servers", "idx_discord_servers_guild_id", "guild_id"), ("discord_server_tool_overrides", "idx_discord_server_tool_overrides_guild_id", "guild_id")]
    for table, name, column in indexes:
        bind.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ("{column}")'))
    bind.execute(text('CREATE INDEX IF NOT EXISTS "idx_threads_created_at" ON "threads" ("created_at" DESC)'))
    bind.execute(text("""INSERT INTO skills (name, description, content, is_active)
                       SELECT :name, :description, :content, TRUE
                       WHERE NOT EXISTS (SELECT 1 FROM skills WHERE lower(name) = lower(CAST(:name AS VARCHAR(255))))"""),
                 {"name": "Statistical probability analysis", "description": "Research event rates online and calculate probabilities, odds, and dry-streak questions.", "content": PROBABILITY_SKILL})


def downgrade() -> None:
    raise RuntimeError("The application baseline is intentionally irreversible; restore a database backup instead.")
