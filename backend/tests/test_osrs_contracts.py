import pytest
from pydantic import ValidationError
from app.contracts.osrs import EquipmentItem, OsrsLoadoutPayload

SLOTS = ("head", "cape", "neck", "ammo", "weapon", "body", "shield", "legs", "hands", "feet", "ring")
STATS = ("atk", "str", "def", "hp", "ranged", "magic", "prayer", "mining", "herblore")

def payload():
    return {"schema_version": 1, "equipment": {slot: None for slot in SLOTS},
            "skills": {key: 99 for key in STATS}, "boosts": {key: 0 for key in STATS},
            "prayers": [0], "potions": [0],
            "buffs": {"on_slayer_task": False, "in_wilderness": False, "forinthry_surge": False,
                      "soulreaper_stacks": 0, "ba_attacker_level": 0, "chinchompa_distance": 4,
                      "kandarin_diary": False, "charge_spell": False, "mark_of_darkness_spell": False,
                      "using_sunfire_runes": False},
            "combat": {"stance": None, "attack_type": None, "spell": None}}

def test_canonical_payload_is_complete_and_aliases_upstream_keys():
    result = OsrsLoadoutPayload.model_validate(payload())
    assert result.schema_version == 1
    assert set(result.equipment.model_fields) == set(SLOTS)
    assert result.model_dump(by_alias=True)["skills"]["def"] == 99
    assert "potions" not in result.model_dump(by_alias=True)["buffs"]

def test_payload_rejects_missing_slot_and_bad_schema():
    value = payload(); del value["equipment"]["ring"]
    with pytest.raises(ValidationError): OsrsLoadoutPayload.model_validate(value)
    value = payload(); value["schema_version"] = 2
    with pytest.raises(ValidationError): OsrsLoadoutPayload.model_validate(value)

def test_payload_rejects_out_of_range_prayer():
    value = payload(); value["prayers"] = [21]
    with pytest.raises(ValidationError): OsrsLoadoutPayload.model_validate(value)

def test_equipment_item_accepts_both_item_var_spellings_and_serializes_canonically():
    item = EquipmentItem.model_validate({"id": 4151, "itemVars": {"charges": 3}})
    assert item.item_vars == {"charges": 3}
    assert item.model_dump() == {"id": 4151, "version": None, "name": None, "item_vars": {"charges": 3}}
    assert EquipmentItem.model_validate({"id": 4151, "item_vars": {}}).item_vars == {}

def test_equipment_item_requires_positive_id():
    with pytest.raises(ValidationError):
        EquipmentItem.model_validate({"id": 0})
