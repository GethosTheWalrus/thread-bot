from typing import Annotated, Literal
from uuid import UUID
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

class EquipmentItem(Strict):
    id: int = Field(ge=1)
    version: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=255)
    item_vars: dict = Field(
        default_factory=dict,
        validation_alias=AliasChoices("item_vars", "itemVars"),
        serialization_alias="item_vars",
    )

class Equipment(Strict):
    head: EquipmentItem | None
    cape: EquipmentItem | None
    neck: EquipmentItem | None
    ammo: EquipmentItem | None
    weapon: EquipmentItem | None
    body: EquipmentItem | None
    shield: EquipmentItem | None
    legs: EquipmentItem | None
    hands: EquipmentItem | None
    feet: EquipmentItem | None
    ring: EquipmentItem | None

class Skills(Strict):
    atk: int = Field(ge=1, le=126); str: int = Field(ge=1, le=126)
    def_: int = Field(alias="def", ge=1, le=126); hp: int = Field(ge=1, le=126)
    ranged: int = Field(ge=1, le=126); magic: int = Field(ge=1, le=126)
    prayer: int = Field(ge=1, le=126); mining: int = Field(ge=1, le=126)
    herblore: int = Field(ge=1, le=126)
    model_config = ConfigDict(extra="forbid", populate_by_name=False)

class Boosts(Strict):
    atk: int = Field(ge=-126, le=126)
    str: int = Field(ge=-126, le=126)
    def_: int = Field(alias="def", ge=-126, le=126)
    hp: int = Field(ge=-126, le=126)
    ranged: int = Field(ge=-126, le=126)
    magic: int = Field(ge=-126, le=126)
    prayer: int = Field(ge=-126, le=126)
    mining: int = Field(ge=-126, le=126)
    herblore: int = Field(ge=-126, le=126)
    model_config = ConfigDict(extra="forbid", populate_by_name=False)

class Buffs(Strict):
    on_slayer_task: bool = False; in_wilderness: bool = False; forinthry_surge: bool = False
    soulreaper_stacks: int = Field(0, ge=0, le=5)
    ba_attacker_level: int = Field(0, ge=0)
    chinchompa_distance: int = Field(4, ge=1, le=7)
    kandarin_diary: bool = False; charge_spell: bool = False; mark_of_darkness_spell: bool = False
    using_sunfire_runes: bool = False

class Combat(Strict):
    stance: Literal["Accurate", "Aggressive", "Autocast", "Controlled", "Defensive", "Defensive Autocast", "Longrange", "Rapid", "Manual Cast"] | None = None
    attack_type: Literal["stab", "slash", "crush", "magic", "ranged"] | None = None
    spell: str | None = None

class OsrsLoadoutPayload(Strict):
    schema_version: Literal[1] = 1
    equipment: Equipment
    skills: Skills
    boosts: Boosts
    prayers: list[Annotated[int, Field(ge=0, le=20)]] = Field(default_factory=list, max_length=20)
    potions: list[Annotated[int, Field(ge=0, le=22)]] = Field(default_factory=list, max_length=22)
    buffs: Buffs
    combat: Combat

class LoadoutCreate(Strict):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    loadout: OsrsLoadoutPayload
    is_default: bool = False
    source_type: Literal["manual", "wiki", "clone"] = "manual"
    source_ref: str | None = None
    engine_revision: str | None = None

class LoadoutUpdate(Strict):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    loadout: OsrsLoadoutPayload | None = None
    is_default: bool | None = None

class LoadoutResponse(Strict):
    id: UUID; workspace_id: UUID; name: str; description: str | None
    loadout: OsrsLoadoutPayload; revision: int; is_default: bool
    schema_version: int = 1; source_type: str; source_ref: str | None; engine_revision: str | None

class BindingRequest(Strict):
    loadout_id: UUID

class WikiPreview(Strict):
    link: str = Field(min_length=1, max_length=2000)

class CloneRequest(Strict):
    name: str = Field(min_length=1, max_length=255)

class ImportCommit(Strict):
    loadouts: list[LoadoutCreate] = Field(min_length=1, max_length=6)
