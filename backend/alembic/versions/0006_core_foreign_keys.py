"""Enforce deferred autonomy-core references.

Revision ID: 0006_core_foreign_keys
Revises: 0005_agents_core
"""

from alembic import op
from sqlalchemy import inspect


revision = "0006_core_foreign_keys"
down_revision = "0005_agents_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    # 0005 was deployed both with PostgreSQL-generated names and with explicit
    # names.  Rename matching constraints when possible; never drop a useful
    # uniqueness constraint just because its name differs.
    for table, columns, desired in (
        ("agent_versions", ["agent_id", "version"], "uq_agent_versions_agent_version"),
        ("agent_versions", ["agent_id", "config_hash"], "uq_agent_versions_config_hash"),
    ):
        uniques = inspector.get_unique_constraints(table)
        if any(item["name"] == desired for item in uniques):
            continue
        match = next((item["name"] for item in uniques if item["column_names"] == columns), None)
        if match:
            bind.exec_driver_sql(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{match}" TO "{desired}"')
        else:
            op.create_unique_constraint(desired, table, columns)

    for name, table, referred, columns in (
        ("fk_agents_active_version_id_agent_versions", "agents", "agent_versions", ["active_version_id"]),
        ("fk_agent_versions_policy_set_id_policy_sets", "agent_versions", "policy_sets", ["policy_set_id"]),
        ("fk_agent_versions_budget_profile_id_budget_profiles", "agent_versions", "budget_profiles", ["budget_profile_id"]),
        ("fk_policy_sets_active_version_id_policy_versions", "policy_sets", "policy_versions", ["active_version_id"]),
    ):
        if not any(set(f["constrained_columns"]) == set(columns) and f["referred_table"] == referred for f in inspect(bind).get_foreign_keys(table)):
            op.create_foreign_key(name, table, referred, columns, ["id"], ondelete="SET NULL")
    for column in (
        "state_before_artifact_id",
        "state_after_artifact_id",
        "state_diff_artifact_id",
    ):
        if not any(column in f["constrained_columns"] and f["referred_table"] == "artifacts" for f in inspect(bind).get_foreign_keys("agent_runs")):
            op.create_foreign_key(f"fk_agent_runs_{column}_artifacts", "agent_runs", "artifacts", [column], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    raise RuntimeError(
        "Autonomy migrations are forward-only; restore a database backup to downgrade."
    )
