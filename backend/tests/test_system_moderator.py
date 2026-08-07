import asyncio
import inspect

from app.activities.llm_activities import save_message
from app.agents.autonomy_service import (
    SYSTEM_MODERATOR_HANDLE,
    SYSTEM_MODERATOR_PROMPT,
    ensure_system_moderator,
)
from app.workflows.thread_workflow import RunThreadWorkflow
from app.activities.agent_activities import route_agent_output


def test_system_moderator_has_a_fixed_routing_only_contract():
    assert SYSTEM_MODERATOR_HANDLE == "moderator"
    assert "never answer" in SYSTEM_MODERATOR_PROMPT.lower()
    assert "only that Agent's @handle" in SYSTEM_MODERATOR_PROMPT
    source = inspect.getsource(ensure_system_moderator)
    assert 'is_moderator=True, is_system=True' in source
    assert 'status="active"' in source
    assert '"tool_selection": []' in source


def test_routing_only_message_persistence_is_suppressed_before_database_io():
    result = asyncio.run(save_message({
        "thread_id": "00000000-0000-0000-0000-000000000001",
        "role": "assistant",
        "content": "This must never be visible",
        "agent_context": {"routing_only": True},
    }))
    assert result == {"completed_turns": None, "suppressed": True}


def test_shared_runtime_enforces_invisible_router_and_no_speech_or_title():
    source = inspect.getsource(RunThreadWorkflow.run)
    assert "ABSOLUTE ROUTING-ONLY ROLE" in source
    assert "Your entire response must be exactly one @handle" in source
    assert "not routing_only and self._reachy_enabled_for_thread" in source
    assert "should_title = not routing_only" in source


def test_moderator_routing_reuses_original_user_message():
    source = inspect.getsource(route_agent_output)
    assert "source_agent.is_system and source.input_message_id" in source
    assert 'run.route = "moderator_routed"' in source
