from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, text, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts import ActorContext, DurableEventContract, redact_secret
from app.models.foundation_models import AuditEvent, DomainEvent, OutboxMessage


async def append_event(db: AsyncSession, event: DurableEventContract, topic: str | None = None, idempotency_key: str | None = None) -> DomainEvent:
    row = DomainEvent(id=event.event_id, workspace_id=event.workspace_id, event_type=event.event_type,
                      payload=redact_secret(event.payload), correlation_id=event.correlation_id,
                      causation_id=event.causation_id)
    db.add(row)
    await db.flush()
    if topic:
        db.add(OutboxMessage(workspace_id=event.workspace_id, event_id=event.event_id, topic=topic,
                             payload=redact_secret(event.payload), idempotency_key=idempotency_key or str(event.event_id)))
    await db.flush()
    # LISTEN/NOTIFY is only a wakeup hint; the rows remain authoritative.
    await db.execute(text("SELECT pg_notify('threadbot_events', :payload)"), {"payload": str(row.sequence)})
    return row


async def append_audit(db: AsyncSession, actor: ActorContext, action: str, resource_type: str | None = None,
                       resource_id: str | None = None, metadata: dict | None = None) -> AuditEvent:
    row = AuditEvent(workspace_id=actor.workspace_id, actor_type=actor.actor_type.value, actor_id=actor.actor_id,
                     action=action, resource_type=resource_type, resource_id=resource_id,
                     metadata_=redact_secret(metadata or {}), correlation_id=actor.correlation_id)
    db.add(row)
    await db.flush()
    return row


async def list_events(db: AsyncSession, workspace_id: UUID, after: int = 0, limit: int = 100) -> list[DomainEvent]:
    result = await db.execute(select(DomainEvent).where(DomainEvent.workspace_id == workspace_id,
        DomainEvent.sequence > after).order_by(DomainEvent.sequence).limit(min(limit, 500)))
    return list(result.scalars())


# Seconds a claimed message may sit without heartbeat before reclamation.
_OUTBOX_STALE_SECS = 300


async def claim_outbox(db: AsyncSession, worker_id: str, limit: int = 50) -> list[OutboxMessage]:
    """Reclaim stale claimed rows, then claim pending work transactionally.

    Callers should commit after dispatch so the status/locked_at transitions
    (stale → pending, pending → claimed) are persisted atomically.
    """
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(seconds=_OUTBOX_STALE_SECS)

    # Step 1 — Reclaim rows whose lease expired (claimed but not updated).
    stale_result = await db.execute(
        select(OutboxMessage)
        .where(
            OutboxMessage.status == "claimed",
            OutboxMessage.locked_at < stale_cutoff,
        )
        .order_by(OutboxMessage.created_at)
        .limit(100)
        .with_for_update(skip_locked=True)
    )
    for row in stale_result.scalars():
        row.status = "pending"
        row.claimed_by = None
        row.locked_at = None

    # Step 2 — Claim fresh work from the now-freed pool.
    result = await db.execute(
        select(OutboxMessage)
        .where(OutboxMessage.status == "pending", OutboxMessage.available_at <= now,
               or_(OutboxMessage.locked_at.is_(None), OutboxMessage.locked_at < now))
        .order_by(OutboxMessage.created_at)
        .limit(min(limit, 500))
        .with_for_update(skip_locked=True)
    )
    rows = list(result.scalars())
    for row in rows:
        row.status = "claimed"
        row.claimed_by = worker_id
        row.locked_at = now
        row.attempts += 1
    await db.flush()
    return rows


async def mark_outbox_published(db: AsyncSession, message_id: UUID, worker_id: str) -> bool:
    result = await db.execute(
        select(OutboxMessage).where(OutboxMessage.id == message_id, OutboxMessage.status == "claimed",
                                   OutboxMessage.claimed_by == worker_id).with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    row.status = "published"
    row.published_at = datetime.now(timezone.utc)
    row.locked_at = None
    return True


async def mark_outbox_failed(db: AsyncSession, message_id: UUID, worker_id: str, error: str,
                             retry_at: datetime | None = None) -> bool:
    result = await db.execute(
        select(OutboxMessage).where(OutboxMessage.id == message_id, OutboxMessage.status == "claimed",
                                   OutboxMessage.claimed_by == worker_id).with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        return False
    row.status = "pending" if retry_at else "failed"
    row.available_at = retry_at or row.available_at
    row.failed_at = datetime.now(timezone.utc)
    row.last_error = error[:2000]
    row.locked_at = None
    return True
