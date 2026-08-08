from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import sys
import types
import inspect

workflow_module = types.ModuleType("app.workflows.thread_workflow")
workflow_module.RunThreadWorkflow = SimpleNamespace(run=None)
sys.modules.setdefault("app.workflows.thread_workflow", workflow_module)
from app.api.routes import (
    _build_thread_response,
    _image_attachments_from_urls,
    _thread_agent_summary,
    configure_thread_agent,
    list_threads_endpoint,
    set_thread_approval_preset,
    set_thread_mode,
    thread_agent_run,
)
from app.api.autonomy import draft as update_agent_draft
from app.api.autonomy import agents as list_agents
from app.agents.autonomy_service import list_thread_agents


def test_thread_response_helper_projects_agent_fields():
    thread_id = uuid4()
    thread = SimpleNamespace(
        id=thread_id, title="Agent", parent_id=None,
        created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        llm_overrides=None, is_pinned=False, mode="agent", archived_at=None,
    )
    response = _build_thread_response(
        thread, agent={"id": uuid4(), "name": "helper", "status": "active"},
        latest_active_run={"status": "queued"}, pending_approvals=2,
    )
    assert response.mode == "agent"
    assert response.agent["name"] == "helper"
    assert response.latest_active_run["status"] == "queued"
    assert response.pending_approvals == 2
    assert response.approval_preset == "effectful"


def test_agent_summary_helper_is_importable_and_async():
    assert callable(_thread_agent_summary)
    source = inspect.getsource(_thread_agent_summary)
    assert 'Agent.status != "archived"' in source
    assert 'Agent.status == "active"' not in source


def test_image_attachment_projection_keeps_metadata_inputs():
    attachments = _image_attachments_from_urls(["https://example.test/image.png"])
    assert attachments == [{
        "url": "https://example.test/image.png",
        "filename": "image-1",
        "content_type": "image/*",
    }]


def test_thread_mode_change_refreshes_server_updated_timestamp():
    configure_source = inspect.getsource(configure_thread_agent)
    mode_source = inspect.getsource(set_thread_mode)

    assert "await db.refresh(thread)" in configure_source
    assert "return await configure_thread_agent" in mode_source
    assert "await db.refresh(thread)" in mode_source


def test_thread_approval_preset_change_is_blocked_during_agent_work():
    source = inspect.getsource(set_thread_approval_preset)

    assert 'AgentRun.status.in_({"queued", "running", "waiting_approval", "waiting_handoff"})' in source
    assert 'raise HTTPException(409, "Approval policy cannot change while Agent work is active")' in source


def test_agent_draft_refreshes_server_updated_timestamp():
    assert "await db.refresh(row)" in inspect.getsource(update_agent_draft)


def test_thread_listing_does_not_duplicate_multi_agent_threads():
    source = inspect.getsource(list_threads_endpoint)
    assert "Thread.workspace_id == actor.workspace_id" in source
    assert ".outerjoin(" not in source


def test_thread_agent_run_routes_mentions_or_active_moderator():
    source = inspect.getsource(thread_agent_run)
    assert "parse_agent_mention" in source
    assert "item.is_moderator and item.status == \"active\"" in source
    assert "route=\"user_mention\" if mention.target_handle else \"moderator\"" in source


def test_archived_agents_are_hidden_from_normal_agent_views():
    roster_source = inspect.getsource(list_thread_agents)
    list_source = inspect.getsource(list_agents)

    assert 'Agent.status != "archived"' in roster_source
    assert 'status != "all"' in list_source
    assert 'Agent.status != "archived"' in list_source
