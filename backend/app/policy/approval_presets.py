from app.tools.catalog import classify_tool_for_agent


APPROVAL_PRESETS = frozenset({"all", "effectful", "never"})


def evaluate_approval_preset(tool_identity: str, preset: str) -> dict:
    """Apply the understandable approval preset to server-owned classification."""
    classification = classify_tool_for_agent(tool_identity)
    if not classification.get("allowed"):
        return {
            "effect": "deny",
            "risk_level": classification.get("risk", "unknown"),
            "reason": "tool is not in the server-owned catalog",
            "requires_approval": False,
        }

    normalized = preset if preset in APPROVAL_PRESETS else "effectful"
    needs_approval = normalized == "all" or (
        normalized == "effectful" and bool(classification.get("effectful", True))
    )
    if needs_approval:
        reason = (
            "Thread policy requires approval for every tool"
            if normalized == "all"
            else "Thread policy requires approval for writes, effects, and unknown tools"
        )
        return {
            "effect": "require_approval",
            "risk_level": classification.get("risk", "unknown"),
            "reason": reason,
            "requires_approval": True,
        }
    return {
        "effect": "allow",
        "risk_level": classification.get("risk", "unknown"),
        "reason": (
            "Thread policy does not require human approval"
            if normalized == "never"
            else "Thread policy allows this read-only or local utility"
        ),
        "requires_approval": False,
    }
