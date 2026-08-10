"""Direct the OSRS DPS skill to the high-level calculation tool."""

from alembic import op
from sqlalchemy import text


revision = "0029_osrs_dps_high_level_tool"
down_revision = "0028_osrs_dps_skill"
branch_labels = None
depends_on = None


OLD_PROCEDURE = """4. Build each loadout with hydrate_player so upstream equipment bonuses, legal styles, and attack speed are applied. Preserve itemVars for equipment such as blowpipes. Adjust the returned monster inputs for current HP, raid scaling, phase, and defence reductions before calculation.
5. Use compute_basic for outgoing DPS and normal/spec results, compute_reverse for incoming monster damage, compute_ttk_distribution for exact TTK distributions, and compare for graph-style comparisons. Use osrs_execute_worker only when exact upstream worker request semantics are specifically needed."""

NEW_PROCEDURE = """4. Prefer calculate_dps for outgoing DPS. It accepts simple monster selectors, item IDs, levels, boosts, prayers, buffs, and combat-style fields, then resolves and hydrates exact upstream objects internally. Use the upstream field names atk, str, def, hp, magic, prayer, and ranged. Preserve itemVars for equipment such as blowpipes.
5. Use hydrate_player plus compute_basic only when a complete hydrated object is specifically needed. Use compute_reverse for incoming monster damage, compute_ttk_distribution for exact TTK distributions, and compare for graph-style comparisons. Use osrs_execute_worker only when exact upstream worker request semantics are specifically needed."""


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
    raise RuntimeError("OSRS DPS high-level tool migration is forward-only")
