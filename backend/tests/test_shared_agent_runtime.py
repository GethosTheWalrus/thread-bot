import inspect

from app.workflows.thread_workflow import RunThreadWorkflow, _filter_agent_tools
from app.workflows.agent_workflows import AgentRunWorkflow
from app.workflows.policy_aware_thread_workflow import PolicyAwareThreadTurnWorkflow


def test_agent_tool_filter_uses_canonical_and_legacy_identities():
    tools = [
        {"function": {"name": "srv_lookup"}},
        {"function": {"name": "calculator"}},
    ]
    selected, mapping = _filter_agent_tools(
        tools, {"srv_lookup": {"server_name": "srv", "original_name": "lookup"}}, ["srv:lookup", "builtin:calculator"]
    )
    assert [item["function"]["name"] for item in selected] == ["srv_lookup", "calculator"]
    assert "srv_lookup" in mapping


def test_shared_agent_route_is_patched_and_legacy_workflow_retained():
    source = inspect.getsource(AgentRunWorkflow.run)
    assert 'workflow.patched("agent-shared-thread-turn-v1")' in source
    assert "RunThreadWorkflow.run" in source
    assert 'loaded.get("mode") == "live"' in source
    assert "generate_and_update_title" in source
    assert PolicyAwareThreadTurnWorkflow
    assert 'workflow.patched("agent-run-approval-policy-v1")' in source
    assert 'child_input["approval_policy"]' in source


def test_chat_path_has_no_agent_context_filter():
    source = inspect.getsource(RunThreadWorkflow.run)
    assert "agent_context = input.get(\"agent_context\")" in source
    assert "if agent_context is not None" in source
    assert 'final_message_args["agent_context"] = agent_context' in source
    assert '"agent_context": agent_context,' not in source


def test_shared_route_only_emits_supported_progress_event():
    source = inspect.getsource(AgentRunWorkflow.run)
    assert '"event_type": "run_started"' in source
    assert '"event_type": "run_completed"' not in source
    assert '"event_type": "run_failed"' not in source


def test_heartbeat_materialization_does_not_create_message():
    from app.agents.heartbeat_service import materialize_heartbeat_run

    assert "Message(" not in inspect.getsource(materialize_heartbeat_run)


def test_background_agent_continuation_is_bounded_and_noninteractive():
    source = inspect.getsource(RunThreadWorkflow.run)
    assert "automatic_continuations < 1" in source
    assert "Continuing automatically to finish the Agent turn" in source


def test_shared_heartbeat_has_scheduling_boundary_and_no_empty_message():
    source = inspect.getsource(RunThreadWorkflow.run)
    assert "There is no new user message" in source
    assert '"heartbeat-recurring-mandate-v2"' in source
    assert '"heartbeat-input-boundary-v1"' in source
    assert "must not be persisted as a Thread message" in source
    assert "do not continue, quote, concatenate, or repeat earlier assistant responses" in source
    assert "recurring_guidance" in source
    assert "unconditional recurring or proactive task" in source
    assert "Prior completion does not make a recurring mandate" in source
    assert "if llm_response:" in source
    assert '!= "heartbeat"' in source


def test_effect_free_runs_stay_on_legacy_safe_path():
    source = inspect.getsource(AgentRunWorkflow.run)
    assert 'shared_patch and loaded.get("mode") == "live"' in source


def test_legacy_tool_limit_behavior_is_behind_protocol_patch():
    source = inspect.getsource(PolicyAwareThreadTurnWorkflow._run_impl)
    assert "if protocol_v2:" in source
    assert 'return await self._finalize(request, "exhausted", last_text)' in source


def test_shared_runtime_strips_hidden_reasoning_behind_replay_patch():
    source = inspect.getsource(RunThreadWorkflow.run)
    assert 'workflow.patched("strip-hidden-reasoning-v1")' in source
    assert "strip_hidden_reasoning(llm_response)" in source


def test_agents_input_merges_consecutive_assistant_history_when_enabled():
    workflow_instance = object.__new__(RunThreadWorkflow)
    result = workflow_instance._agents_input(
        [
            {"role": "user", "content": "Initial request"},
            {"role": "assistant", "content": "First background update"},
            {"role": "assistant", "content": "Second background update"},
        ],
        merge_consecutive_assistant=True,
    )
    assert result == [
        {"role": "user", "content": "Initial request"},
        {
            "role": "assistant",
            "content": "First background update\n\nSecond background update",
        },
    ]


def test_consecutive_assistant_merge_is_behind_replay_patch():
    source = inspect.getsource(RunThreadWorkflow.run)
    assert '"merge-consecutive-assistant-v1"' in source


def test_live_agent_tools_use_replay_safe_durable_approval_gate():
    run_source = inspect.getsource(RunThreadWorkflow.run)
    gate_source = inspect.getsource(RunThreadWorkflow._execute_gated_agent_tool)
    assert 'workflow.patched("run-thread-approval-gate-v1")' in run_source
    for activity in (
        "persist_planned_action",
        "evaluate_policy_and_reserve_budget",
        "create_approval_request",
        "load_approval_state",
        "recheck_authorization",
        "persist_action_result",
    ):
        assert activity in gate_source
    assert "workflow.wait_condition" in gate_source
    assert "Denied by approver" in gate_source


def test_live_agent_tool_gate_serializes_concurrent_tool_callbacks():
    init_source = inspect.getsource(RunThreadWorkflow.__init__)
    tools_source = inspect.getsource(RunThreadWorkflow._agent_tools)

    assert "asyncio.Lock()" in init_source
    assert "async with self._agent_tool_lock" in tools_source
