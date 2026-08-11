import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from app.database import get_db
from app.security import require_owner_or_admin
from app.contracts.common import ActorContext
from app.contracts.osrs import BindingRequest, CloneRequest, ImportCommit, LoadoutCreate, LoadoutResponse, LoadoutUpdate, WikiPreview
from app.models.models import MCPServer
from app.services import osrs_loadouts as service

router = APIRouter(prefix="/api/osrs", tags=["osrs"])

async def actor_dep(actor: ActorContext = Depends(require_owner_or_admin)): return actor

def parse_mcp_response(result):
    """Extract JSON from MCP structured content or text without exposing transport details."""
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if structured is not None: return structured
    values = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text: values.append(text)
    raw = "\n".join(values)
    try: return json.loads(raw)
    except (TypeError, ValueError): return {"text": raw}

async def _mcp(db, tool_name, arguments):
    from app.encryption import decrypt_dict
    from app.mcp_helper import get_mcp_server_params
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    if tool_name not in {"loadout_metadata", "search_equipment", "import_wiki_dps_link"}:
        raise HTTPException(400, "OSRS tool is not allowlisted")
    servers = (await db.scalars(select(MCPServer).where(MCPServer.is_active.is_(True)))).all()
    def cached_names(value):
        if isinstance(value, dict):
            values = value.get("tools", [])
            if not values:
                values = [{"name": key} for key in value]
        else:
            values = value or []
        return {x.get("name") for x in values if isinstance(x, dict)}
    server = next((x for x in servers if "osrs" in x.name.lower() or tool_name in cached_names(x.cached_tools)), None)
    if not server: raise HTTPException(503, "active OSRS MCP server is unavailable")
    params = get_mcp_server_params(server.image, await decrypt_dict(server.env_vars) or {}, await decrypt_dict(server.args) or {}, await decrypt_dict(server.registry_credentials) or {})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return parse_mcp_response(await session.call_tool(tool_name, arguments))

@router.get("/metadata")
async def metadata(db=Depends(get_db), actor=Depends(actor_dep)): return await _mcp(db, "loadout_metadata", {})

@router.get("/equipment/search")
async def equipment_search(q: str, slot: str | None = None, limit: int = 20, db=Depends(get_db), actor=Depends(actor_dep)):
    return await _mcp(db, "search_equipment", {"query": q, "slot": slot, "limit": max(1, min(limit, 50))})

@router.post("/wiki/preview")
async def wiki_preview(body: WikiPreview, db=Depends(get_db), actor=Depends(actor_dep)):
    return await _mcp(db, "import_wiki_dps_link", {"link": body.link})

@router.post("/wiki/commit")
async def wiki_commit(body: ImportCommit, db=Depends(get_db), actor=Depends(actor_dep)):
    return [await service.create_loadout(db, actor.workspace_id, item.model_copy(update={"source_type": "wiki"}), actor) for item in body.loadouts]

@router.get("/loadouts", response_model=list[LoadoutResponse])
async def list_loadouts(db=Depends(get_db), actor=Depends(actor_dep)): return await service.list_loadouts(db, actor.workspace_id)

@router.post("/loadouts", response_model=LoadoutResponse)
async def create_loadout(body: LoadoutCreate, db=Depends(get_db), actor=Depends(actor_dep)): return await service.create_loadout(db, actor.workspace_id, body, actor)

@router.get("/loadouts/{loadout_id}", response_model=LoadoutResponse)
async def get_loadout(loadout_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await service.get_loadout(db, actor.workspace_id, loadout_id)
    if not row: raise HTTPException(404, "loadout not found")
    return row

@router.put("/loadouts/{loadout_id}", response_model=LoadoutResponse)
async def update_loadout(loadout_id: UUID, body: LoadoutUpdate, db=Depends(get_db), actor=Depends(actor_dep)):
    row, error = await service.update_loadout(db, actor.workspace_id, loadout_id, body)
    if error == "missing": raise HTTPException(404, "loadout not found")
    if error: raise HTTPException(409, "loadout revision conflict")
    return row

@router.post("/loadouts/{loadout_id}/clone", response_model=LoadoutResponse)
async def clone_loadout(loadout_id: UUID, body: CloneRequest, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await service.clone_loadout(db, actor.workspace_id, loadout_id, body.name, actor)
    if not row: raise HTTPException(404, "loadout not found")
    return row

@router.post("/loadouts/{loadout_id}/default", response_model=LoadoutResponse)
async def default_loadout(loadout_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await service.set_default(db, actor.workspace_id, loadout_id)
    if not row: raise HTTPException(404, "loadout not found")
    return row

@router.delete("/loadouts/{loadout_id}")
async def delete_loadout(loadout_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    if not await service.delete_loadout(db, actor.workspace_id, loadout_id): raise HTTPException(404, "loadout not found")
    return {"deleted": True}

@router.get("/threads/{thread_id}/loadouts")
async def bindings(thread_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)): return await service.thread_bindings(db, actor.workspace_id, thread_id)

@router.put("/threads/{thread_id}/loadout", response_model=LoadoutResponse)
async def bind(thread_id: UUID, body: BindingRequest, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await service.bind_thread(db, actor.workspace_id, thread_id, body.loadout_id)
    if not row: raise HTTPException(404, "loadout not found")
    return row

@router.get("/threads/{thread_id}/loadout", response_model=LoadoutResponse)
async def binding(thread_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    row, _explicit = await service.resolve_thread_loadout(db, actor.workspace_id, thread_id)
    if not row: raise HTTPException(404, "no loadout bound or configured as default")
    return row

@router.delete("/threads/{thread_id}/loadout")
async def unbind(thread_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    ids = await service.thread_bindings(db, actor.workspace_id, thread_id)
    if not ids or not await service.unbind_thread(db, actor.workspace_id, thread_id, ids[0]): raise HTTPException(404, "binding not found")
    return {"deleted": True}
