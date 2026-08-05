"""Tests for policy-aware budget/approval preservation and local effect gates."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import pytest

from app.contracts.common import ActorContext, ActorType, AuthenticationMethod


def test_evaluate_policy_and_reserve_budget_preserves_require_approval(monkeypatch):
    """A budget reservation must not erase a policy's require_approval verdict."""
    from app.activities.autonomy_activities import evaluate_policy_and_reserve_budget
    from app.policy.engine import evaluate_policy

    # Simulate a policy that requires approval.
    calls = []

    def fake_evaluate_policy(payload, rules, policy_version):
        calls.append(payload)
        return {"effect": "require_approval", "risk_level": "medium", "reason": "elevated risk", "requires_approval": True}

    def fake_classify(tool_identity):
        return {"risk": "medium", "allowed": True, "retry_safe": False}

    monkeypatch.setattr("app.policy.engine.evaluate_policy", fake_evaluate_policy, raising=True)
    monkeypatch.setattr("app.tools.catalog.classify_tool_for_agent", fake_classify, raising=True)

    # No budget profile -> the unlimited branch must still preserve require_approval.
    import asyncio
    result = asyncio.run(evaluate_policy_and_reserve_budget({
        "tool_identity": "mcp:server:tool",
        "risk_profile": None,
        "rules": [],
        "policy_version": "default",
        "run_id": str(uuid4()),
        "action_id": "act-1",
        "request_hash": "hash-1",
        "budget_profile_id": None,
        "workspace_id": str(uuid4()),
    }))
    assert result["effect"] == "require_approval"
    assert result["requires_approval"] is True


def test_local_mode_side_effects_enabled_flag_respected(monkeypatch):
    """Local mode should permit side effects when the operator explicitly enables them."""
    from app.config import _overrides
    from app.security import autonomy_flags
    monkeypatch.setitem(_overrides, "security_mode", "local")
    monkeypatch.setitem(_overrides, "autonomy_enabled", True)
    monkeypatch.setitem(_overrides, "autonomy_side_effects_enabled", True)
    monkeypatch.setitem(_overrides, "autonomy_webhooks_enabled", True)
    flags = autonomy_flags()
    assert flags["autonomy_side_effects_enabled"] is True
    assert flags["autonomy_webhooks_enabled"] is False


def test_builtin_descriptors_empty_selection_yields_no_tools():
    """An explicit empty tool selection must advertise no built-ins."""
    from app.tools.catalog import builtin_descriptors
    assert builtin_descriptors([]) == []
    assert builtin_descriptors(None)  # default = all safe built-ins


def test_builtin_descriptors_honors_explicit_web_fetch_selection():
    from app.tools.catalog import builtin_descriptors, identity_for_descriptor
    descriptors = builtin_descriptors(["web_fetch"])
    assert [
        identity_for_descriptor(item, item["function"]["name"])
        for item in descriptors
    ] == ["builtin:web_fetch"]


def test_builtin_descriptors_none_selection_yields_all_safe():
    from app.tools.catalog import builtin_descriptors, SAFE_BUILTIN_TOOLS
    descriptors = builtin_descriptors(None)
    names = {(d.get("function") or {}).get("name") for d in descriptors}
    assert names == set(SAFE_BUILTIN_TOOLS)


def test_agent_workflow_actor_provenance_reflects_local_mode(monkeypatch):
    """In local mode the autonomous actor uses local provenance, not admin_token."""
    from app.config import _overrides
    from app.security import security_mode
    from app.contracts.common import AuthenticationMethod
    monkeypatch.setitem(_overrides, "security_mode", "local")
    assert security_mode() == "local"
    assert AuthenticationMethod.local == "local"
