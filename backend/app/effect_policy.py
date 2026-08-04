"""Server-side effect boundary for every autonomous execution path."""

EFFECT_FREE_MODES = frozenset({"dry_run", "replay", "canary_shadow"})


def is_effect_free_mode(mode: str | None) -> bool:
    return mode in EFFECT_FREE_MODES


def blocked_effect(mode: str | None, effect: str) -> str | None:
    if is_effect_free_mode(mode) and effect in {"mutation", "notification", "handoff", "reachy", "connector", "credential"}:
        return f"{effect} execution is suppressed in {mode} mode"
    return None


def effect_free_result(action_id: str, revision: int, mode: str, effect: str) -> dict:
    reason = blocked_effect(mode, effect) or "execution suppressed"
    return {
        "schema_version": 1, "action_id": action_id, "action_revision": revision,
        "status": "simulated", "display_content": f"{mode}: {reason}",
        "model_content": f"{mode}: {reason}", "outcome": None, "artifacts": [],
        "retry_safe": True, "error_code": "effect_free_mode",
    }
