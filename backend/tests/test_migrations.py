from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.models.models import Base
from app.models import foundation_models, runtime_models, approval_models, run_models  # noqa: F401


ROOT = Path(__file__).parents[1]


def test_alembic_has_one_linear_head():
    config = Config(str(ROOT / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0028_osrs_dps_skill"]
    assert scripts.get_revision("0001_schema_baseline").down_revision is None
    assert scripts.get_revision("0002_require_created_timestamps").down_revision == "0001_schema_baseline"
    assert scripts.get_revision("0003_foundation").down_revision == "0002_require_created_timestamps"
    assert scripts.get_revision("0004_foundation").down_revision == "0003_foundation"
    assert scripts.get_revision("0005_agents_core").down_revision == "0004_foundation"
    assert scripts.get_revision("0006_core_foreign_keys").down_revision == "0005_agents_core"
    assert scripts.get_revision("0007_runtime_config_snapshots").down_revision == "0006_core_foreign_keys"
    assert scripts.get_revision("0008_approvals_and_simulation").down_revision == "0007_runtime_config_snapshots"
    assert scripts.get_revision("0009_phase2_control_plane").down_revision == "0008_approvals_and_simulation"
    assert scripts.get_revision("0010_phase2_replay_and_routes").down_revision == "0009_phase2_control_plane"
    assert scripts.get_revision("0011_credential_fk_approval").down_revision == "0010_phase2_replay_and_routes"
    assert scripts.get_revision("0012_phase3").down_revision == "0011_credential_fk_approval"
    assert scripts.get_revision("0013_phase3_constraints").down_revision == "0012_phase3"
    assert scripts.get_revision("0014_phase3_contract_lifecycle").down_revision == "0013_phase3_constraints"
    assert scripts.get_revision("0015_phase4_replay_rollout_observability").down_revision == "0014_phase3_contract_lifecycle"
    assert scripts.get_revision("0016_phase4_canary_assignment_workspace").down_revision == "0015_phase4_replay_rollout_observability"
    assert scripts.get_revision("0017_slo_metrics").down_revision == "0016_phase4_canary_assignment_workspace"
    assert scripts.get_revision("0018_notification_claim_leases").down_revision == "0017_slo_metrics"
    assert scripts.get_revision("0019_thread_modes").down_revision == "0018_notification_claim_leases"
    assert scripts.get_revision("0020_multi_agent_threads").down_revision == "0019_thread_modes"
    assert scripts.get_revision("0021_reconcile_multi_agent_schema").down_revision == "0020_multi_agent_threads"
    assert scripts.get_revision("0022_agent_heartbeats").down_revision == "0021_reconcile_multi_agent_schema"
    assert scripts.get_revision("0023_backfill_thread_workspaces").down_revision == "0022_agent_heartbeats"
    assert scripts.get_revision("0024_system_moderators").down_revision == "0023_backfill_thread_workspaces"
    assert scripts.get_revision("0025_discord_approval_prompts").down_revision == "0024_system_moderators"
    assert scripts.get_revision("0026_thread_approval_presets").down_revision == "0025_discord_approval_prompts"
    assert scripts.get_revision("0027_mcp_tool_safety_overrides").down_revision == "0026_thread_approval_presets"
    assert scripts.get_revision("0028_osrs_dps_skill").down_revision == "0027_mcp_tool_safety_overrides"


def test_phase4_revision_widens_alembic_version_before_stamping():
    revision = (ROOT / "alembic/versions/0015_phase4_replay_rollout_observability.py").read_text()
    assert revision.index('"alembic_version"') < revision.index('op.create_table("replay_sessions"')
    assert "length=255" in revision


def test_baseline_contains_runtime_schema_and_reconciliation():
    revision = (ROOT / "alembic/versions/0001_schema_baseline.py").read_text()
    for expected in (
        "generated_media",
        "discord_thread_links",
        "discord_servers",
        "discord_server_tool_overrides",
        "cached_tools_at",
        "conversation_summary_turn_count",
        "PROBABILITY_SKILL",
        'ondelete="CASCADE"',
        "lower(name) = lower(CAST(:name AS VARCHAR(255)))",
        "metadata",
    ):
        assert expected in revision


def test_application_startup_only_checks_migration_head():
    source = (ROOT / "app/database/__init__.py").read_text()
    assert "create_all" not in source
    assert "MigrationContext" in source
    assert "alembic upgrade head" in source


def test_model_metadata_declares_baseline_indexes_and_constraint():
    expected_indexes = {
        "idx_messages_thread_id", "idx_messages_created_at", "idx_threads_parent_id",
        "idx_threads_created_at", "idx_thread_tool_overrides_thread_id",
        "idx_thread_skill_overrides_thread_id", "idx_discord_thread_links_thread_id",
        "idx_discord_thread_links_discord_thread_id", "idx_discord_servers_guild_id",
        "idx_discord_server_tool_overrides_guild_id",
    }
    actual_indexes = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert expected_indexes <= actual_indexes
    constraint = next(
        constraint for constraint in Base.metadata.tables["discord_server_tool_overrides"].constraints
        if constraint.name == "uq_discord_server_tool_overrides_scope"
    )
    assert {column.name for column in constraint.columns} == {"guild_id", "server_id", "tool_name"}
    assert str(Base.metadata.tables["messages"].c.metadata.server_default.arg) == "'{}'::jsonb"


def test_multi_agent_reconciliation_declares_expected_indexes_and_repairs_route():
    expected_indexes = {
        "idx_agent_runs_parent_root", "idx_agent_runs_thread_route",
        "idx_messages_agent_handle", "idx_messages_agent_run",
        "idx_threads_workspace_updated",
    }
    actual_indexes = {index.name for table in Base.metadata.tables.values() for index in table.indexes}
    assert expected_indexes <= actual_indexes
    revision = (ROOT / "alembic/versions/0021_reconcile_multi_agent_schema.py").read_text()
    assert "UPDATE agent_runs SET route = 'user' WHERE route IS NULL" in revision
    assert "ALTER COLUMN route SET NOT NULL" in revision
    assert "get_unique_constraints(\"agents\")" in revision


def test_thread_workspace_revision_backfills_before_not_null():
    revision = (ROOT / "alembic/versions/0023_backfill_thread_workspaces.py").read_text()
    assert revision.index("UPDATE threads SET workspace_id") < revision.index("nullable=False")
    assert "00000000-0000-0000-0000-000000000001" in revision
    assert 'RuntimeError("Thread workspace ownership migration is forward-only")' in revision
    assert not Base.metadata.tables["threads"].c.workspace_id.nullable


def test_system_moderator_revision_backfills_and_matches_model():
    revision = (ROOT / "alembic/versions/0024_system_moderators.py").read_text()
    assert "UPDATE agents SET is_moderator = false" in revision
    assert "'Thread moderator', 'moderator'" in revision
    assert "'active', 'act', true, true" in revision
    assert "uq_agents_system_thread" in revision
    assert "ck_agents_system_is_moderator" in revision
    assert 'RuntimeError("System moderator migration is forward-only")' in revision
    assert not Base.metadata.tables["agents"].c.is_system.nullable


def test_discord_approval_prompt_revision_and_model_match():
    revision = (ROOT / "alembic/versions/0025_discord_approval_prompts.py").read_text()
    assert "approval_provider_prompts" in revision
    assert "uq_approval_provider_prompt_message" in revision
    assert "idx_approval_provider_prompts_request" in revision
    assert 'RuntimeError("Discord approval prompt migration is forward-only")' in revision
    table = Base.metadata.tables["approval_provider_prompts"]
    assert {"request_id", "provider_channel_id", "provider_message_id", "intended_actor_id"} <= set(table.columns.keys())


def test_thread_approval_preset_revision_and_model_match():
    revision = (ROOT / "alembic/versions/0026_thread_approval_presets.py").read_text()
    assert "approval_preset" in revision
    assert "ck_threads_approval_preset" in revision
    assert 'RuntimeError("Thread approval preset migration is forward-only")' in revision
    column = Base.metadata.tables["threads"].c.approval_preset
    assert not column.nullable
    assert str(column.server_default.arg) == "effectful"


def test_mcp_tool_safety_override_revision_and_model_match():
    revision = (ROOT / "alembic/versions/0027_mcp_tool_safety_overrides.py").read_text()
    assert "tool_safety_overrides" in revision
    assert 'RuntimeError("MCP tool safety override migration is forward-only")' in revision
    column = Base.metadata.tables["mcp_servers"].c.tool_safety_overrides
    assert not column.nullable
    assert str(column.server_default.arg) == "'{}'::jsonb"


def test_osrs_dps_skill_revision_is_idempotent_and_tool_driven():
    revision = (ROOT / "alembic/versions/0028_osrs_dps_skill.py").read_text()
    for expected in (
        "OSRS_DPS_SKILL",
        "OSRS DPS calculation",
        "use_skill",
        "hydrate_player",
        "compute_basic",
        "engine_info",
        "WHERE NOT EXISTS",
    ):
        assert expected in revision
    assert 'RuntimeError("OSRS DPS skill migration is forward-only")' in revision


def test_timestamp_revision_backfills_before_not_null_and_is_non_destructive():
    revision = (ROOT / "alembic/versions/0002_require_created_timestamps.py").read_text()
    for table in ("discord_servers", "generated_images", "generated_media", "skills"):
        assert table in revision
    assert "COALESCE(created_at, updated_at, NOW())" in revision
    assert "WHERE created_at IS NULL" in revision
    assert "nullable=False" in revision
    assert "restore a database backup" in revision


def test_foundation_index_and_outbox_model_parity():
    revision = (ROOT / "alembic/versions/0004_foundation.py").read_text()
    assert '"idx_principals_workspace"' in revision
    assert "outbox_messages" in revision
    assert {index.name for index in Base.metadata.tables["principals"].indexes} >= {"idx_principals_workspace"}
    outbox = Base.metadata.tables["outbox_messages"]
    assert {"status", "claimed_by", "last_error", "failed_at"} <= set(outbox.columns.keys())


def test_autonomy_core_reference_revision_is_forward_only():
    revision = (ROOT / "alembic/versions/0006_core_foreign_keys.py").read_text()
    for expected in (
        "fk_agents_active_version_id_agent_versions",
        "fk_agent_versions_policy_set_id_policy_sets",
        "fk_agent_versions_budget_profile_id_budget_profiles",
        "fk_policy_sets_active_version_id_policy_versions",
        "state_before_artifact_id",
        "state_after_artifact_id",
        "state_diff_artifact_id",
    ):
        assert expected in revision
    assert "restore a database backup" in revision
