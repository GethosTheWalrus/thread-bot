"""Teach the OSRS DPS skill to optimize candidate gear."""

from alembic import op
from sqlalchemy import text


revision = "0030_osrs_dps_gear_optimizer"
down_revision = "0029_osrs_dps_high_level_tool"
branch_labels = None
depends_on = None


OLD_PROCEDURE = """4. Prefer calculate_dps for outgoing DPS. It accepts simple monster selectors, item IDs, levels, boosts, prayers, buffs, and combat-style fields, then resolves and hydrates exact upstream objects internally. Use the upstream field names atk, str, def, hp, magic, prayer, and ranged. Preserve itemVars for equipment such as blowpipes.
5. Use hydrate_player plus compute_basic only when a complete hydrated object is specifically needed. Use compute_reverse for incoming monster damage, compute_ttk_distribution for exact TTK distributions, and compare for graph-style comparisons. Use osrs_execute_worker only when exact upstream worker request semantics are specifically needed."""

NEW_PROCEDURE = """4. For boss gearing or upgrade recommendations, clarify the exact boss/version, account stats, current setup, intended combat style, owned or eligible candidate items, account restrictions, and optional acquisition budget. Resolve every candidate with search_equipment. If a budget matters, source current prices and pass them as caller-supplied costs; the MCP server has no live price feed.
5. Use optimize_gear to rank candidate combinations. It optimizes only the supplied candidate pool. Describe an exhaustive result as the best among those candidates, never global best-in-slot. Clearly label beam-search results as approximate, surface cost/search warnings, and do not recommend items the account cannot equip or obtain.
6. Prefer calculate_dps for outgoing DPS comparisons that do not need optimization. It accepts simple monster selectors, item IDs, levels, boosts, prayers, buffs, and combat-style fields, then resolves and hydrates exact upstream objects internally. Use the upstream field names atk, str, def, hp, magic, prayer, and ranged. Preserve itemVars for equipment such as blowpipes.
7. Use hydrate_player plus compute_basic only when a complete hydrated object is specifically needed. Use compute_reverse for incoming monster damage, compute_ttk_distribution for exact TTK distributions, and compare for graph-style comparisons. Use osrs_execute_worker only when exact upstream worker request semantics are specifically needed."""


def upgrade():
    op.get_bind().execute(
        text(
            """UPDATE skills
               SET content = replace(content, :old, :new)
               WHERE lower(name) = lower('OSRS DPS calculation')
                 AND position(:old IN content) > 0"""
        ),
        {"old": OLD_PROCEDURE, "new": NEW_PROCEDURE},
    )


def downgrade():
    raise RuntimeError("OSRS DPS gear optimizer migration is forward-only")
