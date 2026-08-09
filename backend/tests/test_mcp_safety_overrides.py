import inspect

import pytest
from pydantic import ValidationError

from app.api.routes import _available_tools_from_cache
from app.models.schemas import MCPServerCreate
from app.tools.catalog import (
    classify_tool_for_agent,
    mcp_tool_risk_profile,
    risk_profile_for_descriptor,
)
from app.workflows.policy_aware_thread_workflow import PolicyAwareThreadTurnWorkflow
from app.workflows.thread_workflow import RunThreadWorkflow


def test_mcp_safety_override_schema_accepts_only_supported_values():
    request = MCPServerCreate(
        name="DuckDuckGo",
        image="example/ddg",
        tool_safety_overrides={"search": "read_only", "fetch_content": "effectful"},
    )
    assert request.tool_safety_overrides == {
        "search": "read_only",
        "fetch_content": "effectful",
    }
    with pytest.raises(ValidationError):
        MCPServerCreate(
            name="DuckDuckGo",
            image="example/ddg",
            tool_safety_overrides={"search": "trusted"},
        )


def test_mcp_read_only_profile_changes_effect_classification_without_enabling_retries():
    read_only = mcp_tool_risk_profile("read_only")
    classification = classify_tool_for_agent("mcp:DuckDuckGo:search", read_only)
    assert classification == {
        "risk": "low",
        "category": "read",
        "effectful": False,
        "allowed": True,
        "retry_safe": False,
    }
    assert classify_tool_for_agent("mcp:DuckDuckGo:search")["effectful"] is True
    assert risk_profile_for_descriptor({"x-threadbot-mcp-safety": "read_only"}) == read_only
    assert risk_profile_for_descriptor({"x-threadbot-mcp-safety": "invalid"}) is None


def test_cached_tool_shapes_remain_compatible():
    expected = [("search", "Search the web")]
    legacy = _available_tools_from_cache([{"name": "search", "description": "Search the web"}])
    current = _available_tools_from_cache({"tools": [{"name": "search", "description": "Search the web"}]})
    assert [(tool.name, tool.description) for tool in legacy] == expected
    assert [(tool.name, tool.description) for tool in current] == expected


def test_mcp_safety_profiles_are_replay_patched_through_both_agent_workflows():
    shared_run = inspect.getsource(RunThreadWorkflow.run)
    shared_gate = inspect.getsource(RunThreadWorkflow._execute_gated_agent_tool)
    policy_run = inspect.getsource(PolicyAwareThreadTurnWorkflow._run_impl)
    assert 'workflow.patched("mcp-tool-safety-v1")' in shared_run
    assert '"risk_profile": risk_profile' in shared_gate
    assert 'workflow.patched("policy-aware-mcp-tool-safety-v1")' in policy_run
    assert 'policy_args["risk_profile"] = risk_profile' in policy_run
    assert 'recheck_args["risk_profile"] = risk_profile' in policy_run
