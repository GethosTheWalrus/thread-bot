"""Transactional Phase 1 autonomy application services."""
from datetime import datetime, timezone
import re
from uuid import UUID, uuid4
from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.autonomy_hashing import canonical_hash
from app.models.models import Thread, Message, Skill
from app.models.agent_models import Agent, AgentTemplate, AgentTemplateVersion, AgentVersionDraft, AgentVersion, AgentTrigger, TriggerEvent
from app.models.run_models import AgentRun, AgentRunEvent
from app.models.runtime_models import RuntimeConfigSnapshot
from app.models.foundation_models import AuditEvent, DomainEvent, IdempotencyRecord
from app.database.autonomy import append_run_event

def _now(): return datetime.now(timezone.utc)
def _workspace(row, workspace_id):
    if row is None or row.workspace_id != workspace_id: raise LookupError("resource not found")
    return row

_RESERVED_HANDLES = {"user", "threadbot", "everyone", "here", "moderator"}

def generated_agent_handle(name: str) -> str:
    handle = re.sub(r"[^a-z0-9_-]+", "_", name.lower()).strip("_-")[:32]
    if not handle or not handle[0].isalpha():
        handle = f"agent_{handle}"[:32] if handle else "agent"
    if handle in _RESERVED_HANDLES:
        handle = f"agent_{handle}"[:32]
    return handle

async def create_agent(db:AsyncSession, workspace_id:UUID, actor, values:dict):
    thread_id = values.pop("thread_id", None)
    if thread_id:
        thread = await db.scalar(select(Thread).where(Thread.id == thread_id))
        if not thread: raise LookupError("thread not found")
        existing = await db.scalar(select(Agent).where(Agent.thread_id == thread_id, Agent.status != "archived"))
        if existing and existing.workspace_id != workspace_id: raise LookupError("thread not found")
    else:
        thread=Thread(title=values["name"], mode="agent", workspace_id=workspace_id); db.add(thread); await db.flush()
    thread.mode = "agent"
    thread.workspace_id = workspace_id
    values["handle"] = values.get("handle") or generated_agent_handle(values["name"])
    values["is_moderator"] = not bool(await db.scalar(select(Agent.id).where(Agent.thread_id == thread.id)))
    row=Agent(workspace_id=workspace_id,thread_id=thread.id,created_by_type=actor.actor_type.value,created_by_id=actor.actor_id,**values); db.add(row); await db.flush()
    return row

async def list_thread_agents(db, workspace_id, thread_id):
    return list((await db.execute(select(Agent).where(Agent.workspace_id == workspace_id, Agent.thread_id == thread_id).order_by(Agent.is_moderator.desc(), Agent.created_at))).scalars().all())

async def set_thread_moderator(db, workspace_id, thread_id, agent_id):
    rows = await list_thread_agents(db, workspace_id, thread_id)
    if not any(row.id == agent_id for row in rows): raise LookupError("agent not found in thread")
    target = next(row for row in rows if row.id == agent_id)
    if target.status == "archived":
        raise ValueError("archived agent cannot be moderator")
    # Clear first and flush: the partial unique moderator index must never see
    # two moderators during a replacement transaction.
    for row in rows: row.is_moderator = False
    await db.flush()
    target.is_moderator = True
    await db.flush()
    return target

async def archive_thread_agent(db, workspace_id, thread_id, agent_id):
    rows = await list_thread_agents(db, workspace_id, thread_id)
    row = next((item for item in rows if item.id == agent_id), None)
    if row is None: raise LookupError("agent not found in thread")
    if row.is_moderator:
        replacement = next((item for item in rows if item.id != row.id and item.status != "archived"), None)
        if replacement is None:
            raise ValueError("moderator replacement required")
        row.is_moderator = False
        await db.flush()
        replacement.is_moderator = True
    row.status = "archived"
    await db.flush()
    return row

async def audit(db, workspace_id, actor, action, resource_type, resource_id, payload=None):
    db.add(AuditEvent(workspace_id=workspace_id,actor_type=actor.actor_type.value,actor_id=actor.actor_id,action=action,resource_type=resource_type,resource_id=str(resource_id) if resource_id else None,metadata_=payload or {},correlation_id=actor.correlation_id))

async def domain_event(db, workspace_id, actor, event_type, payload, dedupe_key):
    db.add(DomainEvent(workspace_id=workspace_id,event_type=event_type,payload=payload,dedupe_key=f"{dedupe_key}:{actor.correlation_id}",correlation_id=actor.correlation_id))

async def audit_mutation(db, workspace_id, actor, action, resource_type, resource_id, payload=None):
    await audit(db,workspace_id,actor,action,resource_type,resource_id,payload)
    await domain_event(db,workspace_id,actor,action,payload or {},f"{action}:{resource_id}")

async def upsert_draft(db:AsyncSession, agent_id:UUID, workspace_id:UUID, payload:dict):
    agent=_workspace(await db.scalar(select(Agent).where(Agent.id==agent_id)),workspace_id)
    draft=await db.scalar(select(AgentVersionDraft).where(AgentVersionDraft.agent_id==agent_id).with_for_update())
    expected=payload["optimistic_lock_version"]
    if draft:
        if draft.version != expected: raise ValueError("optimistic lock conflict")
        draft.version += 1
        for key in ("schema_version","config","prompt_template","tool_selection","skill_selection","credential_bindings"): setattr(draft,key,payload[key])
        draft.config_hash=canonical_hash({k:payload[k] for k in ("schema_version","config","prompt_template","tool_selection","skill_selection","credential_bindings")})
    else:
        if expected != 1: raise ValueError("optimistic lock conflict")
        draft=AgentVersionDraft(agent_id=agent.id,version=1,config_hash=canonical_hash(payload),**{k:payload[k] for k in ("schema_version","config","prompt_template","tool_selection","skill_selection","credential_bindings")}); db.add(draft)
    await db.flush(); return draft

async def activate_draft(db:AsyncSession, agent_id:UUID, workspace_id:UUID, actor):
    agent=_workspace(await db.scalar(select(Agent).where(Agent.id==agent_id).with_for_update()),workspace_id)
    draft=await db.scalar(select(AgentVersionDraft).where(AgentVersionDraft.agent_id==agent_id))
    if not draft: raise LookupError("draft not found")
    config_hash=canonical_hash({"schema_version":draft.schema_version,"config":draft.config,"prompt_template":draft.prompt_template,"tool_selection":draft.tool_selection,"skill_selection":draft.skill_selection,"credential_bindings":draft.credential_bindings})
    row=await db.scalar(select(AgentVersion).where(AgentVersion.agent_id==agent.id,AgentVersion.config_hash==config_hash))
    if not row:
        max_version=await db.scalar(select(func.max(AgentVersion.version)).where(AgentVersion.agent_id==agent.id)) or 0
        row=AgentVersion(agent_id=agent.id,version=max_version+1,schema_version=draft.schema_version,config=draft.config,prompt_template=draft.prompt_template,tool_selection=draft.tool_selection,skill_selection=draft.skill_selection,credential_bindings=draft.credential_bindings,config_hash=config_hash,created_by_type=actor.actor_type.value,created_by_id=actor.actor_id); db.add(row); await db.flush()
    agent.active_version_id=row.id; agent.status="active"; await db.flush(); return row

async def create_runtime_snapshot(db, workspace_id, version:AgentVersion, model_config:dict, binding_id=None):
    forbidden=("secret","token","password","api_key","ciphertext")
    def contains_secret(value):
        if isinstance(value,dict): return any(any(x in str(k).lower() for x in forbidden) or contains_secret(v) for k,v in value.items())
        if isinstance(value,list): return any(contains_secret(v) for v in value)
        return False
    if contains_secret(model_config): raise ValueError("secret material in runtime config")
    selected = {str(item) for item in (version.skill_selection or [])}
    selected_skills = []
    if selected:
        rows = list((await db.execute(select(Skill).where(Skill.is_active.is_(True)))).scalars())
        selected_skills = [
            {"id": str(skill.id), "name": skill.name, "content": skill.content}
            for skill in rows
            if str(skill.id) in selected or skill.name in selected
        ]
    config={"model":model_config.get("model"),"api_url":model_config.get("api_url"),"temperature":model_config.get("temperature"),"max_tokens":model_config.get("max_tokens"),"tool_selection":list(version.tool_selection or []),"prompt_template":version.prompt_template,"skill_selection":list(version.skill_selection or []),"selected_skills":selected_skills}
    digest=canonical_hash(config); row=await db.scalar(select(RuntimeConfigSnapshot).where(RuntimeConfigSnapshot.workspace_id==workspace_id,RuntimeConfigSnapshot.config_hash==digest))
    if not row: row=RuntimeConfigSnapshot(workspace_id=workspace_id,schema_version=version.schema_version,config=config,model_credential_binding_id=binding_id,config_hash=digest); db.add(row); await db.flush()
    return row

async def create_run(db, workspace_id, actor, agent, version, message, mode="live", trigger_id=None, idempotency_key=None, response_mode="both", message_metadata=None, input_message_id=None, parent_run_id=None, route="user", origin_id=None, origin_message_id=None):
    if not idempotency_key: raise ValueError("Idempotency-Key is required")
    if version is None:
        raise ValueError("agent has no active version")
    old=await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.workspace_id==workspace_id,IdempotencyRecord.key==idempotency_key).with_for_update())
    if old and old.response: return await db.get(AgentRun, UUID(old.response["run_id"]))
    if old: raise ValueError("idempotency key is in progress")
    record=IdempotencyRecord(workspace_id=workspace_id,key=idempotency_key,operation="agent.run")
    try:
        async with db.begin_nested(): db.add(record); await db.flush()
    except IntegrityError:
        existing=await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.workspace_id==workspace_id,IdempotencyRecord.key==idempotency_key))
        if existing and existing.response:return await db.get(AgentRun,UUID(existing.response["run_id"]))
        raise ValueError("idempotency key is in progress")
    from app.database.autonomy import create_trigger_event, create_live_run
    try:
        event, _ = await create_trigger_event(db,id=uuid4(),workspace_id=workspace_id,agent_id=agent.id,trigger_id=trigger_id,schema_version=1,source="manual",event_type="manual.run",subject={},occurred_at=_now(),dedupe_key=idempotency_key,correlation_id=actor.correlation_id,causation_id=None,origin_chain=[],trust="trusted_metadata",payload={"message":message, "response_mode": response_mode},content_refs=[])
        if mode == "live":
            run, created = await create_live_run(db,workspace_id=workspace_id,agent_id=agent.id,agent_version_id=version.id,thread_id=agent.thread_id,trigger_event_id=event.id,correlation_id=actor.correlation_id,mode=mode)
        else:
            run=AgentRun(workspace_id=workspace_id,agent_id=agent.id,agent_version_id=version.id,thread_id=agent.thread_id,trigger_event_id=event.id,correlation_id=actor.correlation_id,mode=mode); db.add(run); await db.flush(); created=True
        if not created: return run
        run.input_message_id = input_message_id
        run.parent_run_id = parent_run_id
        run.root_run_id = parent_run_id or run.id
        run.depth = 0
        if parent_run_id:
            parent = await db.get(AgentRun, parent_run_id)
            run.depth = (parent.depth + 1) if parent else 1
            run.root_run_id = (parent.root_run_id or parent.id) if parent else parent_run_id
        run.route = route
        run.origin_id = origin_id
        run.origin_message_id = origin_message_id
        metadata = dict(message_metadata or {})
        metadata["autonomy_run_id"] = str(run.id)
        if input_message_id is None:
            input_row = Message(thread_id=agent.thread_id, role="user", content=message, metadata_=metadata)
            db.add(input_row); await db.flush(); run.input_message_id = input_row.id
        else:
            input_row = await db.get(Message, input_message_id)
            if input_row is None or input_row.thread_id != agent.thread_id: raise ValueError("input message does not belong to agent thread")
            input_row.metadata_ = {**(input_row.metadata_ or {}), **metadata}
        event.payload = {**(event.payload or {}), "input_message_id": str(run.input_message_id), "origin_id": origin_id, "origin_message_id": origin_message_id}
        await db.flush(); await append_run_event(db,run.id,"run_queued",{"mode":mode}); await audit_mutation(db,workspace_id,actor,"agent.run","agent_run",run.id,{"mode":mode})
        record.status="completed"; record.response={"run_id":str(run.id)}
        return run
    except Exception:
        await db.delete(record)
        await db.flush()
        raise

async def fail_queued_run(db, run_id, reason, code="dispatch_failed"):
    run=await db.scalar(select(AgentRun).where(AgentRun.id==run_id).with_for_update())
    if run and run.status=="queued":
        run.status="failed"; run.failure_code=code; run.failure_summary=reason; run.completed_at=_now(); await append_run_event(db,run.id,"run_failed",{"reason":reason,"code":code})
    return run
