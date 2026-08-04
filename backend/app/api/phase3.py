from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.security import require_autonomy, require_owner_or_admin
from app.contracts.common import ActorContext
from app.contracts.phase3 import HandoffContractCreate, HandoffContractPatch, HandoffContractResponse, HandoffContractValidation, HandoffContractVersionResponse, HandoffCreate, HandoffPage, HandoffResponse, ArtifactPage, ArtifactResponse, OperationsSummary, RecommendationCreate, RecommendationDecision, RecommendationResponse
from app.models.phase3_models import HandoffContract, AgentHandoff, PolicyRecommendation, ArtifactTombstone, HandoffEscalation
from app.models.run_models import Artifact, AgentRun
from app.models.foundation_models import AuditEvent, DomainEvent
from app.models.agent_models import AgentVersionDraft
from app.services.phase3 import create_handoff, record_handoff_rejection
import base64

def _cursor(row): return base64.urlsafe_b64encode(f"{row.created_at.isoformat()}|{row.id}".encode()).decode()
def _decode(value):
    try: stamp, raw_id = base64.urlsafe_b64decode(value.encode()).decode().split("|", 1); return datetime.fromisoformat(stamp), UUID(raw_id)
    except Exception as exc: raise HTTPException(400, "invalid cursor") from exc

router = APIRouter(prefix="/api", tags=["phase3"], dependencies=[Depends(require_autonomy("autonomy_enabled"))])

async def actor_dep(actor: ActorContext = Depends(require_owner_or_admin)): return actor

@router.post("/handoff-contracts", response_model=HandoffContractResponse)
async def create_contract(body: HandoffContractCreate, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    values = body.model_dump(mode="json")
    row = HandoffContract(workspace_id=actor.workspace_id, **values)
    db.add(row); await db.flush()
    from app.agents.autonomy_service import audit_mutation
    await audit_mutation(db, actor.workspace_id, actor, "handoff_contract.created", "handoff_contract", row.id)
    return row

@router.post("/handoff-contracts/{contract_id}/validate")
async def validate_contract(contract_id: UUID, body: HandoffContractValidation, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(HandoffContract).where(HandoffContract.id == contract_id, HandoffContract.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "contract not found")
    from app.services.phase3 import validate_json_schema
    try: validate_json_schema(row.input_schema, body.input_payload)
    except ValueError as exc: return {"valid": False, "errors": [str(exc)]}
    return {"valid": True, "contract_id": str(row.id), "version": row.version}

@router.get("/handoff-contracts/{contract_id}", response_model=HandoffContractResponse)
async def get_contract(contract_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(HandoffContract).where(HandoffContract.id == contract_id, HandoffContract.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "contract not found")
    return row

@router.patch("/handoff-contracts/{contract_id}", response_model=HandoffContractResponse)
async def patch_contract(contract_id: UUID, body: HandoffContractPatch, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(HandoffContract).where(HandoffContract.id == contract_id, HandoffContract.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "contract not found")
    if row.status != "draft": raise HTTPException(409, "only draft contracts may be edited")
    if row.lifecycle_version != body.lifecycle_version: raise HTTPException(409, "contract version conflict")
    for key, value in body.model_dump(exclude={"lifecycle_version"}, exclude_none=True, mode="json").items(): setattr(row, key, value)
    row.lifecycle_version += 1
    from app.agents.autonomy_service import audit_mutation
    await audit_mutation(db, actor.workspace_id, actor, "handoff_contract.updated", "handoff_contract", row.id, {"lifecycle_version": row.lifecycle_version})
    return row

@router.post("/handoff-contracts/{contract_id}/activate", response_model=HandoffContractResponse)
async def activate_contract(contract_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(HandoffContract).where(HandoffContract.id == contract_id, HandoffContract.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "contract not found")
    row.status = "active"; row.is_active = True; row.lifecycle_version += 1
    from app.agents.autonomy_service import audit_mutation
    await audit_mutation(db, actor.workspace_id, actor, "handoff_contract.activated", "handoff_contract", row.id)
    return row

@router.post("/handoff-contracts/{contract_id}/archive", response_model=HandoffContractResponse)
async def archive_contract(contract_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(HandoffContract).where(HandoffContract.id == contract_id, HandoffContract.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "contract not found")
    row.status = "archived"; row.is_active = False; row.lifecycle_version += 1
    from app.agents.autonomy_service import audit_mutation
    await audit_mutation(db, actor.workspace_id, actor, "handoff_contract.archived", "handoff_contract", row.id)
    return row

@router.get("/handoff-contracts/{contract_id}/versions", response_model=list[HandoffContractVersionResponse])
async def contract_versions(contract_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    current = await db.scalar(select(HandoffContract).where(HandoffContract.id == contract_id, HandoffContract.workspace_id == actor.workspace_id))
    if not current: raise HTTPException(404, "contract not found")
    return list((await db.execute(select(HandoffContract).where(HandoffContract.workspace_id == actor.workspace_id, HandoffContract.name == current.name).order_by(HandoffContract.version))).scalars())

@router.get("/handoff-contracts")
async def list_contracts(limit: int = 50, cursor: str | None = None, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    q = select(HandoffContract).where(HandoffContract.workspace_id == actor.workspace_id).order_by(desc(HandoffContract.created_at), desc(HandoffContract.id)).limit(min(limit, 200))
    if cursor:
        stamp, raw_id = _decode(cursor); from sqlalchemy import and_, or_
        q = q.where(or_(HandoffContract.created_at < stamp, and_(HandoffContract.created_at == stamp, HandoffContract.id < raw_id)))
    rows = list((await db.execute(q)).scalars()); return {"items": rows, "next_cursor": _cursor(rows[-1]) if len(rows) == min(limit, 200) else None}

@router.post("/handoffs", response_model=HandoffResponse, status_code=202)
async def handoff(body: HandoffCreate, source_run_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if idempotency_key and idempotency_key != body.idempotency_key: raise HTTPException(409, "Idempotency-Key does not match request")
    try: row = await create_handoff(db, actor.workspace_id, source_run_id, body)
    except ValueError as exc:
        await record_handoff_rejection(db, actor.workspace_id, source_run_id, str(exc)); await db.commit()
        raise HTTPException(422, str(exc)) from exc
    await db.commit()
    source_run = await db.get(AgentRun, source_run_id)
    from app.api.routes import get_temporal_client
    client = get_temporal_client()
    if client is None: raise HTTPException(503, "agent worker unavailable; handoff was durably queued")
    from app.workflows.phase3_workflows import HandoffSLAWorkflow
    try:
        await client.start_workflow(HandoffSLAWorkflow.run, {"handoff_id": str(row.id), "workspace_id": str(actor.workspace_id), "mode": source_run.mode if source_run else "autonomous", "acknowledgement_deadline": row.acknowledgement_deadline.isoformat(), "completion_deadline": row.completion_deadline.isoformat()}, id=f"handoff-sla:{row.id}", task_queue="threadbot-agent")
    except Exception as exc:
        raise HTTPException(503, "handoff SLA dispatch failed; recovery will retry") from exc
    return row

@router.post("/handoffs/{handoff_id}/acknowledge")
async def acknowledge(handoff_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(AgentHandoff).where(AgentHandoff.id == handoff_id, AgentHandoff.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "handoff not found")
    client = __import__("app.api.routes", fromlist=["get_temporal_client"]).get_temporal_client()
    if client is None: raise HTTPException(503, "agent worker unavailable")
    from app.workflows.phase3_workflows import HandoffSLAWorkflow
    try:
        await client.get_workflow_handle(f"handoff-sla:{handoff_id}").signal(HandoffSLAWorkflow.acknowledge)
    except Exception as exc: raise HTTPException(503, "handoff SLA workflow unavailable") from exc
    return {"accepted": True, "workflow_id": f"handoff-sla:{handoff_id}"}

@router.get("/handoffs/{handoff_id}/sla")
async def sla_status(handoff_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(AgentHandoff).where(AgentHandoff.id == handoff_id, AgentHandoff.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "handoff not found")
    client = __import__("app.api.routes", fromlist=["get_temporal_client"]).get_temporal_client()
    workflow_status = "unavailable"
    if client is not None:
        try: workflow_status = (await client.get_workflow_handle(f"handoff-sla:{handoff_id}").describe()).status.name
        except Exception: workflow_status = "missing_or_failed"
    return {"handoff_id": str(row.id), "status": row.status, "acknowledged_at": row.acknowledged_at, "completion_deadline": row.completion_deadline, "workflow_status": workflow_status}

@router.get("/handoffs", response_model=HandoffPage)
async def list_handoffs(limit: int = 50, cursor: str | None = None, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    q = select(AgentHandoff).where(AgentHandoff.workspace_id == actor.workspace_id).order_by(desc(AgentHandoff.created_at), desc(AgentHandoff.id)).limit(min(limit, 200))
    if cursor:
        stamp, raw_id = _decode(cursor); from sqlalchemy import and_, or_
        q = q.where(or_(AgentHandoff.created_at < stamp, and_(AgentHandoff.created_at == stamp, AgentHandoff.id < raw_id)))
    rows = list((await db.execute(q)).scalars()); return {"items": rows, "next_cursor": _cursor(rows[-1]) if len(rows) == min(limit, 200) else None}

@router.get("/sla-incidents")
async def sla_incidents(limit: int = 50, cursor: str | None = None, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    q = select(HandoffEscalation).where(HandoffEscalation.workspace_id == actor.workspace_id).order_by(desc(HandoffEscalation.created_at), desc(HandoffEscalation.id)).limit(min(limit, 200))
    if cursor:
        stamp, raw_id = _decode(cursor); from sqlalchemy import and_, or_
        q = q.where(or_(HandoffEscalation.created_at < stamp, and_(HandoffEscalation.created_at == stamp, HandoffEscalation.id < raw_id)))
    rows = list((await db.execute(q)).scalars()); return {"items": rows, "next_cursor": _cursor(rows[-1]) if len(rows) == min(limit, 200) else None}

@router.get("/artifacts", response_model=ArtifactPage)
async def artifacts(limit: int = 50, cursor: str | None = None, run_id: UUID | None = None, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    q = select(Artifact).where(Artifact.workspace_id == actor.workspace_id).order_by(desc(Artifact.created_at), desc(Artifact.id)).limit(min(limit, 200))
    if run_id:
        q = q.where(Artifact.run_id == run_id)
    if cursor:
        stamp, raw_id = _decode(cursor); from sqlalchemy import and_, or_
        q = q.where(or_(Artifact.created_at < stamp, and_(Artifact.created_at == stamp, Artifact.id < raw_id)))
    rows = list((await db.execute(q)).scalars()); return {"items": rows, "next_cursor": _cursor(rows[-1]) if len(rows) == min(limit, 200) else None}

@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
async def artifact_detail(artifact_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "artifact not found")
    return row

@router.post("/artifacts/{artifact_id}/legal-hold", response_model=ArtifactResponse)
async def artifact_hold(artifact_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "artifact not found")
    row.legal_hold = 1; return row

@router.delete("/artifacts/{artifact_id}/legal-hold", response_model=ArtifactResponse)
async def artifact_unhold(artifact_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "artifact not found")
    row.legal_hold = 0; return row

@router.patch("/artifacts/{artifact_id}/retention", response_model=ArtifactResponse)
async def artifact_retention(artifact_id: UUID, retention_until: datetime, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(Artifact).where(Artifact.id == artifact_id, Artifact.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "artifact not found")
    row.retention_until = retention_until; return row

@router.get("/artifact-tombstones")
async def tombstones(limit: int = 50, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    return list((await db.execute(select(ArtifactTombstone).where(ArtifactTombstone.workspace_id == actor.workspace_id).order_by(desc(ArtifactTombstone.deleted_at)).limit(min(limit, 200)))).scalars())

@router.get("/operations/summary", response_model=OperationsSummary)
async def operations_summary(db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    active = await db.scalar(select(__import__("sqlalchemy", fromlist=["func"]).func.count()).select_from(AgentRun).where(AgentRun.workspace_id == actor.workspace_id, AgentRun.status == "running")) or 0
    queued = await db.scalar(select(__import__("sqlalchemy", fromlist=["func"]).func.count()).select_from(AgentRun).where(AgentRun.workspace_id == actor.workspace_id, AgentRun.status == "queued")) or 0
    pending = await db.scalar(select(__import__("sqlalchemy", fromlist=["func"]).func.count()).select_from(AgentHandoff).where(AgentHandoff.workspace_id == actor.workspace_id, AgentHandoff.status.in_(["pending", "acknowledged"]))) or 0
    incidents = await db.scalar(select(__import__("sqlalchemy", fromlist=["func"]).func.count()).select_from(HandoffEscalation).where(HandoffEscalation.workspace_id == actor.workspace_id)) or 0
    from app.config import get_settings
    return {"active_runs": active, "queued_runs": queued, "pending_handoffs": pending, "sla_incidents": incidents, "queue_health": {"chat": get_settings().TEMPORAL_TASK_QUEUE, "agent": get_settings().AGENT_TASK_QUEUE, "connectors": get_settings().CONNECTOR_TASK_QUEUE, "notifications": get_settings().NOTIFICATION_TASK_QUEUE, "visibility": "sampled"}}

@router.get("/handoffs/{handoff_id}", response_model=HandoffResponse)
async def handoff_detail(handoff_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(AgentHandoff).where(AgentHandoff.id == handoff_id, AgentHandoff.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "handoff not found")
    return row

@router.get("/policy-recommendations", response_model=list[RecommendationResponse])
async def recommendations(db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    return list((await db.execute(select(PolicyRecommendation).where(PolicyRecommendation.workspace_id == actor.workspace_id).order_by(desc(PolicyRecommendation.created_at)).limit(200))).scalars())

@router.post("/policy-recommendations", response_model=RecommendationResponse, status_code=201)
async def create_recommendation(body: RecommendationCreate, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = PolicyRecommendation(workspace_id=actor.workspace_id, **body.model_dump())
    db.add(row); await db.flush(); return row

@router.post("/policy-recommendations/{recommendation_id}/decision", response_model=RecommendationResponse)
async def recommendation_decision(recommendation_id: UUID, body: RecommendationDecision, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(PolicyRecommendation).where(PolicyRecommendation.id == recommendation_id, PolicyRecommendation.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "recommendation not found")
    if row.status != "pending": raise HTTPException(409, "recommendation already decided")
    row.status = "accepted" if body.accept else "rejected"; row.decided_at = datetime.now(timezone.utc)
    if body.accept:
        diff = row.proposed_diff or {}; agent_id = diff.get("agent_id")
        if agent_id:
            from app.agents.autonomy_service import upsert_draft
            try:
                draft = await upsert_draft(db, UUID(str(agent_id)), actor.workspace_id, {"optimistic_lock_version": 1, "schema_version": diff.get("schema_version", 1), "config": diff.get("config", {}), "prompt_template": diff.get("prompt_template", ""), "tool_selection": diff.get("tool_selection", []), "skill_selection": diff.get("skill_selection", []), "credential_bindings": diff.get("credential_bindings", [])})
            except (LookupError, ValueError) as exc: raise HTTPException(422, str(exc)) from exc
            row.accepted_draft_id = draft.id
    return row
