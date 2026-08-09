"""Add persistent per-tool MCP safety overrides."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0027_mcp_tool_safety_overrides"
down_revision = "0026_thread_approval_presets"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("mcp_servers")}
    if "tool_safety_overrides" not in columns:
        op.add_column(
            "mcp_servers",
            sa.Column(
                "tool_safety_overrides",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade():
    raise RuntimeError("MCP tool safety override migration is forward-only")
