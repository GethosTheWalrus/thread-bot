from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.encoders import jsonable_encoder
import json
from fastapi.responses import JSONResponse
from temporalio.exceptions import WorkflowAlreadyStartedError
from sqlalchemy import select, desc, func, or_, exists
from app.database import get_db
from app.security import require_autonomy, require_owner_or_admin
from app.contracts.common import ActorContext
from app.contracts.phase4 import ReplayRequest, ReplayResponse, CanaryCreate, CanaryDecision, ForecastResponse, RecoveryRequest
from app.models.run_models import AgentRun, AgentRunEvent
from app.models.agent_models import Agent, AgentVersion
from app.models.phase4_models import ReplaySession, CanaryDeployment, CanaryAssignment, ForecastSnapshot, SLOAlert, QueueControl, SLOMetric
from app.models.agent_models import TriggerEvent
from app.models.phase2_models import ConnectorCursor
from app.models.approval_models import ApprovalRequest
from app.models.foundation_models import IdempotencyRecord
from app.services.phase4 import recorded_replay, reexecute_replay, forecast_from_runs, audit_recovery, redact_replay, shadow_effects_blocked


async def _workflow_is_started(client, workflow_id: str) -> bool:
    """Reconcile a start whose response may have been lost."""
    try:
        await client.get_workflow_handle(workflow_id).describe()
        return True
    except Exception:
        return False

router = APIRouter(prefix="/api", tags=["autonomy-phase4"], dependencies=[Depends(require_autonomy("autonomy_enabled"))])


async def actor_dep(actor: ActorContext = Depends(require_owner_or_admin)): return actor


def _replay_response(row):
    return redact_replay({"id": row.id, "mode": row.mode, "effect_free": row.effect_free, "source_run_id": row.source_run_id, "replay_run_id": row.replay_run_id, "timeline": row.timeline or [], "comparison": row.comparison or {}})


@router.post("/agent-runs/{run_id}/replay", response_model=ReplayResponse, dependencies=[Depends(require_autonomy("agents_replay_enabled"))])
async def replay_run(run_id: UUID, body: ReplayRequest, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.workspace_id == actor.workspace_id))
    if not run: raise HTTPException(404, "run not found")
    if idempotency_key:
        prior = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.workspace_id == actor.workspace_id, IdempotencyRecord.key == idempotency_key).with_for_update())
        if prior and prior.status == "completed" and prior.response:
            if prior.response.get("mode") not in (None, body.mode):
                raise HTTPException(409, "idempotency key is bound to a different replay mode")
            return prior.response
        if prior and prior.status == "in_progress":
            raise HTTPException(409, "replay dispatch is already in progress")
        if prior and prior.status == "failed":
            replay_session_id = prior.response.get("replay_session_id") if isinstance(prior.response, dict) else None
            row = await db.scalar(select(ReplaySession).where(ReplaySession.id == replay_session_id).with_for_update()) if replay_session_id else None
            if not row:
                row = await db.scalar(select(ReplaySession).where(ReplaySession.source_run_id == run.id, ReplaySession.workspace_id == actor.workspace_id).order_by(ReplaySession.created_at.desc()).with_for_update())
            prior.status = "in_progress"
        else:
            row = None
    else:
        prior = None
        row = None
    if row is not None and row.mode != body.mode:
        raise HTTPException(409, "idempotency key is bound to a different replay mode")
    if row is None:
        if body.mode == "recorded": row = await recorded_replay(db, run)
        else: row = await reexecute_replay(db, run)
        if idempotency_key:
            prior = IdempotencyRecord(workspace_id=actor.workspace_id, key=idempotency_key, operation=f"replay:{run_id}", status="in_progress", response={"replay_session_id": str(row.id)})
            db.add(prior)
    await audit_recovery(db, actor.workspace_id, actor.actor_id, f"{body.mode}_replay", str(run.id), {"effect_free": True})
    if body.mode == "reexecution":
        replay_run = await db.get(AgentRun, row.replay_run_id)
        if replay_run is None:
            raise HTTPException(409, "replay run is missing")
        # A failed dispatch is retryable, but it must reuse the same run and
        # stable workflow ID.  Never create another logical replay session.
        replay_run.status = "queued"
        replay_run.failure_code = None
        replay_run.failure_summary = None
        workflow_id = f"agent-run:{replay_run.id}"
        replay_run.temporal_workflow_id = workflow_id
    await db.commit()
    if body.mode == "reexecution":
        try:
            from app.api.routes import get_temporal_client
            from app.temporal_client import autonomy_search_attributes
            from app.workflows.agent_workflows import AgentRunWorkflow
            client = get_temporal_client()
            if client is None:
                raise RuntimeError("Temporal client unavailable")
            await client.start_workflow(
                AgentRunWorkflow.run, str(replay_run.id), id=workflow_id,
                task_queue="threadbot-agent",
                memo={"source_run_id": str(run.id), "agent_version_id": str(replay_run.agent_version_id), "mode": "replay"},
                search_attributes=autonomy_search_attributes(str(actor.workspace_id), str(replay_run.agent_id), "replay"),
            )
        except Exception as exc:
            # Temporal may have accepted StartWorkflow before the client lost
            # its response.  Treat AlreadyStarted and a successful describe as
            # reconciliation, not as a new execution or a failed dispatch.
            started = isinstance(exc, WorkflowAlreadyStartedError) or await _workflow_is_started(client, workflow_id)
            if started:
                row.comparison = {**(row.comparison or {}), "dispatch": "already_started"}
                if prior:
                    prior.status = "completed"
                    prior.response = jsonable_encoder(_replay_response(row))
                    await db.commit()
                return _replay_response(row)
            async with db.begin():
                replay_run = await db.scalar(select(AgentRun).where(AgentRun.id == row.replay_run_id).with_for_update())
                replay_run.status = "failed"
                replay_run.failure_code = "replay_dispatch_failed"
                replay_run.failure_summary = str(exc)[:500]
                row.comparison = {**(row.comparison or {}), "dispatch": "failed", "error": str(exc)[:500]}
                if prior:
                    prior.status = "failed"
                    prior.response = {"replay_session_id": str(row.id), "status": "failed", "error": "replay dispatch failed"}
            raise HTTPException(503, "replay dispatch failed; retry with the same idempotency key") from exc
    response = _replay_response(row)
    if prior:
        prior.status = "completed"
        prior.response = jsonable_encoder(response)
        await db.commit()
    return response


@router.get("/agent-runs/{run_id}/replay/export")
async def replay_export(run_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(ReplaySession).where(ReplaySession.source_run_id == run_id, ReplaySession.workspace_id == actor.workspace_id).order_by(ReplaySession.created_at.desc()))
    if not row: raise HTTPException(404, "replay not found")
    return JSONResponse({"schema_version": 1, "replay": redact_replay(_replay_response(row)), "secrets": "redacted"})


@router.get("/agent-runs/{run_id}/replay")
async def replay_detail(run_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    rows = (await db.execute(select(ReplaySession).where(ReplaySession.source_run_id == run_id, ReplaySession.workspace_id == actor.workspace_id).order_by(desc(ReplaySession.created_at)))).scalars().all()
    return [_replay_response(row) for row in rows]


@router.post("/agents/{agent_id}/canary", dependencies=[Depends(require_autonomy("agents_canary_enabled"))])
async def create_canary(agent_id: UUID, body: CanaryCreate, db=Depends(get_db), actor=Depends(actor_dep)):
    agent = await db.scalar(select(Agent).where(Agent.id == agent_id, Agent.workspace_id == actor.workspace_id))
    candidate = await db.scalar(select(AgentVersion).where(AgentVersion.id == body.candidate_version_id, AgentVersion.agent_id == agent_id))
    if not agent or not candidate or not agent.active_version_id: raise HTTPException(404, "agent or version not found")
    row = CanaryDeployment(workspace_id=actor.workspace_id, agent_id=agent_id, stable_version_id=agent.active_version_id, candidate_version_id=candidate.id, cohort=body.normalized_cohort, status="active")
    db.add(row); await db.flush(); return {"id": row.id, "status": row.status, "version": row.version, "stable_version_id": row.stable_version_id, "candidate_version_id": row.candidate_version_id, "cohort": row.cohort}


@router.get("/agents/{agent_id}/canary")
async def get_canary(agent_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    rows = (await db.execute(select(CanaryDeployment).where(CanaryDeployment.agent_id == agent_id, CanaryDeployment.workspace_id == actor.workspace_id).order_by(desc(CanaryDeployment.created_at)))).scalars().all()
    return rows


@router.post("/canaries/{deployment_id}/promote", dependencies=[Depends(require_autonomy("agents_canary_enabled"))])
async def promote_canary(deployment_id: UUID, body: CanaryDecision, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(CanaryDeployment).where(CanaryDeployment.id == deployment_id, CanaryDeployment.workspace_id == actor.workspace_id).with_for_update())
    if not row or row.status not in {"active", "paused"}: raise HTTPException(409, "canary is not promotable")
    if body.expected_version != row.version: raise HTTPException(409, "canary version conflict")
    agent = await db.scalar(select(Agent).where(Agent.id == row.agent_id).with_for_update())
    agent.active_version_id = row.candidate_version_id; row.status = "promoted"; row.version += 1; row.updated_at = datetime.now(timezone.utc)
    await audit_recovery(db, actor.workspace_id, actor.actor_id, "canary_promoted", str(row.id), {"reason": body.reason, "candidate_version_id": str(row.candidate_version_id)})
    await db.commit(); return {"id": row.id, "status": row.status, "version": row.version, "canary_version": row.version, "active_version_id": agent.active_version_id}


@router.post("/canaries/{deployment_id}/rollback", dependencies=[Depends(require_autonomy("agents_canary_enabled"))])
async def rollback_canary(deployment_id: UUID, body: CanaryDecision, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(CanaryDeployment).where(CanaryDeployment.id == deployment_id, CanaryDeployment.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "canary not found")
    if body.expected_version != row.version: raise HTTPException(409, "canary version conflict")
    agent = await db.scalar(select(Agent).where(Agent.id == row.agent_id).with_for_update())
    agent.active_version_id = row.stable_version_id; row.status = "rolled_back"; row.version += 1; row.updated_at = datetime.now(timezone.utc)
    await audit_recovery(db, actor.workspace_id, actor.actor_id, "canary_rolled_back", str(row.id), {"reason": body.reason})
    await db.commit(); return {"id": row.id, "status": row.status, "version": row.version, "canary_version": row.version, "active_version_id": agent.active_version_id}


@router.get("/agents/{agent_id}/forecast", response_model=ForecastResponse)
async def advanced_forecast(agent_id: UUID, horizon_hours: int = 24, db=Depends(get_db), actor=Depends(actor_dep)):
    agent = await db.scalar(select(Agent).where(Agent.id == agent_id, Agent.workspace_id == actor.workspace_id))
    if not agent:
        raise HTTPException(404, "agent not found")
    rows = list((await db.execute(select(AgentRun).where(AgentRun.agent_id == agent_id, AgentRun.workspace_id == actor.workspace_id, AgentRun.status.in_(["succeeded", "failed", "exhausted"])).order_by(desc(AgentRun.completed_at)).limit(500))).scalars())
    forecast = forecast_from_runs(rows, max(1, min(horizon_hours, 8760)))
    return forecast


@router.get("/canaries/{deployment_id}/comparisons")
async def canary_comparisons(deployment_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    from app.models.phase4_models import CanaryComparison
    rows = (await db.execute(select(CanaryComparison).where(CanaryComparison.deployment_id == deployment_id, CanaryComparison.workspace_id == actor.workspace_id).order_by(desc(CanaryComparison.created_at)))).scalars().all()
    return [{"id": r.id, "candidate_run_id": r.candidate_run_id, "stable_run_id": r.stable_run_id, "metrics": r.metrics, "created_at": r.created_at} for r in rows]


@router.post("/operations/recovery")
async def recovery(body: RecoveryRequest, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await audit_recovery(db, actor.workspace_id, actor.actor_id, body.operation, body.resource_id, body.details)
    await db.commit()
    return {"accepted": True, "operation_id": row.id, "operation": body.operation, "resource_id": body.resource_id}


@router.get("/operations/slo")
async def slo(db=Depends(get_db), actor=Depends(actor_dep)):
    now = datetime.now(timezone.utc)
    total = await db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.workspace_id == actor.workspace_id)) or 0
    queued = await db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.workspace_id == actor.workspace_id, AgentRun.status == "queued")) or 0
    dead = await db.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.workspace_id == actor.workspace_id, AgentRun.status == "dead_lettered")) or 0
    oldest_trigger = await db.scalar(select(func.min(TriggerEvent.received_at)).where(TriggerEvent.workspace_id == actor.workspace_id, ~exists(select(AgentRun.id).where(AgentRun.trigger_event_id == TriggerEvent.id))))
    oldest_cursor = await db.scalar(select(func.min(ConnectorCursor.updated_at)).where(ConnectorCursor.workspace_id == actor.workspace_id))
    oldest_approval = await db.scalar(select(func.min(ApprovalRequest.created_at)).where(ApprovalRequest.workspace_id == actor.workspace_id, ApprovalRequest.status == "pending"))
    trigger_lag = max(0, int((now - oldest_trigger).total_seconds())) if oldest_trigger else 0
    cursor_lag = max(0, int((now - oldest_cursor).total_seconds())) if oldest_cursor else 0
    approval_stall = max(0, int((now - oldest_approval).total_seconds())) if oldest_approval else 0
    queue_status = "alerting" if queued > 100 else "ok"
    dead_status = "alerting" if dead else "ok"
    from app.services.phase4 import upsert_slo_alert
    await upsert_slo_alert(db, actor.workspace_id, "queue_depth", "queue_depth", 100, queue_status, {"value": queued})
    await upsert_slo_alert(db, actor.workspace_id, "dead_letters", "dead_letter_count", 0, dead_status, {"value": dead})
    from app.services.phase4 import record_slo_metric
    for metric, value in (("trigger_lag_seconds", trigger_lag), ("cursor_lag_seconds", cursor_lag), ("pending_approval_stall_seconds", approval_stall)):
        await record_slo_metric(db, actor.workspace_id, metric, value)
    await upsert_slo_alert(db, actor.workspace_id, "trigger_lag", "trigger_lag_seconds", 300, "alerting" if trigger_lag > 300 else "ok", {"value": trigger_lag})
    await upsert_slo_alert(db, actor.workspace_id, "cursor_lag", "cursor_lag_seconds", 300, "alerting" if cursor_lag > 300 else "ok", {"value": cursor_lag})
    await upsert_slo_alert(db, actor.workspace_id, "approval_stall", "pending_approval_stall_seconds", 3600, "alerting" if approval_stall > 3600 else "ok", {"value": approval_stall})
    await db.commit()
    alerts = [key for key, active in (("queue_depth", queued > 100), ("dead_letters", bool(dead)), ("trigger_lag", trigger_lag > 300), ("cursor_lag", cursor_lag > 300), ("approval_stall", approval_stall > 3600)) if active]
    return {"runs_total": total, "queue_depth": queued, "dead_letters": dead, "slo": {"queue_depth_target": 100, "dead_letter_target": 0, "trigger_lag_target_seconds": 300, "cursor_lag_target_seconds": 300, "pending_approval_stall_target_seconds": 3600}, "metrics": {"queue_depth": queued, "dead_letter_count": dead, "trigger_lag_seconds": trigger_lag, "cursor_lag_seconds": cursor_lag, "pending_approval_stall_seconds": approval_stall}, "alerts": alerts, "secrets": False, "effect_free_modes": {"replay": "external effects suppressed", "canary_shadow": "external effects suppressed", "dry_run": "external effects suppressed"}}


@router.get("/operations/alerts")
async def alerts(status: str | None = None, db=Depends(get_db), actor=Depends(actor_dep)):
    query = select(SLOAlert).where(SLOAlert.workspace_id == actor.workspace_id)
    if status:
        query = query.where(SLOAlert.status == status)
    rows = (await db.execute(query.order_by(desc(SLOAlert.updated_at)))).scalars().all()
    return [{"id": r.id, "alert_key": r.alert_key, "metric": r.metric, "threshold": r.threshold, "status": r.status, "details": r.details} for r in rows]


@router.post("/operations/queues/{queue_name}/{state}")
async def queue_state(queue_name: str, state: str, db=Depends(get_db), actor=Depends(actor_dep)):
    allowed_queues = {"threadbot-agent", "threadbot-connectors", "threadbot-notifications"}
    if not (queue_name in allowed_queues or queue_name.startswith("agent:")):
        raise HTTPException(422, "queue is not operator controlled")
    if state not in {"paused", "draining", "running"}:
        raise HTTPException(422, "state must be paused, draining, or running")
    row = await db.scalar(select(QueueControl).where(QueueControl.workspace_id == actor.workspace_id, QueueControl.queue_name == queue_name).with_for_update())
    if not row:
        row = QueueControl(workspace_id=actor.workspace_id, queue_name=queue_name, state=state); db.add(row)
    else:
        row.state = state
    await audit_recovery(db, actor.workspace_id, actor.actor_id, {"paused": "pause_queue", "draining": "drain_queue", "running": "resume_queue"}[state], queue_name, {"state": state})
    await db.commit()
    return {"queue_name": queue_name, "state": state}
