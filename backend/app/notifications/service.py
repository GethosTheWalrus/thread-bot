from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models.phase2_models import NotificationDelivery


DELIVERY_CLAIM_LEASE_SECONDS = 120


async def enqueue_delivery(db, workspace_id: UUID, event_type: str, route: dict, payload: dict, business_key: str, profile_id=None):
    row = NotificationDelivery(workspace_id=workspace_id, profile_id=profile_id, route=route, event_type=event_type, business_key=business_key, payload=payload)
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
        return row, True
    except IntegrityError:
        return await db.scalar(select(NotificationDelivery).where(NotificationDelivery.workspace_id == workspace_id, NotificationDelivery.business_key == business_key)), False


async def claim_delivery(db, delivery_id: UUID) -> bool:
    row = await db.scalar(select(NotificationDelivery).where(NotificationDelivery.id == delivery_id).with_for_update())
    if not row or row.status not in {"pending", "retry"}: return False
    now = datetime.now(timezone.utc)
    row.status = "sending"
    row.attempts += 1
    row.claimed_at = now
    row.claim_expires_at = now + timedelta(seconds=DELIVERY_CLAIM_LEASE_SECONDS)
    await db.flush()
    return True


async def mark_delivery(db, delivery_id: UUID, success: bool, error: str | None = None):
    row = await db.scalar(select(NotificationDelivery).where(NotificationDelivery.id == delivery_id).with_for_update())
    if row:
        if row.status == "delivered":
            return row
        row.status = "delivered" if success else ("dead_lettered" if row.attempts >= 5 else "retry")
        row.last_error = error
        row.delivered_at = datetime.now(timezone.utc) if success else None
        row.claimed_at = None
        row.claim_expires_at = None
        if not success and row.status == "retry":
            row.available_at = datetime.now(timezone.utc)
    return row
