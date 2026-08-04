from temporalio.activity import defn

@defn
async def handoff_to_agent(args):
    from app.effect_policy import blocked_effect
    blocked = blocked_effect(args.get("mode"), "handoff")
    if blocked:
        return {"schema_version": 1, "status": "simulated", "effect_free": True, "output": blocked}
    from types import SimpleNamespace
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.services.phase3 import create_handoff
    from sqlalchemy import select
    from app.models.run_models import AgentRun
    async with AsyncSessionLocal() as db:
        source = await db.scalar(select(AgentRun).where(AgentRun.id == UUID(str(args["run_id"]))))
        blocked = blocked_effect(source.mode if source else args.get("mode"), "handoff")
        if blocked:
            return {"schema_version": 1, "status": "simulated", "effect_free": True, "output": blocked}
        body = SimpleNamespace(contract_id=UUID(str(args["arguments"]["contract_id"])), target_agent_id=UUID(str(args["arguments"]["target_agent_id"])), input_payload=args["arguments"]["input_payload"], origin_chain=args["arguments"].get("origin_chain", []), response_mode=SimpleNamespace(value=args["arguments"].get("response_mode", "async")), idempotency_key=args["arguments"]["idempotency_key"])
        row = await create_handoff(db, UUID(str(args["workspace_id"])), UUID(str(args["run_id"])), body); await db.commit()
        return {"schema_version": 1, "handoff_id": str(row.id), "status": row.status, "target_agent_id": str(row.target_agent_id), "output": row.output_payload}

@defn
async def fire_handoff_escalation(args):
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.services.phase3 import fire_escalation_once
    async with AsyncSessionLocal() as db:
        fired = await fire_escalation_once(db, UUID(str(args["workspace_id"])), UUID(str(args["handoff_id"])), args["stage"], args.get("target_type", "human"), args.get("target_id", "owner"))
        await db.commit(); return {"fired": fired}

@defn
async def complete_handoff(args):
    from uuid import UUID
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.phase3_models import AgentHandoff
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(AgentHandoff).where(AgentHandoff.id == UUID(str(args["handoff_id"]))).with_for_update())
        if not row: return {"completed": False}
        if row.status in {"completed", "failed", "timed_out"}: return {"completed": False, "status": row.status}
        row.status = args.get("status", "completed")
        if args.get("output_payload") is not None: row.output_payload = args["output_payload"]
        row.completed_at = datetime.now(timezone.utc); await db.commit()
        return {"completed": True, "status": row.status}

@defn
async def acknowledge_handoff(args):
    from uuid import UUID
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.phase3_models import AgentHandoff
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(AgentHandoff).where(AgentHandoff.id == UUID(str(args["handoff_id"]))).with_for_update())
        if not row or row.status in {"completed", "failed", "timed_out"}: return {"acknowledged": False}
        if row.acknowledged_at is None: row.acknowledged_at = datetime.now(timezone.utc); row.status = "acknowledged"
        await db.commit(); return {"acknowledged": True}

@defn
async def list_orphan_handoff_slas(args=None):
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.phase3_models import AgentHandoff
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(AgentHandoff).where(AgentHandoff.status.in_(["pending", "acknowledged"])).limit(int((args or {}).get("limit", 100))))).scalars().all()
        now = datetime.now(timezone.utc)
        return [{"handoff_id": str(row.id), "workspace_id": str(row.workspace_id), "acknowledgement_deadline": row.acknowledgement_deadline.isoformat(), "completion_deadline": row.completion_deadline.isoformat(), "expired": row.completion_deadline <= now} for row in rows]
