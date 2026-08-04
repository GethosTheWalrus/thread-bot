"""Focused tests for the adaptive agent heartbeat service and contracts."""
from datetime import timezone
from uuid import uuid4

import pytest

from app.contracts.autonomy import (
    HeartbeatConfigUpsert,
    HeartbeatDecision,
    HeartbeatOperationalStatus,
    HeartbeatResponse,
)


def test_heartbeat_config_upsert_validates_min_max():
    with pytest.raises(Exception):
        HeartbeatConfigUpsert(enabled=True, min_wake_seconds=100, max_wake_seconds=50, idle_backoff_factor=2.0)


def test_heartbeat_config_upsert_clamps_ranges():
    # Below min allowed (30) should fail
    with pytest.raises(Exception):
        HeartbeatConfigUpsert(enabled=True, min_wake_seconds=10, max_wake_seconds=100, idle_backoff_factor=2.0)
    # Above max allowed (86400 for min, 604800 for max) should fail
    with pytest.raises(Exception):
        HeartbeatConfigUpsert(enabled=True, min_wake_seconds=30, max_wake_seconds=999999, idle_backoff_factor=2.0)


def test_heartbeat_config_upsert_backoff_range():
    with pytest.raises(Exception):
        HeartbeatConfigUpsert(enabled=True, min_wake_seconds=30, max_wake_seconds=60, idle_backoff_factor=0.5)
    with pytest.raises(Exception):
        HeartbeatConfigUpsert(enabled=True, min_wake_seconds=30, max_wake_seconds=60, idle_backoff_factor=11.0)


def test_heartbeat_decision_enum_values():
    assert HeartbeatDecision.response == "response"
    assert HeartbeatDecision.action == "action"
    assert HeartbeatDecision.delegate == "delegate"
    assert HeartbeatDecision.no_op == "no_op"


def test_heartbeat_operational_status_enum_values():
    assert HeartbeatOperationalStatus.disabled == "disabled"
    assert HeartbeatOperationalStatus.scheduled == "scheduled"
    assert HeartbeatOperationalStatus.evaluating == "evaluating"
    assert HeartbeatOperationalStatus.blocked_global == "blocked_global"


def test_heartbeat_response_model_round_trips():
    row = HeartbeatResponse(
        agent_id=uuid4(),
        enabled=True,
        min_wake_seconds=300,
        max_wake_seconds=3600,
        idle_backoff_factor=2.0,
        revision=1,
        operational_status=HeartbeatOperationalStatus.scheduled,
        consecutive_noops=0,
        updated_at=__import__("datetime").datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    dumped = row.model_dump(mode="json")
    restored = HeartbeatResponse.model_validate(dumped)
    assert restored.enabled is True
    assert restored.min_wake_seconds == 300
    assert restored.operational_status == HeartbeatOperationalStatus.scheduled


def test_heartbeat_workflow_id_is_stable():
    from app.agents.heartbeat_service import heartbeat_workflow_id
    agent_id = uuid4()
    assert heartbeat_workflow_id(agent_id) == f"agent-heartbeat:{agent_id}"


def test_heartbeat_result_uses_the_persisted_run_outcome():
    from app.agents.heartbeat_service import classify_heartbeat_result

    assert classify_heartbeat_result("succeeded", "", 0) == ("succeeded", "no_op")
    assert classify_heartbeat_result("succeeded", "Daily report", 0) == ("succeeded", "response")
    assert classify_heartbeat_result("succeeded", "", 1) == ("succeeded", "action")
    assert classify_heartbeat_result("failed", "partial", 1) == ("failed", "no_op")


def test_heartbeat_migration_0022_is_forward_only_and_adds_table():
    from pathlib import Path
    revision = (Path(__file__).parents[1] / "alembic/versions/0022_agent_heartbeats.py").read_text()
    assert "agent_heartbeats" in revision
    assert "down_revision = \"0021_reconcile_multi_agent_schema\"" in revision
    assert "RuntimeError" in revision


def test_heartbeat_model_declares_constraints_and_indexes():
    from app.models.agent_models import AgentHeartbeat
    index_names = {idx.name for idx in AgentHeartbeat.__table_args__ if hasattr(idx, "name")}
    constraint_names = {c.name for c in AgentHeartbeat.__table_args__ if hasattr(c, "name")}
    assert "idx_agent_heartbeats_status_wake" in index_names
    assert "idx_agent_heartbeats_thread_enabled" in index_names
    assert "ck_agent_heartbeats_min_wake" in constraint_names
    assert "ck_agent_heartbeats_max_wake" in constraint_names
    assert "ck_agent_heartbeats_min_le_max" in constraint_names
    assert "ck_agent_heartbeats_backoff" in constraint_names
    assert "ck_agent_heartbeats_status" in constraint_names
    assert "ck_agent_heartbeats_decision" in constraint_names
    # Primary key is agent_id
    pk_cols = {col.name for col in AgentHeartbeat.__table__.primary_key.columns}
    assert pk_cols == {"agent_id"}
