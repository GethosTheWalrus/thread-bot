"""Discord command helpers for OSRS loadouts."""

import asyncio
import base64
import json
import time
from typing import Any

import aiohttp
from sqlalchemy import select

from app.api.osrs import _mcp
from app.contracts.osrs import LoadoutCreate, LoadoutUpdate, OsrsLoadoutPayload
from app.models.models import DiscordThreadLink, Thread
from app.models.osrs_models import OsrsLoadout
from app.services import osrs_loadouts as service

SLOTS = ("head", "cape", "neck", "ammo", "weapon", "body", "shield", "legs", "hands", "feet", "ring")
STAT_KEYS = ("atk", "str", "def", "hp", "ranged", "magic", "prayer", "mining", "herblore")
EQUIPMENT_URL = (
    "https://raw.githubusercontent.com/weirdgloop/osrs-dps-calc/"
    "91218d63e71927e99748a50d008975336025a88e/cdn/json/equipment.json"
)
EQUIPMENT_CACHE_TTL = 6 * 60 * 60
EQUIPMENT_MAX_BYTES = 4 * 1024 * 1024
_equipment_cache: tuple[float, list[dict[str, Any]]] | None = None
_equipment_load: asyncio.Task | None = None
_equipment_lock = asyncio.Lock()
CLEAR_TOKEN = "clear"


def encode_equipment_choice(item: dict[str, Any]) -> str:
    """Encode the authoritative identity, rather than a display name, for Discord."""
    raw = json.dumps([item["id"], item.get("version")], separators=(",", ":"), ensure_ascii=True).encode()
    return "i:" + base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_equipment_choice(value: str) -> tuple[Any, Any] | None:
    if not isinstance(value, str) or not value.startswith("i:"):
        return None
    try:
        raw = base64.urlsafe_b64decode(value[2:] + "=" * (-len(value[2:]) % 4))
        decoded = json.loads(raw)
        return (decoded[0], decoded[1]) if isinstance(decoded, list) and len(decoded) == 2 else None
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _normalise_item(raw: dict[str, Any]) -> dict[str, Any] | None:
    if raw.get("id") is None or not isinstance(raw.get("name"), str) or not isinstance(raw.get("slot"), (str, list, tuple)):
        return None
    slots = raw["slot"] if isinstance(raw["slot"], (list, tuple)) else [raw["slot"]]
    slots = [str(slot).lower() for slot in slots]
    return {"id": raw["id"], "version": raw.get("version"), "name": raw["name"],
            "slot": slots, "itemVars": raw.get("itemVars", raw.get("item_vars", {})) or {}}


async def _fetch_equipment() -> list[dict[str, Any]]:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(EQUIPMENT_URL) as response:
            response.raise_for_status()
            body = await response.content.read(EQUIPMENT_MAX_BYTES + 1)
            if len(body) > EQUIPMENT_MAX_BYTES:
                raise ValueError("equipment catalog is too large")
    payload = json.loads(body)
    if not isinstance(payload, list):
        raise ValueError("equipment catalog is not a list")
    result = [_normalise_item(item) for item in payload if isinstance(item, dict)]
    result = [item for item in result if item is not None]
    if not result:
        raise ValueError("equipment catalog is empty")
    return result


async def equipment_catalog() -> list[dict[str, Any]]:
    global _equipment_cache, _equipment_load
    now = time.monotonic()
    if _equipment_cache and now - _equipment_cache[0] < EQUIPMENT_CACHE_TTL:
        return _equipment_cache[1]
    async with _equipment_lock:
        now = time.monotonic()
        if _equipment_cache and now - _equipment_cache[0] < EQUIPMENT_CACHE_TTL:
            return _equipment_cache[1]
        if _equipment_load is None:
            _equipment_load = asyncio.create_task(_fetch_equipment())
        task = _equipment_load
    try:
        items = await task
        _equipment_cache = (time.monotonic(), items)
        return items
    except Exception:
        if _equipment_cache:
            return _equipment_cache[1]
        raise
    finally:
        async with _equipment_lock:
            if _equipment_load is task:
                _equipment_load = None


def reset_equipment_catalog(items: list[dict[str, Any]] | None = None) -> None:
    """Reset/inject the catalog for tests and operational refreshes."""
    global _equipment_cache, _equipment_load
    _equipment_cache = (time.monotonic(), items) if items is not None else None
    _equipment_load = None


def equipment_choices(items: list[dict[str, Any]], slot: str, current: str) -> list[dict[str, Any]]:
    query = (current or "").casefold()
    candidates = [item for item in items if slot in item.get("slot", []) and query in item["name"].casefold()]
    candidates.sort(key=lambda item: (not item["name"].casefold().startswith(query), item["name"].casefold(),
                                      str(item.get("version") or ""), str(item["id"])))
    return candidates[:24]


def resolve_equipment_choice(value: str, slot: str, items: list[dict[str, Any]]) -> dict[str, Any] | None | bool:
    if value == CLEAR_TOKEN:
        return None
    identity = decode_equipment_choice(value)
    if identity is None:
        return False
    item_id, version = identity
    for item in items:
        if slot in item.get("slot", []) and item["id"] == item_id and item.get("version") == version:
            return {"id": item["id"], "version": item.get("version"), "name": item["name"],
                    "item_vars": item.get("itemVars", {})}
    return False


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


async def equip_many(db, workspace_id, loadout_id, revision, updates):
    if not updates:
        return None, "no-op"
    row = await service.get_loadout(db, workspace_id, loadout_id)
    if not row or row["revision"] != revision:
        return None, "conflict" if row else "missing"
    payload_data = row["loadout"].model_dump(mode="python", by_alias=True)
    payload_data["equipment"].update(updates)
    payload = OsrsLoadoutPayload.model_validate(payload_data)
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
