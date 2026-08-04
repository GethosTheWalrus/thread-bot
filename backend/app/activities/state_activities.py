from temporalio.activity import defn


@defn
async def capture_connector_snapshot(args: dict) -> dict:
    from uuid import UUID
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.phase2_models import Connector
    from app.connectors import HttpJsonConnector, RssConnector, DiscordConnector, TemporalConnector, McpConnector, ReachyConnector
    from app.state_service import state_snapshot
    adapters = {"http_json": HttpJsonConnector, "rss": RssConnector, "discord": DiscordConnector, "temporal": TemporalConnector, "mcp": McpConnector, "reachy": ReachyConnector}
    async with AsyncSessionLocal() as db:
        connector = await db.scalar(select(Connector).where(Connector.id == UUID(str(args["connector_id"])), Connector.is_active.is_(True)))
        if not connector: return {"supported": False, "reason": "connector missing"}
        snapshot = await adapters[connector.connector_type](connector.config or {}).snapshot(args.get("subject") or {})
        if snapshot is None: return {"supported": False, "reason": "connector does not support snapshots"}
        value = state_snapshot(snapshot)
        from app.models.run_models import AgentStateSnapshot
        row = AgentStateSnapshot(workspace_id=connector.workspace_id, agent_id=UUID(str(args["agent_id"])), run_id=UUID(str(args["run_id"])), state_hash=value["state_hash"], state=value["state"])
        db.add(row); await db.commit()
        return {"supported": True, "snapshot_id": str(row.id), **value}


@defn
async def persist_state_diff(args: dict) -> dict:
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.models.phase2_models import StateDiff
    from app.state_service import state_diff
    async with AsyncSessionLocal() as db:
        value = state_diff(args.get("before") or {}, args.get("after") or {})
        row = StateDiff(workspace_id=UUID(str(args["workspace_id"])), run_id=UUID(str(args["run_id"])), **value)
        db.add(row); await db.commit()
        return {"state_diff_id": str(row.id), **value}
