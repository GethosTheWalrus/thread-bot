from app.contracts.osrs import OsrsLoadoutPayload
from app.discord_loadouts import (CLEAR_TOKEN, SLOTS, canonical_imported_loadout,
                                  decode_equipment_choice, encode_equipment_choice,
                                  equip_many, equipment_choices, resolve_equipment_choice,
                                  starter_payload)
import inspect
from types import SimpleNamespace

import pytest

from app.services import osrs_loadouts
from app.services.osrs_loadouts import to_mcp_calculate_dps_loadout
from app.discord_bot import escape_like_pattern


def test_starter_payload_is_complete_and_safe():
    payload = starter_payload()
    assert set(payload["equipment"]) == set(SLOTS)
    assert all(item is None for item in payload["equipment"].values())
    assert payload["prayers"] == [] and payload["potions"] == []
    assert all(value == 0 for value in payload["boosts"].values())
    assert payload["combat"] == {"stance": None, "attack_type": None, "spell": None}


def test_import_conversion_canonicalizes_camel_case():
    source = starter_payload()
    source.update({
        "equipment": {**source["equipment"], "weapon": {"id": 4151, "itemVars": {"charges": 3}}},
        "skills": {**source["skills"], "def": 80}, "boosts": {**source["boosts"], "def": 1},
        "buffs": {"onSlayerTask": True, "soulreaperStacks": 2},
        "combat": {"attackType": "slash"},
    })
    payload = canonical_imported_loadout(source)
    assert payload["equipment"]["weapon"]["item_vars"] == {"charges": 3}
    assert payload["skills"]["def"] == 80
    assert payload["buffs"]["on_slayer_task"] is True
    assert payload["combat"]["attack_type"] == "slash"


def test_mcp_conversion_puts_potions_in_buffs():
    stored = OsrsLoadoutPayload.model_validate(
        {**starter_payload(), "potions": [14, 19]}
    ).model_dump(mode="json", by_alias=True)
    result = to_mcp_calculate_dps_loadout({"loadout": stored})
    assert result["buffs"]["potions"] == [14, 19]
    assert "potions" not in result


def test_import_conversion_moves_mcp_potions_to_canonical_field():
    source = starter_payload()
    source.pop("potions")
    source["buffs"] = {"potions": [14, 19], "onSlayerTask": True}
    payload = canonical_imported_loadout(source)
    assert payload["potions"] == [14, 19]
    assert "potions" not in payload["buffs"]

def test_discord_autocomplete_escapes_like_wildcards():
    assert escape_like_pattern(r"100%_done\now") == r"100\%\_done\\now"

def test_thread_binding_uses_postgresql_upsert():
    source = inspect.getsource(osrs_loadouts.bind_thread)
    assert "on_conflict_do_update" in source
    assert "index_elements=[\"workspace_id\", \"thread_id\"]" in source


def test_equipment_choices_are_slot_isolated_and_prefix_ranked():
    items = [
        {"id": 2, "version": 1, "name": "Dragon sword", "slot": ["weapon"]},
        {"id": 1, "version": 2, "name": "Dragonfire shield", "slot": ["shield"]},
        {"id": 3, "version": 1, "name": "Abyssal whip", "slot": ["weapon"]},
    ]
    assert [x["name"] for x in equipment_choices(items, "weapon", "dragon")] == ["Dragon sword"]
    assert equipment_choices(items, "shield", "dragon")[0]["name"] == "Dragonfire shield"


def test_equipment_choice_round_trip_includes_version_and_clear():
    item = {"id": 4151, "version": "v2", "name": "Abyssal whip", "slot": ["weapon"]}
    token = encode_equipment_choice(item)
    assert len(token) <= 100
    assert decode_equipment_choice(token) == (4151, "v2")
    assert resolve_equipment_choice(token, "weapon", [item])["version"] == "v2"
    assert resolve_equipment_choice(CLEAR_TOKEN, "weapon", [item]) is None


def test_equipment_choice_rejects_wrong_slot_or_unknown_item():
    item = {"id": 4151, "version": None, "name": "Abyssal whip", "slot": ["weapon"]}
    token = encode_equipment_choice(item)
    assert resolve_equipment_choice(token, "head", [item]) is False
    assert resolve_equipment_choice("not-a-token", "weapon", [item]) is False


def test_equipment_choices_leave_room_for_clear_choice():
    items = [
        {"id": index, "version": None, "name": f"Item {index:02d}", "slot": ["weapon"]}
        for index in range(1, 31)
    ]
    assert len(equipment_choices(items, "weapon", "")) == 24


@pytest.mark.asyncio
async def test_equip_many_updates_all_slots_once(monkeypatch):
    stored = OsrsLoadoutPayload.model_validate(starter_payload())
    row = {"revision": 3, "loadout": stored}
    calls = []

    async def fake_get(*_args):
        return row

    async def fake_update(_db, _workspace_id, _loadout_id, body):
        calls.append(body)
        return {"revision": 4}, None

    monkeypatch.setattr("app.discord_loadouts.service.get_loadout", fake_get)
    monkeypatch.setattr("app.discord_loadouts.service.update_loadout", fake_update)
    weapon = {"id": 4151, "version": None, "name": "Abyssal whip", "item_vars": {}}
    head = {"id": 11865, "version": None, "name": "Slayer helmet (i)", "item_vars": {}}
    result, error = await equip_many(
        SimpleNamespace(), "workspace", "loadout", 3, {"weapon": weapon, "head": head}
    )

    assert error is None and result["revision"] == 4
    assert len(calls) == 1 and calls[0].expected_revision == 3
    assert calls[0].loadout.equipment.weapon.id == 4151
    assert calls[0].loadout.equipment.head.id == 11865
    assert calls[0].loadout.equipment.cape is None


@pytest.mark.asyncio
async def test_equip_many_rejects_empty_update():
    assert await equip_many(SimpleNamespace(), "workspace", "loadout", 1, {}) == (None, "no-op")
