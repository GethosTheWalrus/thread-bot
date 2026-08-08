"""Correlate Discord reply prompts with durable approval requests."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0025_discord_approval_prompts"
down_revision = "0024_system_moderators"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "approval_provider_prompts" not in inspector.get_table_names():
        op.create_table(
            "approval_provider_prompts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "request_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("approval_requests.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("channel", sa.String(32), nullable=False, server_default="discord"),
            sa.Column("provider_channel_id", sa.String(255), nullable=False),
            sa.Column("provider_message_id", sa.String(255), nullable=False),
            sa.Column("intended_actor_id", sa.String(255)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint(
                "channel",
                "provider_channel_id",
                "provider_message_id",
                name="uq_approval_provider_prompt_message",
            ),
        )
        op.create_index(
            "idx_approval_provider_prompts_request",
            "approval_provider_prompts",
            ["request_id", "created_at"],
        )


def downgrade():
    raise RuntimeError("Discord approval prompt migration is forward-only")
