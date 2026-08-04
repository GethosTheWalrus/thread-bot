"""Backfill and require application creation timestamps.

Revision ID: 0002_require_created_timestamps
Revises: 0001_schema_baseline
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_require_created_timestamps"
down_revision = "0001_schema_baseline"
branch_labels = None
depends_on = None


def _backfill_timestamp_pair(table: str) -> None:
    op.execute(sa.text(f"""
        UPDATE {table}
        SET created_at = COALESCE(created_at, updated_at, NOW()),
            updated_at = COALESCE(updated_at, created_at, NOW())
        WHERE created_at IS NULL OR updated_at IS NULL
    """))


def upgrade() -> None:
    _backfill_timestamp_pair("discord_servers")
    for table in ("generated_images", "generated_media", "skills"):
        op.execute(sa.text(f"UPDATE {table} SET created_at = NOW() WHERE created_at IS NULL"))

    for table in ("discord_servers", "generated_images", "generated_media", "skills"):
        op.alter_column(table, "created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    op.alter_column("discord_servers", "updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)


def downgrade() -> None:
    raise RuntimeError("Timestamp constraints are intentionally irreversible; restore a database backup instead.")
