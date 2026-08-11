from app.contracts.osrs import OsrsLoadoutPayload
from app.discord_loadouts import SLOTS, canonical_imported_loadout, starter_payload
import inspect

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
