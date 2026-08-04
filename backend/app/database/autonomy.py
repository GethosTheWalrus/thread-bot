from datetime import datetime, timezone
from uuid import UUID, uuid4
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.run_models import AgentRun, AgentAction, AgentRunEvent
from app.models.agent_models import TriggerEvent

RUN_TRANSITIONS = {
    "queued": {"running", "cancelled", "suppressed", "dead_lettered"},
    "running": {"waiting_approval", "waiting_handoff", "succeeded", "exhausted", "timed_out", "cancelled", "failed", "dead_lettered", "outcome_unknown"},
    "waiting_approval": {"running", "cancelled", "timed_out", "failed"},
    "waiting_handoff": {"running", "timed_out", "cancelled", "failed"},
}
ACTION_TRANSITIONS = {
    "planned": {"policy_denied", "awaiting_approval", "authorized", "simulated", "cancelled"},
    "awaiting_approval": {"authorized", "denied", "expired", "cancelled"},
    "authorized": {"executing", "cancelled"}, "executing": {"succeeded", "failed", "outcome_unknown"},
    "outcome_unknown": {"reconciled_succeeded", "reconciled_failed", "operator_closed"},
}

async def transition_run(db: AsyncSession, run_id: UUID, expected: str, target: str) -> bool:
    if target not in RUN_TRANSITIONS.get(expected, set()): return False
    values = {"status": target}
    if target == "running": values["started_at"] = datetime.now(timezone.utc)
    if target in {"succeeded", "exhausted", "timed_out", "cancelled", "failed", "suppressed", "dead_lettered", "outcome_unknown"}:
        values["completed_at"] = datetime.now(timezone.utc)
    result = await db.execute(update(AgentRun).where(AgentRun.id == run_id, AgentRun.status == expected).values(**values))
    return result.rowcount == 1

async def transition_action(db: AsyncSession, action_id: UUID, expected: str, target: str) -> bool:
    if target not in ACTION_TRANSITIONS.get(expected, set()): return False
    result = await db.execute(update(AgentAction).where(AgentAction.id == action_id, AgentAction.status == expected).values(status=target, updated_at=datetime.now(timezone.utc)))
    return result.rowcount == 1

async def acquire_thread_lease(db: AsyncSession, workspace_id: UUID, thread_id: UUID, run_id: UUID | None, holder: str, expires_at, execution_type: str = "agent_run", execution_id: str | None = None) -> bool:
    from app.models.run_models import ThreadExecutionLease
    existing = await db.scalar(select(ThreadExecutionLease).where(ThreadExecutionLease.thread_id == thread_id).with_for_update())
    if existing and existing.expires_at > datetime.now(timezone.utc) and (existing.run_id != run_id or existing.execution_id != execution_id):
        return False
    if existing:
        existing.run_id = run_id; existing.execution_type = execution_type; existing.execution_id = execution_id; existing.holder = holder; existing.expires_at = expires_at
    else:
        db.add(ThreadExecutionLease(workspace_id=workspace_id, thread_id=thread_id, run_id=run_id, execution_type=execution_type, execution_id=execution_id, holder=holder, expires_at=expires_at))
    await db.flush(); return True

async def release_thread_lease(db: AsyncSession, thread_id: UUID, run_id: UUID) -> None:
    from sqlalchemy import delete
    from app.models.run_models import ThreadExecutionLease
    await db.execute(delete(ThreadExecutionLease).where(ThreadExecutionLease.thread_id == thread_id, ThreadExecutionLease.run_id == run_id))

async def release_thread_execution(db: AsyncSession, thread_id: UUID, execution_type: str, execution_id: str) -> None:
    from sqlalchemy import delete
    from app.models.run_models import ThreadExecutionLease
    await db.execute(delete(ThreadExecutionLease).where(
        ThreadExecutionLease.thread_id == thread_id,
        ThreadExecutionLease.execution_type == execution_type,
        ThreadExecutionLease.execution_id == execution_id,
    ))

async def allocate_event_sequence(db: AsyncSession, run_id: UUID) -> int:
    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
    run = result.scalar_one()
    sequence = run.next_event_sequence
    run.next_event_sequence += 1
    await db.flush()
    return sequence

async def append_run_event(db: AsyncSession, run_id: UUID, event_type: str, payload: dict) -> AgentRunEvent:
    event = AgentRunEvent(run_id=run_id, sequence=await allocate_event_sequence(db, run_id), event_type=event_type, payload=payload)
    db.add(event); await db.flush(); return event

async def create_trigger_event(db: AsyncSession, **values) -> tuple[TriggerEvent, bool]:
    event = TriggerEvent(id=values.pop("id", uuid4()), **values)
    lookup = (event.workspace_id, event.source, event.dedupe_key)
    try:
        async with db.begin_nested():
            db.add(event)
            await db.flush()
        return event, True
    except IntegrityError:
        existing = await db.scalar(select(TriggerEvent).where(
            TriggerEvent.workspace_id == lookup[0],
            TriggerEvent.source == lookup[1],
            TriggerEvent.dedupe_key == lookup[2],
        ))
        return existing, False

async def create_live_run(db: AsyncSession, **values) -> tuple[AgentRun | None, bool]:
    mode = values.pop("mode", "live")
    if mode != "live":
        raise ValueError("create_live_run only accepts live runs")
    run = AgentRun(mode="live", **values)
    lookup = (run.agent_id, run.trigger_event_id)
    try:
        async with db.begin_nested():
            db.add(run)
            await db.flush()
        return run, True
    except IntegrityError:
        existing = await db.scalar(select(AgentRun).where(
            AgentRun.agent_id == lookup[0],
            AgentRun.trigger_event_id == lookup[1],
            AgentRun.mode == "live",
        ))
        return existing, False

transition_agent_run = transition_run
transition_agent_action = transition_action
