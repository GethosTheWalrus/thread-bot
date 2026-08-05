import inspect
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.reachy_bridge import _ReachyAgentTurn, _collect_turn_response, _start_thread_turn


def test_reachy_chat_and_agent_threads_use_distinct_execution_paths():
    source = inspect.getsource(_start_thread_turn)

    assert 'if (thread.mode or "chat") == "agent"' in source
    assert "parse_agent_mention" in source
    assert 'item.is_moderator and item.status == "active"' in source
    assert 'route="reachy"' in source
    assert "input_message_id=input_message.id" in source
    assert "TriggerDispatchWorkflow.run" in source
    assert "RunThreadWorkflow.run" in source


def test_reachy_agent_turn_waits_for_durable_agent_result():
    source = inspect.getsource(_collect_turn_response)

    assert "isinstance(handle, _ReachyAgentTurn)" in source
    assert 'result["status"] not in {"succeeded", "exhausted"}' in source


def test_reachy_agent_interrupt_targets_agent_run_workflow():
    source = inspect.getsource(_ReachyAgentTurn.cancel)

    assert 'workflow_id = f"agent-run:{self.run_id}"' in source
    assert "run.temporal_workflow_id" in source


@pytest.mark.asyncio
async def test_reachy_agent_result_returns_persisted_output():
    turn = _ReachyAgentTurn("dispatch", uuid4(), object(), object())
    turn.result = AsyncMock(return_value={
        "status": "succeeded",
        "output_summary": "Attributed Agent response",
        "failure_summary": "",
    })

    assert await _collect_turn_response(turn) == "Attributed Agent response"


@pytest.mark.asyncio
async def test_reachy_agent_result_surfaces_terminal_failure():
    turn = _ReachyAgentTurn("dispatch", uuid4(), object(), object())
    turn.result = AsyncMock(return_value={
        "status": "failed",
        "output_summary": "",
        "failure_summary": "model unavailable",
    })

    with pytest.raises(RuntimeError, match="model unavailable"):
        await _collect_turn_response(turn)
