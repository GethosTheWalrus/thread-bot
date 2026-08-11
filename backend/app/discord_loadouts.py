"""Discord command helpers for OSRS loadouts."""

from typing import Any

from sqlalchemy import select

from app.api.osrs import _mcp
from app.contracts.osrs import LoadoutCreate, LoadoutUpdate, OsrsLoadoutPayload
from app.models.models import DiscordThreadLink, Thread
from app.models.osrs_models import OsrsLoadout
from app.services import osrs_loadouts as service

SLOTS = ("head", "cape", "neck", "ammo", "weapon", "body", "shield", "legs", "hands", "feet", "ring")
STAT_KEYS = ("atk", "str", "def", "hp", "ranged", "magic", "prayer", "mining", "herblore")


def starter_payload() -> dict:
    return {"schema_version": 1, "equipment": {slot: None for slot in SLOTS},
            "skills": {key: 1 for key in STAT_KEYS}, "boosts": {key: 0 for key in STAT_KEYS},
            "prayers": [], "potions": [],
            "buffs": {"on_slayer_task": False, "in_wilderness": False, "forinthry_surge": False,
                      "soulreaper_stacks": 0, "ba_attacker_level": 0, "chinchompa_distance": 4,
                      "kandarin_diary": False, "charge_spell": False, "mark_of_darkness_spell": False,
                      "using_sunfire_runes": False},
            "combat": {"stance": None, "attack_type": None, "spell": None}}


def canonical_imported_loadout(value: dict[str, Any]) -> dict[str, Any]:
    """Convert the MCP import shape (including camelCase fields) to API shape."""
    value = value.get("loadout", value) if isinstance(value, dict) else {}

    def item(raw):
        if raw is None:
            return None
        return {"id": raw["id"], "version": raw.get("version"), "name": raw.get("name"),
                "item_vars": raw.get("item_vars", raw.get("itemVars", {})) or {}}

    equipment = {slot: item((value.get("equipment") or {}).get(slot)) for slot in SLOTS}

    def values(raw):
        return {"def" if key == "def_" else key: val for key, val in (raw or {}).items()}

    buff_names = {"onSlayerTask": "on_slayer_task", "inWilderness": "in_wilderness",
                  "forinthrySurge": "forinthry_surge", "soulreaperStacks": "soulreaper_stacks",
                  "baAttackerLevel": "ba_attacker_level", "chinchompaDistance": "chinchompa_distance",
                  "kandarinDiary": "kandarin_diary", "chargeSpell": "charge_spell",
                  "markOfDarknessSpell": "mark_of_darkness_spell", "usingSunfireRunes": "using_sunfire_runes"}
    raw_buffs = value.get("buffs") or {}
    potions = value.get("potions")
    if potions is None:
        potions = raw_buffs.get("potions") or []
    buffs = {
        buff_names.get(key, key): val
        for key, val in raw_buffs.items()
        if key != "potions"
    }
    combat = value.get("combat") or {}
    return OsrsLoadoutPayload.model_validate({"schema_version": 1, "equipment": equipment,
        "skills": values(value.get("skills")), "boosts": values(value.get("boosts")),
        "prayers": value.get("prayers") or [], "potions": potions, "buffs": buffs,
        "combat": {"stance": combat.get("stance") or value.get("stance"),
                   "attack_type": combat.get("attack_type") or combat.get("attackType") or value.get("attackType") or value.get("attack_type"),
                   "spell": combat.get("spell") or value.get("spell")}}).model_dump(mode="json", by_alias=True)


async def workspace_thread(db, workspace_id, discord_thread_id: str):
    return await db.scalar(select(DiscordThreadLink.thread_id).join(Thread, Thread.id == DiscordThreadLink.thread_id).where(
        Thread.workspace_id == workspace_id, DiscordThreadLink.discord_thread_id == str(discord_thread_id),
        DiscordThreadLink.is_active.is_(True)))


async def resolve_name(db, workspace_id, name: str):
    return await db.scalar(select(OsrsLoadout).where(OsrsLoadout.workspace_id == workspace_id,
                                                     OsrsLoadout.name.ilike(name)))


def discord_actor(actor_id: str):
    return type("DiscordActor", (), {"actor_type": "discord", "actor_id": str(actor_id)})()


async def create(db, workspace_id, name, actor_id):
    return await service.create_loadout(db, workspace_id, LoadoutCreate(name=name, loadout=starter_payload()), discord_actor(actor_id))


async def import_link(db, workspace_id, link, actor_id):
    result = await _mcp(db, "import_wiki_dps_link", {"link": link})
    values = result.get("loadouts", []) if isinstance(result, dict) else (result if isinstance(result, list) else [])
    source = (result.get("source_ref") or result.get("source") or result.get("link") or link) if isinstance(result, dict) else link
    imported = []
    for index, raw in enumerate(values[:6], 1):
        if not isinstance(raw, dict):
            continue
        base = str(raw.get("name") or f"Imported {index}")[:240]
        name, suffix = base, 2
        while await resolve_name(db, workspace_id, name):
            name, suffix = f"{base[:245 - len(str(suffix))]} ({suffix})", suffix + 1
        engine = result.get("engine") if isinstance(result, dict) else None
        metadata = result.get("metadata") if isinstance(result, dict) else None
        engine_revision = ((result.get("engine_revision") or result.get("upstreamCommit") or
                            result.get("upstream_commit")) if isinstance(result, dict) else None)
        if not engine_revision and isinstance(engine, dict):
            engine_revision = engine.get("upstreamCommit") or engine.get("upstream_commit")
        if not engine_revision and isinstance(metadata, dict):
            engine_revision = metadata.get("upstreamCommit") or metadata.get("upstream_commit")
            if not engine_revision and isinstance(metadata.get("engine"), dict):
                engine_revision = (metadata["engine"].get("upstreamCommit") or
                                   metadata["engine"].get("upstream_commit"))
        body = LoadoutCreate(name=name, loadout=canonical_imported_loadout(raw), source_type="wiki",
                             source_ref=str(source), engine_revision=str(engine_revision) if engine_revision else None)
        imported.append(await service.create_loadout(db, workspace_id, body, discord_actor(actor_id)))
    return imported


async def equip_candidates(db, slot, query):
    result = await _mcp(db, "search_equipment", {"query": query, "slot": slot, "limit": 25})
    values = (result.get("items", result.get("candidates", [])) if isinstance(result, dict)
              else result if isinstance(result, list) else [])
    return [value for value in values if isinstance(value, dict) and value.get("id") is not None][:25]


async def equip(db, workspace_id, loadout_id, revision, slot, item):
    row = await service.get_loadout(db, workspace_id, loadout_id)
    if not row or row["revision"] != revision:
        return None, "conflict" if row else "missing"
    payload = row["loadout"].model_copy(update={"equipment": row["loadout"].equipment.model_copy(update={slot: item})})
    return await service.update_loadout(db, workspace_id, loadout_id,
                                       LoadoutUpdate(expected_revision=revision, loadout=payload))


async def update_stats(db, workspace_id, loadout_id, revision, stats):
    row = await service.get_loadout(db, workspace_id, loadout_id)
    if not row or row["revision"] != revision:
        return None, "conflict" if row else "missing"
    values = {key: stats.get(key, getattr(row["loadout"].skills, key if key != "def" else "def_")) for key in STAT_KEYS}
    payload = row["loadout"].model_copy(update={"skills": values})
    payload = OsrsLoadoutPayload.model_validate(payload.model_dump(mode="python", by_alias=True))
    return await service.update_loadout(db, workspace_id, loadout_id,
                                       LoadoutUpdate(expected_revision=revision, loadout=payload))


async def update_preset(db, workspace_id, loadout_id, revision, *, combat=None, buffs=None):
    row = await service.get_loadout(db, workspace_id, loadout_id)
    if not row or row["revision"] != revision:
        return None, "conflict" if row else "missing"
    payload = row["loadout"]
    if combat:
        payload = payload.model_copy(update={"combat": payload.combat.model_copy(update=combat)})
    if buffs:
        payload = payload.model_copy(update={"buffs": payload.buffs.model_copy(update=buffs)})
    payload = OsrsLoadoutPayload.model_validate(payload.model_dump(mode="python", by_alias=True))
    return await service.update_loadout(db, workspace_id, loadout_id,
                                       LoadoutUpdate(expected_revision=revision, loadout=payload))
