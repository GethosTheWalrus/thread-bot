from datetime import datetime, timezone, timedelta
from uuid import UUID
from sqlalchemy import select
from app.autonomy_hashing import canonical_hash
from app.models.agent_models import TriggerEvent
from app.models.phase2_models import ConnectorCursor, DeadLetter
from app.database.autonomy import create_trigger_event
from app.security import origin_chain_allows
from app.connectors import HttpJsonConnector, RssConnector, DiscordConnector, TemporalConnector, McpConnector, ReachyConnector


async def ingest_connector_event(db, connector, envelope, *, agent_id=None, trigger_id=None):
    allowed, reason = origin_chain_allows(list(envelope.origin_chain), f"connector:{connector.id}")
    if not allowed:
        return None, False, reason
    event, created = await create_trigger_event(db, workspace_id=connector.workspace_id, agent_id=agent_id, trigger_id=trigger_id, schema_version=1, source=envelope.source, event_type=envelope.event_type, subject=envelope.subject, occurred_at=envelope.occurred_at, dedupe_key=envelope.dedupe_key, correlation_id=envelope.correlation_id, causation_id=envelope.causation_id, origin_chain=list(envelope.origin_chain) + [f"connector:{connector.id}"], trust=envelope.trust, payload=envelope.payload, content_refs=[])
    return event, created, None


async def save_poll_cursor(db, connector, subject_key: str, cursor: dict, fingerprint: str | None):
    row = await db.scalar(select(ConnectorCursor).where(ConnectorCursor.connector_id == connector.id, ConnectorCursor.subject_key == subject_key).with_for_update())
    if not row:
        row = ConnectorCursor(workspace_id=connector.workspace_id, connector_id=connector.id, subject_key=subject_key, cursor=cursor, fingerprint=fingerprint); db.add(row)
    else:
        row.cursor = cursor; row.fingerprint = fingerprint; row.updated_at = datetime.now(timezone.utc)
    await db.flush(); return row


async def poll_connector(db, connector, subject_key: str = "default", max_events: int = 100):
    adapters = {"http_json": HttpJsonConnector, "rss": RssConnector, "discord": DiscordConnector, "temporal": TemporalConnector, "mcp": McpConnector, "reachy": ReachyConnector}
    adapter_type = adapters.get(connector.connector_type)
    if not adapter_type: raise ValueError("connector type is not pollable")
    cursor = await db.scalar(select(ConnectorCursor).where(ConnectorCursor.connector_id == connector.id, ConnectorCursor.subject_key == subject_key).with_for_update())
    now = datetime.now(timezone.utc)
    if cursor and cursor.cooldown_until and cursor.cooldown_until > now:
        cursor.suppressed_count += 1; await db.flush(); return (), cursor, "cooldown"
    result = await adapter_type(connector.config or {}).poll(cursor.cursor if cursor else {})
    if result.unchanged:
        await save_poll_cursor(db, connector, subject_key, result.cursor, result.fingerprint); return (), cursor, "unchanged"
    events = result.events[:max_events]
    cursor = await save_poll_cursor(db, connector, subject_key, result.cursor, result.fingerprint)
    cursor.suppressed_count = 0
    if events:
        if cursor and connector.config.get("cooldown_seconds"):
            cursor.cooldown_until = now + timedelta(seconds=min(int(connector.config["cooldown_seconds"]), 86400))
        await db.flush()
    return events, cursor, None


async def dead_letter(db, workspace_id: UUID, stage: str, reason: str, payload: dict):
    row = DeadLetter(workspace_id=workspace_id, stage=stage, reason=reason, payload=payload); db.add(row); await db.flush(); return row
