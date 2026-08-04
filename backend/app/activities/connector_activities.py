from temporalio.activity import defn


@defn
async def reconcile_phase2_dead_letters(args: dict | None = None) -> dict:
    from datetime import datetime, timezone
    from sqlalchemy import select, delete
    from app.database import AsyncSessionLocal
    from app.models.phase2_models import DeadLetter
    from app.models.phase2_models import WebhookNonce
    limit = min(int((args or {}).get("limit", 100)), 500)
    async with AsyncSessionLocal() as db:
        await db.execute(delete(WebhookNonce).where(WebhookNonce.expires_at <= datetime.now(timezone.utc)))
        waiting = len(list((await db.execute(select(DeadLetter.id).where(DeadLetter.status == "retry_requested").limit(limit))).scalars()))
        await db.commit()
    return {"requeued": 0, "waiting_for_dispatch": waiting}


@defn
async def poll_connector(args: dict) -> dict:
    from app.effect_policy import is_effect_free_mode
    if is_effect_free_mode(args.get("mode")):
        return {"created": 0, "suppressed": True, "reason": f"connector polling is suppressed in {args['mode']} mode"}
    from sqlalchemy import select
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.models.phase2_models import Connector
    from app.models.phase4_models import QueueControl
    from app.services.phase2 import poll_connector as run_poll, ingest_connector_event
    async with AsyncSessionLocal() as db:
        connector = await db.scalar(select(Connector).where(Connector.id == UUID(str(args["connector_id"])), Connector.is_active.is_(True)))
        if not connector: return {"created": 0, "reason": "connector inactive"}
        control = await db.scalar(select(QueueControl).where(QueueControl.workspace_id == connector.workspace_id, QueueControl.queue_name == "threadbot-connectors"))
        if control and control.state in {"paused", "draining"}:
            return {"created": 0, "reason": f"queue is {control.state}"}
        events, _, reason = await run_poll(db, connector, args.get("subject_key", "default"), min(int(args.get("max_events", 100)), 100))
        created = 0
        for event in events:
            _, was_created, _ = await ingest_connector_event(db, connector, event, agent_id=connector.config.get("agent_id"), trigger_id=connector.config.get("trigger_id"))
            created += int(was_created)
        await db.commit()
    return {"created": created, "reason": reason}
