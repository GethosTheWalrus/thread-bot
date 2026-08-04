from typing import Any
from app.autonomy_hashing import canonical_hash


def canonical_diff(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, Any]:
    before, after = before or {}, after or {}
    keys = sorted(set(before) | set(after))
    return {key: {"before": before.get(key), "after": after.get(key)} for key in keys if before.get(key) != after.get(key)}


def state_snapshot(value: dict[str, Any]) -> dict[str, Any]:
    return {"state": value, "state_hash": canonical_hash(value)}


def state_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {"before_hash": canonical_hash(before), "after_hash": canonical_hash(after), "diff": canonical_diff(before, after)}
