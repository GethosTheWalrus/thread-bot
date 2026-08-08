"""Add understandable per-Thread approval presets."""

from alembic import op
import sqlalchemy as sa


revision = "0026_thread_approval_presets"
down_revision = "0025_discord_approval_prompts"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("threads")}
    if "approval_preset" not in columns:
        op.add_column(
            "threads",
            sa.Column(
                "approval_preset",
                sa.String(16),
                nullable=False,
                server_default="effectful",
            ),
        )
    checks = {constraint["name"] for constraint in inspector.get_check_constraints("threads")}
    if "ck_threads_approval_preset" not in checks:
        op.create_check_constraint(
            "ck_threads_approval_preset",
            "threads",
            "approval_preset IN ('all', 'effectful', 'never')",
        )


def downgrade():
    raise RuntimeError("Thread approval preset migration is forward-only")
