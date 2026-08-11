from uuid import UUID
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.osrs_models import OsrsLoadout, ThreadOsrsLoadout
from app.models.models import Thread
from app.contracts.osrs import LoadoutCreate, LoadoutUpdate, OsrsLoadoutPayload


def to_mcp_calculate_dps_loadout(stored, *, metadata=None):
    """Convert the canonical loadout contract to calculate_dps' primitive fields."""
    payload = stored.get("loadout", stored) if isinstance(stored, dict) else stored
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="python", by_alias=True)
    payload = dict(payload)
    equipment = {}
    for slot, item in (payload.get("equipment") or {}).items():
        if item is None:
            equipment[slot] = None
            continue
        equipment[slot] = {
            "id": item["id"],
            **({"version": item["version"]} if item.get("version") is not None else {}),
            "itemVars": item.get("item_vars") or {},
        }
    def skill_values(values):
        return {("def" if key == "def_" else key): value for key, value in (values or {}).items()}
    camel = {
        "on_slayer_task": "onSlayerTask", "in_wilderness": "inWilderness",
        "forinthry_surge": "forinthrySurge", "soulreaper_stacks": "soulreaperStacks",
        "ba_attacker_level": "baAttackerLevel", "chinchompa_distance": "chinchompaDistance",
        "kandarin_diary": "kandarinDiary", "charge_spell": "chargeSpell",
        "mark_of_darkness_spell": "markOfDarknessSpell", "using_sunfire_runes": "usingSunfireRunes",
    }
    buffs = {
        camel.get(key, key): value
        for key, value in (payload.get("buffs") or {}).items()
        if key != "potions"
    }
    buffs["potions"] = payload.get("potions") or []
    combat = payload.get("combat") or {}
    result = {
        "equipment": equipment, "skills": skill_values(payload.get("skills")),
        "boosts": skill_values(payload.get("boosts")), "prayers": payload.get("prayers") or [],
        "buffs": buffs,
        "stance": combat.get("stance"), "attackType": combat.get("attack_type", combat.get("attackType")),
        "spell": combat.get("spell"),
    }
    if metadata is None and isinstance(stored, dict):
        metadata = {
            key: (str(stored[key]) if key == "id" else stored[key])
            for key in ("id", "name", "revision") if stored.get(key) is not None
        }
    if metadata:
        result["metadata"] = metadata
    return result


loadout_to_mcp_fields = to_mcp_calculate_dps_loadout

def _data(row):
    return {"id": row.id, "workspace_id": row.workspace_id, "name": row.name, "description": row.description,
            "loadout": OsrsLoadoutPayload.model_validate(row.payload), "revision": row.revision, "is_default": row.is_default,
            "schema_version": row.schema_version, "source_type": row.source_type, "source_ref": row.source_ref,
            "engine_revision": row.engine_revision}

async def list_loadouts(db: AsyncSession, workspace_id: UUID):
    return [_data(x) for x in (await db.scalars(select(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id).order_by(OsrsLoadout.name))).all()]

async def get_loadout(db, workspace_id, loadout_id):
    row = await db.scalar(select(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id, OsrsLoadout.id == loadout_id))
    return _data(row) if row else None

async def create_loadout(db, workspace_id, body: LoadoutCreate, actor=None):
    if body.is_default:
        await db.execute(update(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id).values(is_default=False))
    row = OsrsLoadout(workspace_id=workspace_id, name=body.name, description=body.description,
                      payload=body.loadout.model_dump(mode="json", by_alias=True), is_default=body.is_default,
                      schema_version=1, source_type=body.source_type, source_ref=body.source_ref,
                      engine_revision=body.engine_revision,
                       created_by_actor_type=str(getattr(actor, "actor_type", "system")),
                       created_by_actor_id=str(getattr(actor, "actor_id", "system")))
    db.add(row); await db.flush(); return _data(row)

async def update_loadout(db, workspace_id, loadout_id, body: LoadoutUpdate):
    row = await db.scalar(select(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id, OsrsLoadout.id == loadout_id).with_for_update())
    if not row or row.revision != body.expected_revision: return None, "conflict" if row else "missing"
    if body.is_default:
        await db.execute(update(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id, OsrsLoadout.id != row.id).values(is_default=False))
    for key in ("name", "description", "is_default"):
        value = getattr(body, key)
        if value is not None: setattr(row, key, value)
    if body.loadout is not None: row.payload = body.loadout.model_dump(mode="json", by_alias=True)
    row.revision += 1; await db.flush(); return _data(row), None

async def clone_loadout(db, workspace_id, loadout_id, name, actor=None):
    row = await db.scalar(select(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id, OsrsLoadout.id == loadout_id))
    if not row: return None
    clone = OsrsLoadout(workspace_id=workspace_id, name=name, description=row.description, payload=row.payload,
                        schema_version=1, source_type="clone", source_ref=str(row.id),
                        engine_revision=row.engine_revision,
                        created_by_actor_type=str(getattr(actor, "actor_type", "system")),
                        created_by_actor_id=str(getattr(actor, "actor_id", "system")))
    db.add(clone); await db.flush(); return _data(clone)

async def delete_loadout(db, workspace_id, loadout_id):
    result = await db.execute(delete(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id, OsrsLoadout.id == loadout_id)); return result.rowcount > 0

async def set_default(db, workspace_id, loadout_id):
    row = await db.scalar(select(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id, OsrsLoadout.id == loadout_id))
    if not row: return None
    await db.execute(update(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id).values(is_default=False)); row.is_default = True; return _data(row)

async def bind_thread(db, workspace_id, thread_id, loadout_id):
    thread = await db.scalar(select(Thread).where(Thread.workspace_id == workspace_id, Thread.id == thread_id))
    if not thread: return None
    loadout = await db.scalar(select(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id, OsrsLoadout.id == loadout_id))
    if not loadout: return None
    statement = insert(ThreadOsrsLoadout).values(
        workspace_id=workspace_id,
        thread_id=thread_id,
        loadout_id=loadout_id,
    ).on_conflict_do_update(
        index_elements=["workspace_id", "thread_id"],
        set_={"loadout_id": loadout_id},
    )
    await db.execute(statement)
    return _data(loadout)

async def unbind_thread(db, workspace_id, thread_id, loadout_id):
    result = await db.execute(delete(ThreadOsrsLoadout).where(ThreadOsrsLoadout.workspace_id == workspace_id, ThreadOsrsLoadout.thread_id == thread_id, ThreadOsrsLoadout.loadout_id == loadout_id)); return result.rowcount > 0

async def thread_bindings(db, workspace_id, thread_id):
    ids = await db.scalars(select(ThreadOsrsLoadout.loadout_id).where(ThreadOsrsLoadout.workspace_id == workspace_id, ThreadOsrsLoadout.thread_id == thread_id)); return [x for x in ids]

async def resolve_thread_loadout(db, workspace_id, thread_id):
    bound = await db.scalar(
        select(OsrsLoadout)
        .join(ThreadOsrsLoadout, ThreadOsrsLoadout.loadout_id == OsrsLoadout.id)
        .where(
            ThreadOsrsLoadout.workspace_id == workspace_id,
            ThreadOsrsLoadout.thread_id == thread_id,
            OsrsLoadout.workspace_id == workspace_id,
        )
    )
    if bound:
        return _data(bound), True
    default = await db.scalar(select(OsrsLoadout).where(
        OsrsLoadout.workspace_id == workspace_id,
        OsrsLoadout.is_default.is_(True),
    ))
    return (_data(default), False) if default else (None, False)
