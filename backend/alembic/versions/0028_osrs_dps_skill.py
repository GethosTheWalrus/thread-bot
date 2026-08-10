"""Seed the OSRS DPS calculator skill."""

from alembic import op
from sqlalchemy import text


revision = "0028_osrs_dps_skill"
down_revision = "0027_mcp_tool_safety_overrides"
branch_labels = None
depends_on = None


OSRS_DPS_SKILL = """Use this skill for Old School RuneScape max-hit, accuracy, expected-hit, DPS, time-to-kill, special-attack, incoming-damage, and loadout-comparison questions.

Procedure:
1. Call use_skill before beginning so usage appears in the ThreadBot timeline and Discord activity.
2. Clarify the requested result and collect every material input. Ask one compact grouped question rather than guessing. Required details can include the exact monster and version or phase, current HP, raid invocation/path/party settings, player levels and boosts, complete equipment including ammunition or spell, attack style and stance, prayers, potions, Slayer/Wilderness/diary state, weapon-specific state, and ordered defence reductions.
3. Use the OSRS DPS MCP tools as the calculation authority. Call engine_info and report its upstream revision when provenance matters. Use search_monsters, search_equipment, and search_spells to resolve exact IDs and versions. Use combat_metadata for prayer, potion, and combat-style enum values. Never silently choose an ambiguous item, monster, spell, or version.
4. Build each loadout with hydrate_player so upstream equipment bonuses, legal styles, and attack speed are applied. Preserve itemVars for equipment such as blowpipes. Adjust the returned monster inputs for current HP, raid scaling, phase, and defence reductions before calculation.
5. Use compute_basic for outgoing DPS and normal/spec results, compute_reverse for incoming monster damage, compute_ttk_distribution for exact TTK distributions, and compare for graph-style comparisons. Use osrs_execute_worker only when exact upstream worker request semantics are specifically needed.
6. Do not recreate combat formulas with mental arithmetic or the generic calculator when the OSRS DPS MCP server is available. The deterministic MCP result is authoritative for the pinned upstream engine.
7. Validate that equipment slots, two-handed equipment, ammunition, spell, stance, current HP, and encounter settings match the user's intent. Surface every userIssues warning returned by the engine. Do not describe an unsupported upstream mechanic as calculated.
8. For comparisons, keep all assumptions identical except the variables the user asked to compare. Present a compact table with max hit, accuracy, expected hit, attack interval, DPS, and average TTK when available, plus absolute and percentage differences.
9. Cite the OSRS Wiki DPS calculator and include the engine/data revision from engine_info. Explain that parity means the result comes from the pinned OSRS Wiki calculator engine, including that engine's known limitations; it does not imply support for mechanics the upstream engine itself marks unsupported.

If the OSRS DPS MCP tools are unavailable, do not claim calculator parity. Offer to collect the missing inputs or provide a clearly labelled basic estimate using sourced formulas and the generic calculator."""


def upgrade():
    bind = op.get_bind()
    bind.execute(
        text(
            """INSERT INTO skills (name, description, content, is_active)
               SELECT :name, :description, :content, TRUE
               WHERE NOT EXISTS (
                   SELECT 1 FROM skills
                   WHERE lower(name) = lower(CAST(:name AS VARCHAR(255)))
               )"""
        ),
        {
            "name": "OSRS DPS calculation",
            "description": "Resolve OSRS loadouts and targets, then calculate DPS and TTK with the pinned OSRS Wiki calculator engine.",
            "content": OSRS_DPS_SKILL,
        },
    )


def downgrade():
    raise RuntimeError("OSRS DPS skill migration is forward-only")
