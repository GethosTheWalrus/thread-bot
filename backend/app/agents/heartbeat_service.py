"""Adaptive agent heartbeat supervision service.

This is the desired-state authority.  PostgreSQL is the source of truth; the
Temporal workflow is the durable wake scheduler.  All API mutations commit the
desired state before best-effort signaling the workflow so a Temporal failure
never loses the operator's intent.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from uuid import UUID
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent_models import Agent, AgentHeartbeat
from app.models.models import Thread
from app.config import load_settings_from_db
from app.security import autonomy_flags, security_mode


def _now() -> datetime:
    return datetime.now(timezone.utc)


def classify_heartbeat_result(
    status: str | None, output_summary: str | None, successful_actions: int
) -> tuple[str, str]:
    actual_status = status or "failed"
    if actual_status != "succeeded":
        return actual_status, "no_op"
    if successful_actions:
        return actual_status, "action"
    if (output_summary or "").strip():
        return actual_status, "response"
    return actual_status, "no_op"


def _clamped(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


async def _ensure_heartbeat_row(db: AsyncSession, agent: Agent) -> AgentHeartbeat:
    row = await db.get(AgentHeartbeat, agent.id)
    if row is None:
        row = AgentHeartbeat(
            agent_id=agent.id,
            workspace_id=agent.workspace_id,
            thread_id=agent.thread_id,
            enabled=False,
        )
        db.add(row)
        await db.flush()
    return row


def _resolve_status(row: AgentHeartbeat, agent: Agent, thread: Thread | None) -> str:
    """Compute the operational status from current agent/thread/global state."""
    if not row.enabled:
        return "disabled"
    flags = autonomy_flags()
    if not flags.get("autonomy_enabled", False):
        return "blocked_global"
    if agent.status == "archived":
        return "blocked_archived"
    if agent.status == "paused":
        return "paused"
    if thread is not None and thread.mode != "agent":
        return "blocked_mode"
    return "scheduled"


def _compute_next_wake(
    row: AgentHeartbeat,
    decision: str | None,
    requested_interval: int | None,
    *,
    now: datetime | None = None,
) -> datetime | None:
    if not row.enabled:
        return None
    now = now or _now()
    min_wake = int(row.min_wake_seconds)
    max_wake = int(row.max_wake_seconds)
    backoff = float(row.idle_backoff_factor or Decimal("2.0"))
    requested = _clamped(int(requested_interval or min_wake), min_wake, max_wake)
    if decision == "no_op":
        noops = int(row.consecutive_noops or 0) + 1
        idle_floor = min(max_wake, int(min_wake * (backoff ** noops)))
        delay = max(requested, idle_floor)
    elif decision is None:
        # Initial scheduling or after an error: use min wake.
        delay = min_wake
    else:
        delay = requested
    return now + timedelta(seconds=delay)


async def upsert_heartbeat_config(
    db: AsyncSession,
    agent: Agent,
    *,
    enabled: bool,
    min_wake_seconds: int,
    max_wake_seconds: int,
    idle_backoff_factor: float,
    expected_revision: int | None,
) -> AgentHeartbeat:
    await load_settings_from_db()
    row = await _ensure_heartbeat_row(db, agent)
    if expected_revision is not None and row.revision != expected_revision:
        from fastapi import HTTPException
        raise HTTPException(409, "heartbeat revision conflict")
    row.enabled = enabled
    row.min_wake_seconds = _clamped(min_wake_seconds, 30, 86400)
    row.max_wake_seconds = _clamped(max_wake_seconds, 30, 604800)
    if row.max_wake_seconds < row.min_wake_seconds:
        row.max_wake_seconds = row.min_wake_seconds
    row.idle_backoff_factor = max(1.0, min(10.0, float(idle_backoff_factor)))
    row.revision = int(row.revision or 1) + 1
    row.last_error = None
    thread = await db.get(Thread, agent.thread_id)
    row.operational_status = _resolve_status(row, agent, thread)
    if row.operational_status == "scheduled":
        # Reset idle count on configuration change so a fresh enablement uses
        # the configured min wake rather than a backoff floor.
        row.consecutive_noops = 0
        row.next_wake_at = _compute_next_wake(row, None, None)
    else:
        row.next_wake_at = None
    await db.flush()
    return row


async def materialize_heartbeat_run(
    db: AsyncSession, agent_id: UUID
) -> dict:
    """Create the heartbeat trigger event + agent run transactionally.

    Never creates or mutates a Message.  Idempotent on the scheduled wake.
    Returns the new run id and event id.
    """
    from uuid import uuid4
    from app.models.agent_models import AgentVersion, TriggerEvent
    from app.models.run_models import AgentRun
    from app.database.autonomy import create_trigger_event, append_run_event
    from app.agents.autonomy_service import _now as _svc_now

    agent = await db.get(Agent, agent_id)
    if agent is None or agent.status != "active" or not agent.active_version_id:
        return {"created": False, "reason": "agent unavailable"}
    row = await _ensure_heartbeat_row(db, agent)
    thread = await db.get(Thread, agent.thread_id)
    status = _resolve_status(row, agent, thread)
    if status not in {"scheduled", "evaluating"}:
        row.operational_status = status
        await db.flush()
        return {"created": False, "reason": status}
    version = await db.get(AgentVersion, agent.active_version_id)
    if version is None:
        return {"created": False, "reason": "no active version"}
    scheduled_wake = row.next_wake_at or _svc_now()
    dedupe_key = f"heartbeat:{agent.id}:{scheduled_wake.isoformat()}"
    event, created = await create_trigger_event(
        db,
        id=uuid4(),
        workspace_id=agent.workspace_id,
        agent_id=agent.id,
        trigger_id=None,
        schema_version=1,
        source="heartbeat",
        event_type="heartbeat.wake",
        subject={},
        occurred_at=scheduled_wake,
        dedupe_key=dedupe_key,
        correlation_id=uuid4(),
        causation_id=None,
        origin_chain=[],
        trust="trusted_metadata",
        payload={"scheduled_at": scheduled_wake.isoformat(), "route": "heartbeat"},
        content_refs=[],
    )
    run_id = None
    if created:
        run = AgentRun(
            workspace_id=agent.workspace_id,
            agent_id=agent.id,
            agent_version_id=version.id,
            thread_id=agent.thread_id,
            trigger_event_id=event.id,
            correlation_id=event.correlation_id,
            mode="live",
            route="heartbeat",
        )
        db.add(run)
        await db.flush()
        run_id = run.id
        await append_run_event(db, run.id, "run_queued", {"source": "heartbeat"})
    else:
        existing = await db.scalar(
            select(AgentRun).where(AgentRun.trigger_event_id == event.id)
        )
        if existing:
            run_id = existing.id
    row.operational_status = "evaluating"
    row.last_wake_at = _svc_now()
    row.next_wake_at = None
    if run_id is not None:
        row.last_run_id = run_id
    await db.flush()
    return {
        "created": bool(run_id),
        "run_id": str(run_id) if run_id else None,
        "event_id": str(event.id),
        "thread_id": str(agent.thread_id),
        "workspace_id": str(agent.workspace_id),
    }


async def complete_heartbeat_run(
    db: AsyncSession,
    agent_id: UUID,
    run_id: UUID,
    *,
    decision: str | None,
    requested_next_wake: int | None,
    status: str | None,
    error: str | None = None,
) -> dict:
    """Persist the post-run state and compute the next wake.

    Called for every terminal state (success, failure, suppression, etc.).
    The server clamps the requested interval and applies idle backoff.
    """
    from app.models.run_models import AgentAction, AgentRun

    agent = await db.get(Agent, agent_id)
    if agent is None:
        return {"updated": False}
    row = await _ensure_heartbeat_row(db, agent)
    now = _now()
    run = await db.get(AgentRun, run_id)
    actual_status = run.status if run else status
    if decision is None:
        action_count = await db.scalar(
            select(func.count(AgentAction.id)).where(
                AgentAction.run_id == run_id,
                AgentAction.status.in_(["succeeded", "reconciled_succeeded"]),
            )
        )
        actual_status, decision = classify_heartbeat_result(
            actual_status,
            run.output_summary if run else None,
            int(action_count or 0),
        )
    row.last_completed_at = now
    row.last_decision = decision
    if actual_status != "succeeded":
        row.operational_status = "error"
        row.last_error = error or (run.failure_summary if run else None) or f"run {actual_status or 'failed'}"
        # Failure uses bounded backoff so we don't spin.
        noops = int(row.consecutive_noops or 0) + 1
        row.consecutive_noops = noops
        row.next_wake_at = _compute_next_wake(row, "no_op", requested_next_wake, now=now)
    elif decision == "no_op":
        row.last_error = None
        row.consecutive_noops = int(row.consecutive_noops or 0) + 1
        row.operational_status = "scheduled"
        row.next_wake_at = _compute_next_wake(row, "no_op", requested_next_wake, now=now)
    else:
        row.consecutive_noops = 0
        row.operational_status = "scheduled"
        row.last_error = None
        row.next_wake_at = _compute_next_wake(row, decision, requested_next_wake, now=now)
    await db.flush()
    return {
        "updated": True,
        "next_wake_at": row.next_wake_at.isoformat() if row.next_wake_at else None,
        "operational_status": row.operational_status,
    }


async def load_heartbeat_state(db: AsyncSession, agent_id: UUID) -> dict | None:
    agent = await db.get(Agent, agent_id)
    if agent is None:
        return None
    row = await _ensure_heartbeat_row(db, agent)
    thread = await db.get(Thread, agent.thread_id)
    return {
        "agent_id": str(agent.id),
        "workspace_id": str(agent.workspace_id),
        "thread_id": str(agent.thread_id),
        "enabled": bool(row.enabled),
        "min_wake_seconds": int(row.min_wake_seconds),
        "max_wake_seconds": int(row.max_wake_seconds),
        "idle_backoff_factor": float(row.idle_backoff_factor or Decimal("2.0")),
        "revision": int(row.revision or 1),
        "operational_status": row.operational_status,
        "workflow_id": row.workflow_id,
        "last_wake_at": row.last_wake_at.isoformat() if row.last_wake_at else None,
        "last_completed_at": row.last_completed_at.isoformat() if row.last_completed_at else None,
        "next_wake_at": row.next_wake_at.isoformat() if row.next_wake_at else None,
        "last_decision": row.last_decision,
        "last_run_id": str(row.last_run_id) if row.last_run_id else None,
        "consecutive_noops": int(row.consecutive_noops or 0),
        "last_error": row.last_error,
        "agent_status": agent.status,
        "thread_mode": thread.mode if thread else None,
    }


async def list_enabled_heartbeats(db: AsyncSession, workspace_id: UUID | None = None) -> list[AgentHeartbeat]:
    q = select(AgentHeartbeat).where(AgentHeartbeat.enabled.is_(True))
    if workspace_id is not None:
        q = q.where(AgentHeartbeat.workspace_id == workspace_id)
    return list((await db.execute(q)).scalars().all())


def heartbeat_workflow_id(agent_id: UUID) -> str:
    return f"agent-heartbeat:{agent_id}"
