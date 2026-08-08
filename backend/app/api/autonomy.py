from uuid import UUID
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Header, WebSocket, WebSocketDisconnect
from sqlalchemy import select, desc, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.security import require_autonomy, require_owner_or_admin
from app.contracts.common import ActorContext
from app.contracts.autonomy import *
from app.agents.autonomy_service import *
from app.models.agent_models import Agent, AgentTemplate, AgentTemplateVersion, AgentVersion, AgentVersionDraft, AgentTrigger
from app.models.run_models import AgentRun, AgentRunEvent
from app.models.models import Message, Thread
from app.models.foundation_models import AuditEvent
from app.models.foundation_models import IdempotencyRecord
from app.tools.catalog import builtin_descriptors
from app.agents.schedule_service import preview
from app.agents.temporal_schedule_service import create_or_update_schedule, delete_schedule, pause_schedule, resume_schedule
import base64, json

router=APIRouter(prefix="/api/autonomy", tags=["autonomy"], dependencies=[Depends(require_autonomy("autonomy_enabled"))])
async def actor_dep(actor:ActorContext=Depends(require_owner_or_admin)): return actor
def not_found(): raise HTTPException(404,"resource not found")
def output(row): return row
def encode_cursor(value): return base64.urlsafe_b64encode(json.dumps(value,separators=(",",":")).encode()).decode()
def decode_cursor(value):
    try:return json.loads(base64.urlsafe_b64decode(value.encode()))
    except Exception: raise HTTPException(400,"invalid cursor")

@router.get("/capabilities")
async def capabilities(): return {"tools": [{"identity":f"builtin:{x['function']['name']}","risk":"low","side_effects":False} for x in builtin_descriptors()],"skills":{"trusted_instructions_only":True}}

@router.post("/templates", response_model=TemplateResponse)
async def create_template(body:TemplateCreate, db:AsyncSession=Depends(get_db), actor=Depends(actor_dep)):
    row=AgentTemplate(workspace_id=actor.workspace_id,name=body.name,description=body.description,schema_version=body.schema_version,definition=body.definition); db.add(row); await db.flush(); await audit_mutation(db,actor.workspace_id,actor,"template.created","agent_template",row.id); return row
@router.get("/templates")
async def list_templates(db=Depends(get_db),actor=Depends(actor_dep)): return (await db.execute(select(AgentTemplate).where(AgentTemplate.workspace_id==actor.workspace_id).order_by(AgentTemplate.name))).scalars().all()
@router.patch("/templates/{template_id}")
async def patch_template(template_id:UUID,body:TemplateCreate,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(AgentTemplate).where(AgentTemplate.id==template_id,AgentTemplate.workspace_id==actor.workspace_id));
    if not row:return not_found()
    row.name=body.name; row.description=body.description; row.schema_version=body.schema_version; row.definition=body.definition; return row
@router.delete("/templates/{template_id}",status_code=204)
async def delete_template(template_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(AgentTemplate).where(AgentTemplate.id==template_id,AgentTemplate.workspace_id==actor.workspace_id));
    if not row:return not_found()
    row.status="archived"

@router.post("/agents", response_model=AgentResponse)
async def create(body:AgentCreate,db=Depends(get_db),actor=Depends(actor_dep)):
    try:
        row=await create_agent(db,actor.workspace_id,actor,body.model_dump(mode="json")); await audit_mutation(db,actor.workspace_id,actor,"agent.created","agent",row.id); return row
    except IntegrityError: raise HTTPException(409,"agent name already exists")
def _agent_response(row: Agent, thread_title: str | None = None) -> dict:
    return {
        "id": row.id, "thread_id": row.thread_id, "thread_title": thread_title,
        "name": row.name, "handle": row.handle, "is_moderator": row.is_moderator,
        "is_system": bool(getattr(row, "is_system", False)),
        "description": row.description, "status": row.status,
        "execution_mode": row.execution_mode, "active_version_id": row.active_version_id,
        "template_id": row.template_id, "concurrency_limit": row.concurrency_limit,
        "queue_limit": row.queue_limit, "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


@router.get("/agents", response_model=AgentPage)
async def agents(db=Depends(get_db),actor=Depends(actor_dep),limit:int=50,cursor:str|None=None,q:str|None=None,status:str|None=None,moderator:bool|None=None,thread_id:UUID|None=None):
    stmt=select(Agent,Thread.title).join(Thread,Thread.id==Agent.thread_id).where(Agent.workspace_id==actor.workspace_id,Agent.is_system.is_(False))
    if q and q.strip():
        term=f"%{q.strip()}%"
        stmt=stmt.where(or_(Agent.name.ilike(term),Agent.handle.ilike(term),Thread.title.ilike(term)))
    if status and status not in {"all", "current"}: stmt=stmt.where(Agent.status==status)
    elif status != "all": stmt=stmt.where(Agent.status != "archived")
    if moderator is not None: stmt=stmt.where(Agent.is_moderator.is_(moderator))
    if thread_id is not None: stmt=stmt.where(Agent.thread_id==thread_id)
    stmt=stmt.order_by(desc(Agent.created_at)).limit(min(limit,200))
    if cursor:
        stamp,raw_id=decode_cursor(cursor); stmt=stmt.where(or_(Agent.created_at < datetime.fromisoformat(stamp),and_(Agent.created_at==datetime.fromisoformat(stamp),Agent.id < UUID(raw_id))))
    rows=(await db.execute(stmt)).all()
    items=[_agent_response(agent,thread_title) for agent,thread_title in rows]
    last=rows[-1][0] if rows else None
    return {"items":items,"next_cursor":encode_cursor([last.created_at.isoformat(),str(last.id)]) if last and len(rows)==min(limit,200) else None}

@router.get("/threads/{thread_id}/agents", response_model=list[AgentResponse])
async def thread_agents(thread_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    return await list_thread_agents(db, actor.workspace_id, thread_id)

@router.post("/threads/{thread_id}/agents", response_model=AgentResponse)
async def add_thread_agent(thread_id: UUID, body: AgentCreate, db=Depends(get_db), actor=Depends(actor_dep)):
    values = body.model_dump(mode="json")
    values["thread_id"] = thread_id
    try:
        row = await create_agent(db, actor.workspace_id, actor, values)
        await audit_mutation(db, actor.workspace_id, actor, "agent.created", "agent", row.id)
        return row
    except (LookupError, IntegrityError) as exc:
        raise HTTPException(409, str(exc)) from exc

@router.patch("/threads/{thread_id}/agents/{agent_id}", response_model=AgentResponse)
async def patch_thread_agent(thread_id: UUID, agent_id: UUID, body: AgentPatch, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(Agent).where(Agent.id == agent_id, Agent.thread_id == thread_id, Agent.workspace_id == actor.workspace_id))
    if not row:
        raise HTTPException(404, "agent not found")
    if row.is_system:
        raise HTTPException(409, "the Thread moderator is managed automatically")
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(row, key, value.value if hasattr(value, "value") else value)
    await db.flush()
    return row

@router.patch("/threads/{thread_id}/turn-limit")
async def patch_thread_turn_limit(thread_id: UUID, limit: int, db=Depends(get_db), actor=Depends(actor_dep)):
    thread = await db.scalar(select(Thread).where(Thread.id == thread_id, Thread.workspace_id == actor.workspace_id))
    if not thread:
        raise HTTPException(404, "thread not found")
    if not 1 <= limit <= 8:
        raise HTTPException(422, "turn limit must be between 1 and 8")
    thread.agent_turn_limit = limit
    await db.flush()
    return {"thread_id": thread_id, "agent_turn_limit": limit}

@router.post("/threads/{thread_id}/agents/{agent_id}/moderator", response_model=AgentResponse)
async def thread_moderator(thread_id: UUID, agent_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    raise HTTPException(409, "the Thread moderator is managed automatically")

@router.delete("/threads/{thread_id}/agents/{agent_id}", response_model=AgentResponse)
async def thread_archive_agent(thread_id: UUID, agent_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    try: return await archive_thread_agent(db, actor.workspace_id, thread_id, agent_id)
    except LookupError as exc: raise HTTPException(404, str(exc))
    except ValueError as exc: raise HTTPException(409, str(exc))
@router.get("/agents/{agent_id}",response_model=AgentResponse)
async def get_agent(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    result=(await db.execute(select(Agent,Thread.title).join(Thread,Thread.id==Agent.thread_id).where(Agent.id==agent_id,Agent.workspace_id==actor.workspace_id))).first()
    return _agent_response(result[0],result[1]) if result else not_found()
@router.patch("/agents/{agent_id}",response_model=AgentResponse)
async def patch_agent(agent_id:UUID,body:AgentPatch,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(Agent).where(Agent.id==agent_id,Agent.workspace_id==actor.workspace_id));
    if not row: return not_found()
    if row.is_system: raise HTTPException(409,"the Thread moderator is managed automatically")
    for k,v in body.model_dump(exclude_unset=True).items(): setattr(row,k,v.value if hasattr(v,"value") else v)
    row.updated_at=datetime.now(timezone.utc); await audit_mutation(db,actor.workspace_id,actor,"agent.updated","agent",row.id,body.model_dump(exclude_unset=True))
    return row
@router.post("/agents/{agent_id}/pause",response_model=AgentResponse)
async def pause(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)): return await lifecycle(db,agent_id,actor,"paused")
@router.post("/agents/{agent_id}/resume",response_model=AgentResponse)
async def resume(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)): return await lifecycle(db,agent_id,actor,"active")
async def lifecycle(db,agent_id,actor,status):
    row=await db.scalar(select(Agent).where(Agent.id==agent_id,Agent.workspace_id==actor.workspace_id));
    if not row: return not_found()
    if row.is_system: raise HTTPException(409,"the Thread moderator is managed automatically")
    if row.status=="archived": raise HTTPException(409,"archived agent")
    row.status=status; row.updated_at=datetime.now(timezone.utc); await audit_mutation(db,actor.workspace_id,actor,f"agent.{status}","agent",row.id); return row
@router.delete("/agents/{agent_id}",status_code=204)
async def archive(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(Agent).where(Agent.id==agent_id,Agent.workspace_id==actor.workspace_id));
    if not row: return not_found()
    if row.is_system: raise HTTPException(409,"the Thread moderator is managed automatically")
    try: row = await archive_thread_agent(db, actor.workspace_id, row.thread_id, row.id)
    except ValueError as exc: raise HTTPException(409, str(exc))
    row.updated_at=datetime.now(timezone.utc); await audit_mutation(db,actor.workspace_id,actor,"agent.archived","agent",row.id)

@router.put("/agents/{agent_id}/draft",response_model=DraftResponse)
async def draft(agent_id:UUID,body:DraftUpsert,db=Depends(get_db),actor=Depends(actor_dep)):
    agent=await db.scalar(select(Agent).where(Agent.id==agent_id,Agent.workspace_id==actor.workspace_id))
    if agent and agent.is_system: raise HTTPException(409,"the Thread moderator is managed automatically")
    try:
        row=await upsert_draft(db,agent_id,actor.workspace_id,body.model_dump(mode="json")); await db.refresh(row); await audit_mutation(db,actor.workspace_id,actor,"agent.draft_updated","agent",agent_id); return row
    except ValueError as exc: raise HTTPException(409,str(exc))
@router.get("/agents/{agent_id}/draft",response_model=DraftResponse)
async def get_draft(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(AgentVersionDraft).join(Agent,Agent.id==AgentVersionDraft.agent_id).where(AgentVersionDraft.agent_id==agent_id,Agent.workspace_id==actor.workspace_id)); return row or not_found()
@router.post("/agents/{agent_id}/activate",response_model=VersionResponse)
async def activate(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    agent=await db.scalar(select(Agent).where(Agent.id==agent_id,Agent.workspace_id==actor.workspace_id))
    if agent and agent.is_system: raise HTTPException(409,"the Thread moderator is managed automatically")
    try:
        row=await activate_draft(db,agent_id,actor.workspace_id,actor); await audit_mutation(db,actor.workspace_id,actor,"agent.activated","agent",agent_id,{"version_id":str(row.id)}); return row
    except LookupError as exc: raise HTTPException(404,str(exc))
@router.get("/agents/{agent_id}/versions",response_model=list[VersionResponse])
async def versions(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)): return (await db.execute(select(AgentVersion).join(Agent,Agent.id==AgentVersion.agent_id).where(AgentVersion.agent_id==agent_id,Agent.workspace_id==actor.workspace_id).order_by(desc(AgentVersion.version)))).scalars().all()

@router.post("/agents/{agent_id}/triggers",response_model=TriggerResponse)
async def trigger(agent_id:UUID,body:TriggerCreate,db=Depends(get_db),actor=Depends(actor_dep)):
    agent=await db.scalar(select(Agent).where(Agent.id==agent_id,Agent.workspace_id==actor.workspace_id))
    if not agent: return not_found()
    if agent.is_system: raise HTTPException(409,"the Thread moderator cannot be scheduled")
    row=AgentTrigger(workspace_id=actor.workspace_id,agent_id=agent_id,trigger_type=body.trigger_type.value,config=body.config,is_active=body.is_active); db.add(row); await db.flush(); await audit_mutation(db,actor.workspace_id,actor,"trigger.created","agent_trigger",row.id); return row
@router.get("/agents/{agent_id}/triggers",response_model=list[TriggerResponse])
async def triggers(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)): return (await db.execute(select(AgentTrigger).where(AgentTrigger.agent_id==agent_id,AgentTrigger.workspace_id==actor.workspace_id))).scalars().all()
@router.post("/triggers/preview",response_model=TriggerPreview)
async def trigger_preview(body:SchedulePreviewRequest,actor=Depends(actor_dep)):
    try:return preview(body.cron,body.timezone,body.count)
    except ValueError as exc:raise HTTPException(422,str(exc))
@router.post("/triggers/{trigger_id}/test")
async def test_trigger(trigger_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(AgentTrigger).where(AgentTrigger.id==trigger_id,AgentTrigger.workspace_id==actor.workspace_id));
    if not row:return not_found()
    if row.trigger_type!="schedule": return {"valid":True,"preview":None}
    try:return {"valid":True,"preview":preview(row.config["cron"],row.config.get("timezone","UTC"),5)}
    except (KeyError,ValueError) as exc:raise HTTPException(422,str(exc))
@router.patch("/triggers/{trigger_id}",response_model=TriggerResponse)
async def patch_trigger(trigger_id:UUID,body:TriggerCreate,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(AgentTrigger).where(AgentTrigger.id==trigger_id,AgentTrigger.workspace_id==actor.workspace_id));
    if not row:return not_found()
    row.trigger_type=body.trigger_type.value; row.config=body.config; row.is_active=body.is_active; row.updated_at=datetime.now(timezone.utc); await audit_mutation(db,actor.workspace_id,actor,"trigger.updated","agent_trigger",row.id); return row
@router.delete("/triggers/{trigger_id}",status_code=204)
async def delete_trigger(trigger_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(AgentTrigger).where(AgentTrigger.id==trigger_id,AgentTrigger.workspace_id==actor.workspace_id));
    if not row:return not_found()
    row.is_active=False; row.updated_at=datetime.now(timezone.utc); await audit_mutation(db,actor.workspace_id,actor,"trigger.deleted","agent_trigger",row.id)
@router.post("/triggers/{trigger_id}/schedule")
async def schedule_trigger(trigger_id:UUID,db=Depends(get_db),actor=Depends(actor_dep),idempotency_key:str|None=Header(None,alias="Idempotency-Key")):
    if not idempotency_key: raise HTTPException(422,"Idempotency-Key header is required")
    from app.api.routes import get_temporal_client
    row=await db.scalar(select(AgentTrigger).where(AgentTrigger.id==trigger_id,AgentTrigger.workspace_id==actor.workspace_id,AgentTrigger.trigger_type=="schedule"));
    if not row:return not_found()
    client=get_temporal_client()
    if client is None: raise HTTPException(503,"Temporal client unavailable")
    sid=await create_or_update_schedule(client,row.id,row.config["cron"],row.config.get("timezone","UTC"),row.config.get("overlap","skip")); return {"schedule_id":sid,"trigger_id":str(row.id),"status":"scheduled","cron":row.config["cron"],"timezone":row.config.get("timezone","UTC"),"overlap":row.config.get("overlap","skip"),"idempotency_key":idempotency_key}
@router.delete("/triggers/{trigger_id}/schedule",status_code=204)
async def unschedule_trigger(trigger_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    from app.api.routes import get_temporal_client
    row=await db.scalar(select(AgentTrigger).where(AgentTrigger.id==trigger_id,AgentTrigger.workspace_id==actor.workspace_id))
    if not row:return not_found()
    client=get_temporal_client()
    if client is None: raise HTTPException(503,"Temporal client unavailable")
    await delete_schedule(client,trigger_id)
@router.post("/triggers/{trigger_id}/schedule/pause")
async def pause_schedule_trigger(trigger_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    from app.api.routes import get_temporal_client
    row=await db.scalar(select(AgentTrigger).where(AgentTrigger.id==trigger_id,AgentTrigger.workspace_id==actor.workspace_id))
    if not row:return not_found()
    client=get_temporal_client()
    if client is None: raise HTTPException(503,"Temporal client unavailable")
    await pause_schedule(client,trigger_id); return {"paused":True}
@router.post("/triggers/{trigger_id}/schedule/resume")
async def resume_schedule_trigger(trigger_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    from app.api.routes import get_temporal_client
    row=await db.scalar(select(AgentTrigger).where(AgentTrigger.id==trigger_id,AgentTrigger.workspace_id==actor.workspace_id))
    if not row:return not_found()
    client=get_temporal_client()
    if client is None: raise HTTPException(503,"Temporal client unavailable")
    await resume_schedule(client,trigger_id); return {"paused":False}
@router.post("/agents/{agent_id}/run",response_model=RunResponse)
async def run(agent_id:UUID,body:RunRequest,request:Request,db=Depends(get_db),actor=Depends(actor_dep),idempotency_key:str|None=Header(None,alias="Idempotency-Key")):
    agent=await db.scalar(select(Agent).where(Agent.id==agent_id,Agent.workspace_id==actor.workspace_id));
    if not agent: raise HTTPException(404,"agent not found")
    if agent.is_system: raise HTTPException(409,"the Thread moderator only routes Thread messages")
    if agent.status != "active": raise HTTPException(409,f"agent is {agent.status} and cannot receive runs")
    if not agent.active_version_id: raise HTTPException(409,"agent has no active version")
    version=await db.get(AgentVersion,agent.active_version_id)
    if not idempotency_key: raise HTTPException(422,"Idempotency-Key header is required")
    result=None
    try:
        existing_record=await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.workspace_id==actor.workspace_id,IdempotencyRecord.key==idempotency_key))
        result=await create_run(db,actor.workspace_id,actor,agent,version,body.message,body.mode.value,None,idempotency_key,body.response_mode.value)
        await db.commit()
        from app.api.routes import get_temporal_client
        client=get_temporal_client()
        if client is not None and existing_record is None:
            from app.workflows.agent_workflows import TriggerDispatchWorkflow
            await client.start_workflow(TriggerDispatchWorkflow.run,{"agent_id":str(agent.id),"event_id":str(result.trigger_event_id)},id=f"trigger-dispatch:{result.trigger_event_id}",task_queue="threadbot-agent")
        return result
    except ValueError as exc: raise HTTPException(409,str(exc))
    except Exception as exc:
        if result is not None: await fail_queued_run(db,result.id,str(exc)); await db.commit()
        raise HTTPException(503,"autonomy dispatch failed") from exc

@router.post("/agents/{agent_id}/dry-run",response_model=RunResponse)
async def dry_run(agent_id:UUID,body:RunRequest,request:Request,db=Depends(get_db),actor=Depends(actor_dep),idempotency_key:str|None=Header(None,alias="Idempotency-Key")):
    if body.mode != RunMode.dry_run: body=body.model_copy(update={"mode":RunMode.dry_run})
    return await run(agent_id,body,request,db,actor,idempotency_key)
@router.get("/agents/{agent_id}/runs", response_model=RunPage)
async def runs(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep),limit:int=50,after:str|None=None):
    q=select(AgentRun).where(AgentRun.agent_id==agent_id,AgentRun.workspace_id==actor.workspace_id).order_by(desc(AgentRun.queued_at),desc(AgentRun.id)).limit(min(limit,200))
    if after:
        stamp,raw_id=decode_cursor(after); parsed=datetime.fromisoformat(stamp); q=q.where(or_(AgentRun.queued_at < parsed,and_(AgentRun.queued_at==parsed,AgentRun.id < UUID(raw_id))))
    rows=(await db.execute(q)).scalars().all(); return {"items":rows,"next_cursor":encode_cursor([rows[-1].queued_at.isoformat(),str(rows[-1].id)]) if len(rows)==min(limit,200) else None}
@router.get("/runs/{run_id}", response_model=RunResponse)
async def run_detail(run_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(AgentRun).where(AgentRun.id==run_id,AgentRun.workspace_id==actor.workspace_id)); return row or not_found()
@router.get("/runs/{run_id}/events", response_model=EventPage)
async def events(run_id:UUID,db=Depends(get_db),actor=Depends(actor_dep),after:int=0,limit:int=100):
    page_size=min(limit,500)
    rows=(await db.execute(select(AgentRunEvent).join(AgentRun,AgentRun.id==AgentRunEvent.run_id).where(AgentRunEvent.run_id==run_id,AgentRun.workspace_id==actor.workspace_id,AgentRunEvent.sequence>after).order_by(AgentRunEvent.sequence).limit(page_size))).scalars().all()
    return {"items":rows,"next_cursor":rows[-1].sequence if len(rows)==page_size else None}
@router.post("/runs/{run_id}/cancel", response_model=RunResponse)
async def cancel(run_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    row=await db.scalar(select(AgentRun).where(AgentRun.id==run_id,AgentRun.workspace_id==actor.workspace_id));
    if not row:return not_found()
    if row.status in {"queued","running","waiting_approval","waiting_handoff"}:
        from app.api.routes import get_temporal_client
        client=get_temporal_client()
        if client is not None and row.temporal_workflow_id:
            await client.get_workflow_handle(row.temporal_workflow_id).cancel()
            row.status="cancelled"; row.completed_at=datetime.now(timezone.utc)
            await append_run_event(db,row.id,"run_cancelled",{"requested_by":"operator"})
        else:
            row.status="cancelled"; row.completed_at=datetime.now(timezone.utc); await append_run_event(db,row.id,"run_cancelled",{})
        await audit_mutation(db,actor.workspace_id,actor,"run.cancel_requested","agent_run",row.id)
    return row

@router.post("/agents/{agent_id}/forecast",response_model=ForecastResponse)
async def forecast(agent_id:UUID,db=Depends(get_db),actor=Depends(actor_dep)):
    triggers=(await db.execute(select(AgentTrigger).where(AgentTrigger.agent_id==agent_id,AgentTrigger.workspace_id==actor.workspace_id,AgentTrigger.is_active.is_(True)))).scalars().all(); daily=0.0
    for t in triggers:
        if t.trigger_type=="schedule":
            try:
                from datetime import timedelta
                occurrences=preview(t.config["cron"],t.config.get("timezone","UTC"),2000)["occurrences"]
                now=datetime.now(timezone.utc); daily += sum(1 for item in occurrences if now <= item < now+timedelta(days=1))
            except (KeyError,ValueError): pass
    return ForecastResponse(frequency_per_day=daily,estimated_runs=daily,estimated_model_calls=daily,estimated_tool_calls=0,assumptions=["cron occurrences counted over the next 24 hours","one model call per run unless observed usage is available","pure built-in tools only","budget limits are not changed by forecasting"])

@router.get("/audit-events", response_model=AuditPage)
async def audit_events(db=Depends(get_db),actor=Depends(actor_dep),limit:int=50,after:str|None=None):
    q=select(AuditEvent).where(AuditEvent.workspace_id==actor.workspace_id).order_by(desc(AuditEvent.created_at),desc(AuditEvent.id)).limit(min(limit,200))
    if after:
        stamp,raw_id=decode_cursor(after); parsed=datetime.fromisoformat(stamp); q=q.where(or_(AuditEvent.created_at < parsed,and_(AuditEvent.created_at==parsed,AuditEvent.id < UUID(raw_id))))
    rows=(await db.execute(q)).scalars().all(); return {"items":[{"id":row.id,"event_type":row.action,"resource_type":row.resource_type,"resource_id":row.resource_id,"metadata":row.metadata_ or {},"created_at":row.created_at} for row in rows],"next_cursor":encode_cursor([rows[-1].created_at.isoformat(),str(rows[-1].id)]) if len(rows)==min(limit,200) else None}

@router.websocket("/runs/{run_id}/events/ws")
async def run_events_ws(websocket:WebSocket,run_id:UUID):
    from app.security import authenticate_websocket
    from app.security import require_autonomy_feature
    from app.database import AsyncSessionLocal
    import asyncio, time
    try: require_autonomy_feature("autonomy_enabled")
    except HTTPException:
        await websocket.close(code=1008); return
    actor=await authenticate_websocket(websocket)
    if actor is None:return
    await websocket.accept(); after=int(websocket.query_params.get("after",0)); started=time.monotonic()
    try:
        while time.monotonic()-started < 600:
            async with AsyncSessionLocal() as db:
                rows=(await db.execute(select(AgentRunEvent).join(AgentRun,AgentRun.id==AgentRunEvent.run_id).where(AgentRunEvent.run_id==run_id,AgentRun.workspace_id==actor.workspace_id,AgentRunEvent.sequence>after).order_by(AgentRunEvent.sequence).limit(200))).scalars().all()
            for row in rows:
                await websocket.send_json({"sequence":row.sequence,"event_type":row.event_type,"payload":row.payload,"created_at":row.created_at.isoformat() if row.created_at else None}); after=row.sequence
            await asyncio.sleep(.5)
    except WebSocketDisconnect: return


# ---- Adaptive agent heartbeat supervision -----------------------------------

@router.get("/agents/{agent_id}/heartbeat", response_model=HeartbeatResponse)
async def get_heartbeat(agent_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    from app.agents.heartbeat_service import _ensure_heartbeat_row
    agent = await db.scalar(select(Agent).where(Agent.id == agent_id, Agent.workspace_id == actor.workspace_id))
    if not agent:
        raise HTTPException(404, "agent not found")
    if agent.is_system:
        raise HTTPException(409, "the Thread moderator does not use heartbeats")
    row = await _ensure_heartbeat_row(db, agent)
    if row.updated_at is None:
        await db.refresh(row)
    return row


@router.put("/agents/{agent_id}/heartbeat", response_model=HeartbeatResponse)
async def put_heartbeat(
    agent_id: UUID,
    body: HeartbeatConfigUpsert,
    request: Request,
    db: AsyncSession = Depends(get_db),
    actor=Depends(actor_dep),
):
    from app.agents.heartbeat_service import upsert_heartbeat_config, heartbeat_workflow_id
    from app.models.agent_models import AgentHeartbeat
    agent = await db.scalar(select(Agent).where(Agent.id == agent_id, Agent.workspace_id == actor.workspace_id))
    if not agent:
        raise HTTPException(404, "agent not found")
    if agent.is_system:
        raise HTTPException(409, "the Thread moderator does not use heartbeats")
    if agent.status == "archived":
        raise HTTPException(409, "archived agent cannot receive heartbeat config")
    try:
        row = await upsert_heartbeat_config(
            db, agent,
            enabled=body.enabled,
            min_wake_seconds=body.min_wake_seconds,
            max_wake_seconds=body.max_wake_seconds,
            idle_backoff_factor=body.idle_backoff_factor,
            expected_revision=body.expected_revision,
        )
    except HTTPException:
        raise
    row.workflow_id = heartbeat_workflow_id(agent.id)
    await audit_mutation(db, actor.workspace_id, actor, "agent.heartbeat_updated", "agent", agent.id, body.model_dump(mode="json"))
    await db.commit()
    await db.refresh(row)
    # Best-effort Temporal signal/start; desired state already persisted.
    if body.enabled:
        from app.api.routes import get_temporal_client
        from app.workflows.heartbeat_workflow import AgentHeartbeatWorkflow
        client = get_temporal_client()
        if client is not None:
            workflow_id = heartbeat_workflow_id(agent.id)
            handle = client.get_workflow_handle(workflow_id)
            try:
                await handle.signal(AgentHeartbeatWorkflow.configuration_changed)
            except Exception:
                try:
                    await client.start_workflow(
                        AgentHeartbeatWorkflow.run,
                        {"agent_id": str(agent.id), "workspace_id": str(agent.workspace_id)},
                        id=workflow_id,
                        task_queue="threadbot-agent",
                    )
                except Exception:
                    # Reconciliation loop will recover this.
                    pass
    return row


@router.post("/agents/{agent_id}/heartbeat/wake", response_model=HeartbeatResponse)
async def wake_heartbeat(agent_id: UUID, db: AsyncSession = Depends(get_db), actor=Depends(actor_dep)):
    from app.agents.heartbeat_service import _ensure_heartbeat_row, heartbeat_workflow_id
    from app.config import load_settings_from_db
    from app.security import autonomy_flags
    agent = await db.scalar(select(Agent).where(Agent.id == agent_id, Agent.workspace_id == actor.workspace_id))
    if not agent:
        raise HTTPException(404, "agent not found")
    if agent.is_system:
        raise HTTPException(409, "the Thread moderator does not use heartbeats")
    if agent.status != "active":
        raise HTTPException(409, f"agent is {agent.status}")
    if not agent.active_version_id:
        raise HTTPException(409, "agent has no active version")
    await load_settings_from_db()
    if not autonomy_flags().get("autonomy_enabled", False):
        raise HTTPException(409, "autonomy is disabled")
    row = await _ensure_heartbeat_row(db, agent)
    if not row.enabled:
        raise HTTPException(409, "heartbeat is disabled")
    await db.commit()
    await db.refresh(row)
    from app.api.routes import get_temporal_client
    from app.workflows.heartbeat_workflow import AgentHeartbeatWorkflow
    client = get_temporal_client()
    if client is not None:
        workflow_id = heartbeat_workflow_id(agent.id)
        handle = client.get_workflow_handle(workflow_id)
        try:
            await handle.signal(AgentHeartbeatWorkflow.wake_now)
        except Exception:
            try:
                await client.start_workflow(
                    AgentHeartbeatWorkflow.run,
                    {"agent_id": str(agent.id), "workspace_id": str(agent.workspace_id)},
                    id=workflow_id,
                    task_queue="threadbot-agent",
                )
            except Exception:
                pass
    return row
