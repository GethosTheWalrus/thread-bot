from typing import Any
from app.autonomy_hashing import canonical_hash

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3, "unknown": 4}


def explain_risk(tool_identity: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or {}
    defaults = {
        "discord:": ("medium", "external_communication"),
        "temporal:": ("high", "write"),
        "mcp:": ("unknown", "unknown"),
        "reachy:": ("critical", "physical"),
    }
    default = next((value for prefix, value in defaults.items() if tool_identity.startswith(prefix)), ("unknown", "unknown"))
    if tool_identity.startswith("builtin:"):
        default = ("low", "read")
    risk = profile.get("risk_level") or default[0]
    category = profile.get("category") or default[1]
    requires = risk in {"medium", "high", "critical", "unknown"} or category in {"write", "destructive", "financial", "physical", "external_communication"}
    return {"tool_identity": tool_identity, "risk_level": risk, "category": category, "requires_approval": requires, "reason": f"{tool_identity} classified as {risk} {category}"}


def _matches(rule: dict[str, Any], request: dict[str, Any]) -> bool:
    if rule.get("scope") not in {None, "", "*", request.get("tool_identity"), request.get("tool_identity", "").split(":", 1)[0] + ":*"}:
        return False
    conditions = rule.get("conditions") or {}
    return all(request.get(key) == value for key, value in conditions.items())


def evaluate_policy(request: dict[str, Any], rules: list[dict[str, Any]] | None = None, policy_version: str = "default") -> dict[str, Any]:
    risk = explain_risk(request["tool_identity"], request.get("risk_profile"))
    matched = [rule for rule in (rules or []) if _matches(rule, request)]
    matched.sort(key=lambda item: (-int(item.get("priority", 0)), int(item.get("ordinal", 0))))
    deny = next((rule for rule in matched if rule.get("effect") == "deny"), None)
    approval = next((rule for rule in matched if rule.get("effect") == "require_approval"), None)
    if deny:
        effect, reason = "deny", "policy deny rule matched"
    elif approval or risk["requires_approval"]:
        effect, reason = "require_approval", "approval is required for this risk"
    elif matched and matched[0].get("effect") == "allow":
        effect, reason = "allow", "policy allow rule matched"
    else:
        effect, reason = ("deny", "no matching allow rule") if rules else ("allow", "reviewed low-risk operation")
    return {**risk, "effect": effect, "reason": reason, "policy_version": policy_version, "matched_rules": matched, "explanation_hash": canonical_hash({"effect": effect, "reason": reason, "policy_version": policy_version})}
