from temporalio.activity import defn


@defn
async def reconcile_notification_deliveries(args: dict | None = None) -> dict:
    from sqlalchemy import select
    from datetime import datetime, timezone
    from app.database import AsyncSessionLocal
    from app.models.phase2_models import NotificationDelivery
    from app.models.phase4_models import QueueControl
    limit = min(int((args or {}).get("limit", 100)), 500)
    requeued = []
    skipped = 0
    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        rows = list((await db.execute(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == "sending",
                (NotificationDelivery.claim_expires_at.is_(None) | (NotificationDelivery.claim_expires_at < now)),
            )
            .limit(limit)
        )).scalars())
        for row in rows:
            control = await db.scalar(select(QueueControl).where(QueueControl.workspace_id == row.workspace_id, QueueControl.queue_name == "threadbot-notifications"))
            if control and control.state in {"paused", "draining"}:
                skipped += 1
                continue
            row.status = "retry" if row.attempts < 5 else "dead_lettered"
            row.claimed_at = None
            row.claim_expires_at = None
            if row.status == "retry":
                row.available_at = now
                requeued.append(str(row.id))
        await db.commit()
    return {"requeued": len(requeued), "delivery_ids": requeued, "skipped": skipped}


@defn
async def dispatch_notification_delivery(args: dict) -> dict:
    from app.effect_policy import blocked_effect
    if (blocked := blocked_effect(args.get("mode"), "notification")):
        return {"delivered": False, "suppressed": True, "error": blocked}
    from uuid import UUID
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.phase2_models import NotificationDelivery
    from app.models.phase4_models import QueueControl
    from app.notifications.service import claim_delivery, mark_delivery
    from app.notifications.dispatcher import dispatch
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(NotificationDelivery).where(NotificationDelivery.id == UUID(str(args["delivery_id"]))).with_for_update())
        if not row: return {"delivered": False, "error": "delivery missing"}
        control = await db.scalar(select(QueueControl).where(QueueControl.workspace_id == row.workspace_id, QueueControl.queue_name == "threadbot-notifications"))
        if control and control.state in {"paused", "draining"}:
            return {"delivered": False, "suppressed": True, "error": f"queue is {control.state}"}
        if row.status == "delivered": return {"delivered": True, "idempotent": True}
        if not await claim_delivery(db, row.id): return {"delivered": False, "error": "delivery already claimed"}
        await db.commit()
    try:
        credential = None
        if row.route.get("credential_binding_id"):
            from app.credentials.service import resolve_credential_binding
            credential = await resolve_credential_binding(row.route["credential_binding_id"])
        result = await dispatch(row.route, row.payload, credential, mode=row.payload.get("mode"))
        if result.get("delivered") and result.get("write_thread") and row.route.get("config", {}).get("thread_id"):
            from app.models.models import Message
            async with AsyncSessionLocal() as db:
                db.add(Message(thread_id=UUID(str(row.route["config"]["thread_id"])), role="assistant", content=str(row.payload.get("message", "")), metadata_={"notification_delivery_id": str(row.id)}))
                await db.commit()
    except Exception as exc:
        result = {"delivered": False, "error": str(exc)[:500]}
    async with AsyncSessionLocal() as db:
        updated = await mark_delivery(db, UUID(str(args["delivery_id"])), result.get("delivered", False), result.get("error"))
        if updated and updated.status == "dead_lettered":
            from app.models.phase2_models import DeadLetter
            db.add(DeadLetter(workspace_id=updated.workspace_id, stage="notification", reason=result.get("error", "delivery exhausted"), payload={"delivery_id": str(updated.id), "route": updated.route}))
        await db.commit()
    return result
