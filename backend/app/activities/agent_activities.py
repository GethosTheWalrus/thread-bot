"""Activities shared by the autonomy orchestration workflows."""
from temporalio.activity import defn

@defn
async def load_agent_run(args):
    from uuid import UUID, uuid4
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.run_models import AgentRun
    from app.models.agent_models import AgentVersion, TriggerEvent, AgentTrigger, Agent
    async with AsyncSessionLocal() as db:
        run=await db.scalar(select(AgentRun).where(AgentRun.id==UUID(str(args["run_id"]))))
        if not run: return {"found":False}
        version=await db.get(AgentVersion,run.agent_version_id)
        event=await db.get(TriggerEvent, run.trigger_event_id) if run.trigger_event_id else None
        trigger=await db.get(AgentTrigger, event.trigger_id) if event and event.trigger_id else None
        agent = await db.get(Agent, run.agent_id)
        from app.config import get_llm_config, apply_thread_llm_overrides, get_settings
        from app.models.models import Thread, DiscordThreadLink
        thread = await db.get(Thread, run.thread_id)
        effective_config = dict(get_llm_config())
        if thread and thread.llm_overrides:
            effective_config = apply_thread_llm_overrides(effective_config, thread.llm_overrides)
        effective_config.update(dict(version.config or {}))
        effective_config["system_prompt"] = version.prompt_template or ""
        selected_skills = []
        requested_skills = {str(item) for item in (version.skill_selection or [])} if version else set()
        if requested_skills:
            from app.models.models import Skill
            skills = (await db.execute(select(Skill).where(Skill.is_active.is_(True)))).scalars().all()
            selected_skills = [{"name": skill.name, "description": skill.description or "", "content": skill.content} for skill in skills if str(skill.id) in requested_skills or skill.name in requested_skills]
        effective_config["skills"] = selected_skills
        link = await db.scalar(select(DiscordThreadLink).where(DiscordThreadLink.thread_id == run.thread_id, DiscordThreadLink.is_active.is_(True)))
        if link and get_settings().DISCORD_ENABLED:
            effective_config["discord"] = {"enabled": True, "bot_token": get_settings().DISCORD_BOT_TOKEN, "guild_id": link.guild_id, "channel_id": link.channel_id, "discord_thread_id": link.discord_thread_id, "discord_thread_name": link.discord_thread_name}
        budget={}
        if version and version.budget_profile_id:
            from app.models.budget_models import BudgetProfile
            profile=await db.get(BudgetProfile,version.budget_profile_id); budget=(profile.limits or {}) if profile else {}
        from app.temporal_client import autonomy_search_attributes
        from app.security import security_mode
        return {"found":True,"run_id":str(run.id),"workspace_id":str(run.workspace_id),"agent_id":str(run.agent_id),"thread_id":str(run.thread_id),"version_id":str(version.id),"version_config":version.config,"llm_config":effective_config,"chat_task_queue":get_settings().TEMPORAL_TASK_QUEUE,"prompt_template":version.prompt_template,"tool_selection":version.tool_selection,"skill_selection":version.skill_selection,"selected_skills":selected_skills or (version.config or {}).get("selected_skills", []),"credential_bindings":version.credential_bindings,"agent_name":agent.name if agent else None,"agent_handle":agent.handle if agent else None,"policy_version":str(version.policy_set_id or "default"),"connector_id":(trigger.config or {}).get("connector_id") if trigger else None,"subject":(event.subject or {}) if event else {},"response_mode":((event.payload or {}).get("response_mode", "both") if event else "both"),"origin":(event.payload or {}) if event else {},"agent_status":agent.status if agent else "archived","status":run.status,"mode":run.mode,"route":run.route or "","input_message_id":str(run.input_message_id) if run.input_message_id else None,"authentication_method":"admin_token" if security_mode() == "admin_token" else "local","search_attributes":autonomy_search_attributes(str(run.workspace_id), str(run.agent_id), run.mode),"deadline_at":run.deadline_at.isoformat() if run.deadline_at else None,"budget_snapshot":run.budget_snapshot or budget,"budget_profile_id":str(version.budget_profile_id) if version and version.budget_profile_id else None}

@defn
async def materialize_trigger_event(args):
    """Materialize a scheduled occurrence exactly once before coordinator signaling."""
    from app.config import load_settings_from_db
    from app.security import autonomy_flags
    await load_settings_from_db()
    if not autonomy_flags().get("autonomy_enabled", False):
        return {"created": False, "reason": "autonomy is disabled"}
    from uuid import UUID
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent_models import AgentTrigger, Agent
    from app.database.autonomy import create_trigger_event
    async with AsyncSessionLocal() as db:
        if args.get("event_id") and not args.get("trigger_id"):
            from app.models.agent_models import TriggerEvent, Agent
            event=await db.scalar(select(TriggerEvent).where(TriggerEvent.id==UUID(str(args["event_id"]))))
            agent=await db.get(Agent,event.agent_id) if event else None
            return {"created":bool(event and agent),"event_id":str(event.id) if event else None,"agent_id":str(agent.id) if agent else None,"queue_limit":agent.queue_limit if agent else 0}
        trigger=await db.scalar(select(AgentTrigger).where(AgentTrigger.id==UUID(str(args["trigger_id"])),AgentTrigger.is_active.is_(True)))
        if not trigger: return {"created":False,"reason":"trigger inactive"}
        agent=await db.get(Agent,trigger.agent_id)
        if not agent or agent.status in {"archived","paused"}: return {"created":False,"reason":"agent paused or archived"}
        occurrence=args.get("scheduled_at") or args.get("occurrence") or datetime.now(timezone.utc).isoformat()
        event,created=await create_trigger_event(db,workspace_id=trigger.workspace_id,agent_id=agent.id,trigger_id=trigger.id,schema_version=1,source="schedule",event_type="schedule.occurrence",subject={},occurred_at=datetime.fromisoformat(occurrence),dedupe_key=f"schedule:{trigger.id}:{occurrence}",correlation_id=UUID(str(args.get("correlation_id",trigger.id))),causation_id=None,origin_chain=[],trust="trusted_metadata",payload={"scheduled_at":occurrence},content_refs=[])
        await db.commit(); return {"created":created,"event_id":str(event.id),"agent_id":str(agent.id),"queue_limit":agent.queue_limit}

@defn
async def claim_event_run(args):
    from uuid import UUID
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent_models import TriggerEvent, Agent, AgentVersion
    from app.models.run_models import AgentRun
    from app.models.agent_models import AgentVersion
    from app.models.models import Message
    from app.database.autonomy import append_run_event
    async with AsyncSessionLocal() as db:
        event=await db.scalar(select(TriggerEvent).where(TriggerEvent.id==UUID(str(args["event_id"]))).with_for_update())
        if not event:return {"created":False,"reason":"event missing"}
        existing=await db.scalar(select(AgentRun).where(AgentRun.trigger_event_id==event.id))
        if existing:return {"created":False,"run_id":str(existing.id)}
        agent=await db.get(Agent,event.agent_id); version=await db.get(AgentVersion,agent.active_version_id) if agent and agent.active_version_id else None
        if not agent or not version:return {"created":False,"reason":"agent has no active version"}
        if agent.status != "active": return {"created":False,"reason":f"agent is {agent.status}"}
        payload = event.payload or {}
        run=AgentRun(workspace_id=event.workspace_id,agent_id=agent.id,agent_version_id=version.id,thread_id=agent.thread_id,trigger_event_id=event.id,correlation_id=event.correlation_id,mode="live",origin_id=payload.get("origin_id"),origin_message_id=payload.get("origin_message_id")); db.add(run); await db.flush()
        message=(event.payload or {}).get("message",f"Scheduled run at {(event.payload or {}).get('scheduled_at','')}" )
        input_message_id = payload.get("input_message_id")
        input_row = await db.get(Message, UUID(str(input_message_id))) if input_message_id else None
        if input_row is not None:
            if input_row.thread_id != agent.thread_id:
                return {"created":False,"reason":"input message does not belong to agent thread"}
            input_row.metadata_ = {**(input_row.metadata_ or {}), "autonomy_run_id": str(run.id), "untrusted_trigger": True, "trigger_event_id": str(event.id), "agent_id": str(agent.id)}
            run.input_message_id = input_row.id
        else:
            input_row = Message(thread_id=agent.thread_id,role="user",content=message,metadata_={"autonomy_run_id":str(run.id),"untrusted_trigger":True,"trigger_event_id":str(event.id),"agent_id":str(agent.id)})
            db.add(input_row); await db.flush(); run.input_message_id = input_row.id
        await append_run_event(db,run.id,"run_queued",{"source":event.source,"input_message_id":str(run.input_message_id)}); await db.commit()
        run_ids = [str(run.id)]
        from app.models.phase4_models import CanaryDeployment, CanaryAssignment
        from app.services.phase4 import cohort_matches
        deployment = await db.scalar(select(CanaryDeployment).where(
            CanaryDeployment.workspace_id == event.workspace_id,
            CanaryDeployment.agent_id == agent.id,
            CanaryDeployment.status == "active",
        ).order_by(CanaryDeployment.created_at.desc()))
        cohort = dict(deployment.cohort or {}) if deployment else None
        if deployment and cohort_matches({**cohort, "deployment_id": str(deployment.id)}, event):
            shadow = AgentRun(workspace_id=event.workspace_id, agent_id=agent.id,
                agent_version_id=deployment.candidate_version_id, thread_id=agent.thread_id,
                trigger_event_id=event.id, source_run_id=run.id,
                source_trigger_event_id=event.id, correlation_id=event.correlation_id,
                causation_id=run.id, mode="canary_shadow", status="queued",
                budget_snapshot=run.budget_snapshot or {},
                usage_summary={"shadow_of": str(run.id), "effect_free": True})
            db.add(shadow); await db.flush()
            db.add(CanaryAssignment(workspace_id=event.workspace_id, deployment_id=deployment.id,
                run_id=shadow.id, bucket="canary", assigned_version_id=deployment.candidate_version_id))
            shadow.input_message_id = run.input_message_id
            await append_run_event(db, shadow.id, "run_queued", {"mode": "canary_shadow", "source_run_id": str(run.id)})
            await db.commit()
            run_ids.append(str(shadow.id))
        return {"created":True,"run_id":str(run.id),"run_ids":run_ids,"agent_id":str(agent.id),"queue_limit":agent.queue_limit}

@defn
async def suppress_event(args):
    from uuid import UUID
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent_models import TriggerEvent, Agent, AgentVersion
    from app.models.run_models import AgentRun
    from app.database.autonomy import append_run_event
    async with AsyncSessionLocal() as db:
        event=await db.scalar(select(TriggerEvent).where(TriggerEvent.id==UUID(str(args["event_id"]))))
        if not event:return {"suppressed":False}
        existing=await db.scalar(select(AgentRun).where(AgentRun.trigger_event_id==event.id))
        if existing:return {"suppressed":True,"run_id":str(existing.id)}
        agent=await db.get(Agent,event.agent_id); version=await db.get(AgentVersion,agent.active_version_id) if agent and agent.active_version_id else None
        if not agent or not version:return {"suppressed":False}
        run=AgentRun(workspace_id=event.workspace_id,agent_id=agent.id,agent_version_id=version.id,thread_id=agent.thread_id,trigger_event_id=event.id,correlation_id=event.correlation_id,mode="live",status="suppressed",failure_code="queue_overflow",failure_summary="coordinator queue limit exceeded"); db.add(run); await db.flush(); await append_run_event(db,run.id,"run_suppressed",{"reason":"queue_overflow"})
        from app.models.foundation_models import AuditEvent, DomainEvent
        db.add(AuditEvent(workspace_id=event.workspace_id, actor_type="system", actor_id="coordinator", action="run.suppressed", resource_type="agent_run", resource_id=str(run.id), metadata_={"reason":"queue_overflow"}, correlation_id=event.correlation_id))
        db.add(DomainEvent(workspace_id=event.workspace_id, event_type="run.suppressed", payload={"run_id":str(run.id),"reason":"queue_overflow"}, dedupe_key=f"run.suppressed:{run.id}", correlation_id=event.correlation_id))
        await db.commit(); return {"suppressed":True,"run_id":str(run.id)}

@defn
async def mark_run_workflow(args):
    from uuid import UUID
    from sqlalchemy import update
    from app.database import AsyncSessionLocal
    from app.models.run_models import AgentRun
    async with AsyncSessionLocal() as db:
        await db.execute(update(AgentRun).where(AgentRun.id==UUID(str(args["run_id"]))).values(temporal_workflow_id=args["workflow_id"]))
        await db.commit(); return {"ok":True}

@defn
async def fail_run(args):
    from uuid import UUID
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.run_models import AgentRun
    from app.database.autonomy import append_run_event
    async with AsyncSessionLocal() as db:
        run=await db.scalar(select(AgentRun).where(AgentRun.id==UUID(str(args["run_id"]))).with_for_update())
        if run and run.status not in {"succeeded","failed","cancelled","exhausted","timed_out","suppressed","dead_lettered","outcome_unknown"}:
            run.status="failed"; run.failure_code=args.get("failure_code","dispatch_failed"); run.failure_summary=args.get("reason"); run.completed_at=datetime.now(timezone.utc); await append_run_event(db,run.id,"run_failed",{"reason":run.failure_summary})
        await db.commit(); return {"status":run.status if run else "failed"}

@defn
async def persist_runtime_snapshot(args):
    from uuid import UUID
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent_models import AgentVersion
    from app.agents.autonomy_service import create_runtime_snapshot
    async with AsyncSessionLocal() as db:
        version=await db.get(AgentVersion,UUID(str(args["version_id"])))
        row=await create_runtime_snapshot(db,UUID(str(args["workspace_id"])),version,args.get("model_config") or {},args.get("credential_binding_id"))
        await db.commit(); return {"runtime_snapshot_id":str(row.id)}

@defn
async def project_run_terminal(args):
    from uuid import UUID
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.run_models import AgentRun
    from app.models.agent_models import AgentVersion, TriggerEvent
    from app.models.phase2_models import NotificationRoute
    from app.notifications.service import enqueue_delivery
    from app.database.autonomy import append_run_event
    from app.models.phase4_models import CanaryAssignment
    from app.services.phase4 import write_canary_comparison
    async with AsyncSessionLocal() as db:
        run=await db.scalar(select(AgentRun).where(AgentRun.id==UUID(str(args["run_id"]))).with_for_update())
        if not run: return {"status":"failed", "delivery_ids": []}
        terminal={"succeeded","exhausted","timed_out","cancelled","failed","suppressed","dead_lettered","outcome_unknown"}
        if run.status not in terminal:
            run.status=args.get("status","failed")
            from datetime import datetime, timezone
            run.completed_at=datetime.now(timezone.utc)
            if run.status=="failed":
                run.failure_code=args.get("failure_code","runtime_failed"); run.failure_summary=args.get("output_summary")
        run.output_summary=args.get("output_summary") or run.output_summary
        await append_run_event(db,run.id,"run_terminal",{"status":run.status})
        assignment = await db.scalar(select(CanaryAssignment).where(CanaryAssignment.run_id == run.id))
        if assignment:
            stable = await db.get(AgentRun, run.source_run_id)
            metrics = {"candidate_status": run.status, "candidate_output": run.output_summary or "",
                       "stable_status": stable.status if stable else None,
                       "stable_output": stable.output_summary if stable else None,
                       "effect_free": True}
            await write_canary_comparison(db, run.workspace_id, assignment.deployment_id,
                                          run.id, stable.id if stable else None, metrics)
        delivery_ids = []
        if run.mode == "live":
            version = await db.get(AgentVersion, run.agent_version_id)
            profile_id = (version.config or {}).get("notification_profile_id") if version else None
            if profile_id:
                routes = (await db.execute(select(NotificationRoute).where(NotificationRoute.profile_id == UUID(str(profile_id)), NotificationRoute.is_active.is_(True)))).scalars().all()
                payload = {"run_id": str(run.id), "status": run.status, "message": run.output_summary or "", "event_type": "run.terminal", "mode": run.mode}
                for route in routes:
                    delivery, _ = await enqueue_delivery(db, run.workspace_id, "run.terminal", {"channel": route.channel, "config": route.config, "filters": route.filters, "credential_binding_id": str(route.credential_binding_id) if route.credential_binding_id else None}, payload, f"run:{run.id}:run.terminal:{route.id}:1", route.profile_id)
                    delivery_ids.append(str(delivery.id))
                    await append_run_event(db, run.id, "notification_queued", {"delivery_id": str(delivery.id), "channel": route.channel})
        await db.commit(); return {"status":run.status, "delivery_ids": delivery_ids}

@defn
async def recover_coordinator_queue(args):
    from uuid import UUID
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.run_models import AgentRun
    async with AsyncSessionLocal() as db:
        from app.models.agent_models import Agent
        agent=await db.get(Agent,UUID(str(args["agent_id"])))
        rows=(await db.execute(select(AgentRun.trigger_event_id).where(AgentRun.agent_id==UUID(str(args["agent_id"])),AgentRun.status=="queued",AgentRun.trigger_event_id.is_not(None)).order_by(AgentRun.queued_at).limit(int(args.get("limit",100))))).scalars().all()
        return {"run_ids":[str(x) for x in rows],"queue_limit":agent.queue_limit if agent else 100}

@defn
async def recover_thread_queue(args):
    from uuid import UUID
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.run_models import AgentRun
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(AgentRun.id).where(
            AgentRun.thread_id == UUID(str(args["thread_id"])),
            AgentRun.workspace_id == UUID(str(args["workspace_id"])),
            AgentRun.status == "queued"
        ).order_by(AgentRun.queued_at).limit(int(args.get("limit", 100))))).scalars().all()
        return {"run_ids": [str(x) for x in rows]}

@defn
async def route_agent_output(args):
    """Route one completed assistant output without creating a duplicate user row."""
    from uuid import UUID
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.models import Message, Thread
    from app.models.agent_models import Agent, AgentVersion, TriggerEvent
    from app.models.run_models import AgentRun
    from app.agent_mentions import parse_agent_mention
    from app.database.autonomy import append_run_event, create_trigger_event
    from app.agents.autonomy_service import _now
    async with AsyncSessionLocal() as db:
        source = await db.scalar(select(AgentRun).where(AgentRun.id == UUID(str(args["run_id"]))).with_for_update())
        if not source or source.status != "succeeded" or not source.output_summary:
            return {"routed": False, "reason": "not_successful"}
        existing = await db.scalar(select(AgentRun).where(AgentRun.parent_run_id == source.id, AgentRun.route == "agent_mention"))
        if existing:
            return {"routed": True, "run_id": str(existing.id), "duplicate": True}
        thread = await db.get(Thread, source.thread_id)
        roster = list((await db.execute(select(Agent).where(
            Agent.thread_id == source.thread_id, Agent.status == "active").order_by(Agent.created_at))).scalars())
        result = parse_agent_mention(source.output_summary, [a.handle for a in roster], current_handle=next((a.handle for a in roster if a.id == source.agent_id), None))
        if not result.target_handle:
            reason = "self" if result.user_mentioned else "no_target"
            await append_run_event(db, source.id, "agent_output_not_routed", {"reason": reason})
            await db.commit()
            return {"routed": False, "reason": reason}
        target = next((a for a in roster if a.handle.casefold() == result.target_handle.casefold()), None)
        limit = min(8, max(1, int(getattr(thread, "agent_turn_limit", 4) or 4)))
        if source.depth >= limit:
            await append_run_event(db, source.id, "agent_output_not_routed", {"reason": "bounded", "depth": source.depth, "limit": limit})
            await db.commit()
            return {"routed": False, "reason": "bounded"}
        if not target or not target.active_version_id:
            await append_run_event(db, source.id, "agent_output_not_routed", {"reason": "target_unavailable"})
            await db.commit()
            return {"routed": False, "reason": "target_unavailable"}
        version = await db.get(AgentVersion, target.active_version_id)
        if not version:
            return {"routed": False, "reason": "target_unavailable"}
        event, created = await create_trigger_event(db, id=uuid4(), workspace_id=source.workspace_id,
            agent_id=target.id, trigger_id=None, schema_version=1, source="agent_mention",
            event_type="agent.output.mention", subject={"source_run_id": str(source.id)}, occurred_at=_now(),
            dedupe_key=f"agent-output:{source.id}", correlation_id=source.correlation_id,
            causation_id=source.id, origin_chain=[], trust="trusted_metadata",
            payload={"message": source.output_summary, "route": "agent_mention"}, content_refs=[])
        if not created:
            await db.commit(); return {"routed": True, "duplicate": True}
        run = AgentRun(workspace_id=source.workspace_id, agent_id=target.id, agent_version_id=version.id,
            thread_id=source.thread_id, trigger_event_id=event.id, correlation_id=source.correlation_id,
            causation_id=source.id, parent_run_id=source.id, root_run_id=source.root_run_id or source.id,
            depth=source.depth + 1, route="agent_mention", origin_id=source.origin_id,
            origin_message_id=source.origin_message_id, mode=source.mode)
        db.add(run); await db.flush()
        output_message = await db.scalar(select(Message).where(Message.thread_id == source.thread_id,
            Message.agent_run_id == source.id, Message.role == "assistant").order_by(Message.created_at.desc()))
        if output_message:
            run.input_message_id = output_message.id
        await append_run_event(db, source.id, "agent_output_routed", {"target_agent_id": str(target.id), "run_id": str(run.id)})
        await append_run_event(db, run.id, "run_queued", {"route": "agent_mention", "parent_run_id": str(source.id)})
        await db.commit()
        return {"routed": True, "run_id": str(run.id), "thread_id": str(run.thread_id)}
