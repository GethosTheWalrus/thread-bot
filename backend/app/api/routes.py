from typing import Annotated
from app.database import get_db
from app.database.crud import (
    create_thread,
    get_thread,
    get_thread_with_messages,
    get_root_threads,
    get_child_threads,
    add_message,
    update_thread_title,
    set_thread_pinned,
    delete_thread,
    create_mcp_server,
    get_mcp_servers,
    delete_mcp_server,
    toggle_mcp_server,
    update_mcp_server,
    create_skill,
    get_skills,
    update_skill,
    delete_skill,
    toggle_skill,
    get_enabled_thread_skills,
    get_thread_skill_overrides,
    set_thread_skill_overrides,
    upsert_settings,
    get_thread_tool_overrides,
    set_thread_tool_overrides,
    get_thread_llm_overrides,
    set_thread_llm_overrides,
    clear_thread_llm_overrides,
    get_discord_link,
    create_discord_link,
    set_discord_link_active,
    upsert_discord_server,
    get_discord_servers,
    get_discord_server_tool_overrides,
    set_discord_server_tool_overrides,
    get_discord_server,
)
from app.models.models import Thread, Message, DiscordThreadLink, GeneratedImage, GeneratedMedia
from app.models.schemas import (
    ThreadCreateRequest,
    ChatRequest,
    ContinueWorkflowRequest,
    ThreadResponse,
    MessageResponse,
    ThreadListItem,
    ThreadListResponse,
    RenameRequest,
    ThreadPinRequest,
    MCPServerCreate,
    MCPServerResponse,
    MCPTestResponse,
    ToolOverrideRequest,
    ToolOverridesResponse,
    ToolOverrideItem,
    SkillCreate,
    SkillResponse,
    SkillOverrideRequest,
    SkillOverridesResponse,
    SkillOverrideItem,
    AvailableServer,
    AvailableTool,
    DiscordSettingsRequest,
    DiscordSettingsResponse,
    DiscordShareRequest,
    DiscordThreadLinkResponse,
    DiscordServerResponse,
    DiscordServerListResponse,
    DiscordServerMcpOverridesResponse,
    DiscordServerMcpOverridesRequest,
    ReachyBindingResponse,
    ImageUploadResponse,
    UploadedImageResponse,
    ThreadLlmOverridesResponse,
    ThreadLlmOverridesRequest,
    ThreadContextResponse,
    ThreadModeRequest,
    ContextBudgetResponse,
    ContextCompositionItem,
    ContextSummaryResponse,
    SecurityModeRequest,
    SecurityResponse,
)
from fastapi import APIRouter, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect, File, UploadFile, Header
from fastapi.responses import FileResponse, Response, JSONResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from datetime import datetime, timedelta, timezone
import json
import secrets
from app.config import (
    get_settings,
    get_llm_config,
    get_setting,
    update_settings,
    get_discord_config,
    get_reachy_config,
    get_comfyui_workflow_presets,
    apply_thread_llm_overrides,
    clean_thread_llm_overrides,
    THREAD_OVERRIDABLE_KEYS,
    THREAD_OVERRIDABLE_LABELS,
    THREAD_OVERRIDABLE_BOOLEAN,
    THREAD_OVERRIDABLE_NUMERIC,
)
from temporalio.client import Client as TemporalClient
from temporalio.contrib.workflow_streams import WorkflowStreamClient
from app.workflows.thread_workflow import RunThreadWorkflow
from app.security import authenticate_websocket, browser_cookie_secure, security_mode, hash_token, LOCAL_WORKSPACE_ID, SESSION_MAX_AGE_SECONDS, require_actor, local_actor, require_owner_or_admin
from app.database.foundation import list_events
from app.models.foundation_models import ApiToken
from app.contracts import ActorContext
from app.models.agent_models import Agent
from app.models.run_models import AgentRun
from app.models.approval_models import ApprovalRequest

router = APIRouter(prefix="/api", tags=["chatbot"])


def get_temporal_client():
    """Get Temporal client from app state."""
    return getattr(router, "_temporal_client", None)


def set_temporal_client(client: TemporalClient):
    router._temporal_client = client


def _skills_for_llm(skills) -> list[dict]:
    return [
        {
            "id": str(skill.id),
            "name": skill.name,
            "description": skill.description or "",
            "content": skill.content,
        }
        for skill in skills
        if skill.content and skill.content.strip()
    ]


async def _active_thread_workflow_id(client: TemporalClient, thread_id: UUID) -> str | None:
    for prefix in (f"thread-{thread_id}-", f"discord-thread-{thread_id}-", f"reachy-thread-{thread_id}-"):
        query = f'ExecutionStatus="Running" AND WorkflowId STARTS_WITH "{prefix}"'
        async for execution in client.list_workflows(query=query, limit=1):
            return execution.id
    return None


async def _thread_is_generating(thread_id: UUID) -> bool:
    client = get_temporal_client()
    if not client:
        return False
    return await _active_thread_workflow_id(client, thread_id) is not None


async def _relay_workflow_stream(
    websocket: WebSocket,
    temporal_client: TemporalClient,
    workflow_id: str,
    *,
    from_offset: int = 0,
    discord_config: dict | None = None,
) -> None:
    import time

    stream = WorkflowStreamClient.create(temporal_client, workflow_id)
    last_typing_pulse = 0.0
    async for item in stream.subscribe(None, from_offset=from_offset, result_type=dict):
        if item.topic == "threadbot-model-events":
            raw = item.data
            if raw.get("type") != "response.output_text.delta":
                continue
            content = raw.get("delta") or ""
            if not content:
                continue
            event = {"type": "token", "content": content, "offset": item.offset}
        elif item.topic == "events":
            event = item.data
            # UI token frames are relayed from the SDK raw stream above so they
            # arrive while the model is generating, not after workflow replay.
            if event.get("type") == "token":
                continue
            event["offset"] = item.offset
        else:
            continue
        if discord_config and event.get("type") == "token":
            now = time.monotonic()
            if now - last_typing_pulse >= 8:
                last_typing_pulse = now
                try:
                    from app.discord_integration import send_discord_typing
                    await send_discord_typing(discord_config["discord_thread_id"], discord_config=discord_config)
                except Exception as exc:
                    print(f"[discord] stream relay typing pulse failed: {exc}", flush=True)
        await websocket.send_json(event)
        if event.get("type") in {"done", "error"}:
            break


async def _send_workflow_terminal_event(
    websocket: WebSocket,
    temporal_client: TemporalClient,
    workflow_id: str,
) -> None:
    handle = temporal_client.get_workflow_handle(workflow_id)
    try:
        result = await handle.result()
        title_result = await _start_title_activity(temporal_client, workflow_id, result)
        if isinstance(title_result, dict) and title_result.get("title"):
            try:
                await websocket.send_json({
                    "type": "title",
                    "thread_id": title_result.get("thread_id"),
                    "content": title_result["title"],
                })
            except Exception:
                pass
    except Exception as e:
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
        except Exception:
            pass
        raise

    try:
        await websocket.send_json({"type": "done"})
    except Exception:
        pass


async def _start_title_activity(
    temporal_client: TemporalClient,
    workflow_id: str,
    workflow_result,
) -> dict | None:
    if not isinstance(workflow_result, dict):
        return None
    title_args = workflow_result.get("title")
    if not title_args:
        return None

    from temporalio.common import ActivityIDConflictPolicy, ActivityIDReusePolicy
    from temporalio.exceptions import ActivityAlreadyStartedError
    from app.activities.llm_activities import generate_and_update_title

    settings = get_settings()
    activity_id = f"title-{workflow_id}"
    try:
        activity_handle = await temporal_client.start_activity(
            generate_and_update_title,
            title_args,
            id=activity_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            schedule_to_close_timeout=timedelta(seconds=90),
            start_to_close_timeout=timedelta(seconds=60),
            id_reuse_policy=ActivityIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=ActivityIDConflictPolicy.FAIL,
        )
        print(f"[title] enqueued standalone activity {activity_id}", flush=True)
        return await activity_handle.result()
    except ActivityAlreadyStartedError:
        return None
    except Exception as exc:
        print(f"[title] failed to start standalone activity {activity_id}: {exc}", flush=True)
        return None


async def _relay_workflow_until_complete(
    websocket: WebSocket,
    temporal_client: TemporalClient,
    workflow_id: str,
    *,
    from_offset: int = 0,
    discord_config: dict | None = None,
) -> None:
    import asyncio

    relay_task = asyncio.create_task(
        _relay_workflow_stream(
            websocket,
            temporal_client,
            workflow_id,
            from_offset=from_offset,
            discord_config=discord_config,
        )
    )
    completion_task = asyncio.create_task(
        _send_workflow_terminal_event(websocket, temporal_client, workflow_id)
    )
    done, pending = await asyncio.wait(
        {relay_task, completion_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in done:
        try:
            task.result()
        except (WebSocketDisconnect, RuntimeError):
            if task is relay_task:
                pass
            else:
                raise

    if relay_task in done and not completion_task.done():
        await completion_task

    for task in pending:
        if task is completion_task and task.done():
            continue
        task.cancel()


# ── Broadcast WebSocket (push thread-list updates to all clients) ─

_broadcast_clients: set[WebSocket] = set()


async def broadcast(event: dict) -> None:
    """Send a JSON event to all connected broadcast WebSocket clients."""
    dead: set[WebSocket] = set()
    for ws in _broadcast_clients:
        try:
            await ws.send_json(event)
        except Exception:
            dead.add(ws)
    for ws in dead:
        _broadcast_clients.discard(ws)


async def broadcast_thread_updated(thread_id: str) -> None:
    await broadcast({
        "type": "thread_updated",
        "thread_id": thread_id,
    })


def _build_message_response(m) -> MessageResponse:
    metadata = m.metadata_ or {}
    return MessageResponse(
        id=m.id,
        thread_id=m.thread_id,
        role=m.role,
        content=m.content,
        created_at=m.created_at,
        metadata=m.metadata_,
        agent_id=m.agent_id,
        agent_version_id=m.agent_version_id,
        agent_run_id=m.agent_run_id,
        agent_handle=m.agent_handle or metadata.get("agent_handle"),
        agent_name=metadata.get("agent_name"),
    )


def _build_discord_link_response(link) -> DiscordThreadLinkResponse | None:
    if not link:
        return None
    return DiscordThreadLinkResponse(
        thread_id=link.thread_id,
        guild_id=link.guild_id,
        channel_id=link.channel_id,
        discord_thread_id=link.discord_thread_id,
        discord_thread_name=link.discord_thread_name,
        is_active=link.is_active,
    )


def _build_discord_server_response(server, thread_count: int = 0) -> DiscordServerResponse:
    return DiscordServerResponse(
        guild_id=server.guild_id,
        guild_name=server.guild_name,
        default_channel_id=server.default_channel_id,
        thread_count=thread_count,
    )


def _build_available_server(server) -> AvailableServer:
    tools = _available_tools_from_cache(server.cached_tools)
    return AvailableServer(id=str(server.id), name=server.name, tools=tools)


def _available_tools_from_cache(cached_tools) -> list[AvailableTool]:
    if isinstance(cached_tools, dict):
        cached_tools = cached_tools.get("tools") or []
    if not isinstance(cached_tools, list):
        return []
    return [
        AvailableTool(name=t["name"], description=t.get("description", ""))
        for t in cached_tools
        if isinstance(t, dict) and t.get("name")
    ]


async def _get_discord_link_for_thread(db: AsyncSession, thread_id: UUID):
    return await get_discord_link(db, thread_id)


async def _get_discord_server_name_for_thread(db: AsyncSession, thread_id: UUID) -> str | None:
    discord_link = await get_discord_link(db, thread_id)
    if not discord_link or not discord_link.is_active:
        return None
    server = await get_discord_server(db, discord_link.guild_id)
    if not server:
        return None
    return server.guild_name or server.guild_id


def _build_workflow_discord_config(discord_config: dict, link) -> dict | None:
    if not link or not link.is_active:
        return None
    if not discord_config.get("enabled") or not discord_config.get("bot_token"):
        return None
    return {
        "enabled": discord_config.get("enabled"),
        "bot_token": discord_config.get("bot_token"),
        "guild_id": link.guild_id,
        "channel_id": link.channel_id,
        "discord_thread_id": link.discord_thread_id,
        "discord_thread_name": link.discord_thread_name,
    }


def _estimate_context_tokens(messages) -> int:
    total_chars = 0
    for message in messages or []:
        role = getattr(message, "role", None)
        if role == "thinking":
            continue
        total_chars += len(getattr(message, "content", None) or "")
    return int(total_chars / 4)


def _image_attachments_from_urls(urls: list[str] | None) -> list[dict]:
    attachments = []
    for idx, url in enumerate(urls or [], start=1):
        if not isinstance(url, str) or not url.startswith(("http://", "https://", "data:image/")):
            continue
        attachments.append({
            "url": url,
            "filename": f"image-{idx}",
            "content_type": "image/*",
        })
    return attachments


def _content_with_image_lines(content: str, attachments: list[dict]) -> str:
    lines = [content.strip()] if content and content.strip() else []
    for attachment in attachments:
        url = attachment.get("url")
        if url:
            lines.append(f"Image attachment: {attachment.get('filename') or 'image'} {url}")
    return "\n".join(lines)


def _clean_image_attachment_lines(content: str) -> str:
    return "\n".join(
        line for line in (content or "").splitlines()
        if not line.startswith("Image attachment: ")
    ).strip()


def _agent_run_projection(run, agent=None):
    if not run:
        return None
    agent = agent or getattr(run, "agent", None)
    return {"id": run.id, "agent_id": getattr(run, "agent_id", None), "agent_name": getattr(agent, "name", None), "agent_handle": getattr(agent, "handle", None), "status": run.status, "mode": run.mode,
            "route": getattr(run, "route", ""), "input_message_id": getattr(run, "input_message_id", None),
            "output_summary": run.output_summary, "failure_summary": run.failure_summary,
            "queued_at": run.queued_at, "started_at": run.started_at,
            "completed_at": run.completed_at}


def _agent_projection(agent):
    if not agent:
        return None
    return {"id": agent.id, "name": agent.name, "handle": agent.handle,
            "is_moderator": bool(agent.is_moderator), "status": agent.status,
            "execution_mode": agent.execution_mode, "active_version_id": agent.active_version_id}


async def _thread_agent_summary(db: AsyncSession, thread_id: UUID, workspace_id=LOCAL_WORKSPACE_ID):
    agent = await db.scalar(select(Agent).where(
        Agent.thread_id == thread_id, Agent.workspace_id == workspace_id,
        Agent.status != "archived", Agent.is_moderator.is_(True),
    ))
    if not agent:
        agent = await db.scalar(select(Agent).where(
            Agent.thread_id == thread_id, Agent.workspace_id == workspace_id,
            Agent.status != "archived",
        ).order_by(Agent.created_at, Agent.id))
    if not agent:
        return None, None, 0
    active = await db.scalar(select(AgentRun).where(
        AgentRun.thread_id == thread_id, AgentRun.workspace_id == workspace_id,
        AgentRun.status.in_({"queued", "running", "waiting_approval", "waiting_handoff"}),
    ).order_by(AgentRun.queued_at.desc(), AgentRun.id.desc()))
    pending = await db.scalar(select(func.count(ApprovalRequest.id)).join(
        AgentRun, AgentRun.id == ApprovalRequest.run_id
    ).where(ApprovalRequest.workspace_id == workspace_id, AgentRun.thread_id == thread_id,
            ApprovalRequest.status == "pending")) or 0
    active_agent = await db.get(Agent, active.agent_id) if active else None
    return _agent_projection(agent), _agent_run_projection(active, active_agent), int(pending)


async def _thread_roster_projection(db, thread_id, workspace_id):
    from app.models.agent_models import Agent
    agents = list((await db.execute(select(Agent).where(
        Agent.thread_id == thread_id, Agent.workspace_id == workspace_id,
        Agent.status != "archived").order_by(Agent.is_moderator.desc(), Agent.created_at))).scalars())
    active = list((await db.execute(select(AgentRun).where(
        AgentRun.thread_id == thread_id, AgentRun.workspace_id == workspace_id,
        AgentRun.status.in_({"queued", "running", "waiting_approval", "waiting_handoff"}))
        .order_by(AgentRun.queued_at))).scalars())
    agent_by_id = {a.id: a for a in agents}
    return [_agent_projection(a) for a in agents], [_agent_run_projection(r, agent_by_id.get(r.agent_id)) for r in active]


async def _thread_agent_summaries(db: AsyncSession, thread_ids: list[UUID], workspace_id=LOCAL_WORKSPACE_ID):
    if not thread_ids:
        return {}
    agents = list((await db.execute(select(Agent).where(
        Agent.thread_id.in_(thread_ids), Agent.workspace_id == workspace_id,
        Agent.status != "archived"))).scalars())
    runs = list((await db.execute(select(AgentRun).where(
        AgentRun.thread_id.in_(thread_ids), AgentRun.workspace_id == workspace_id,
        AgentRun.status.in_({"queued", "running", "waiting_approval", "waiting_handoff"}),
    ).order_by(AgentRun.queued_at.desc(), AgentRun.id.desc()))).scalars())
    approvals = (await db.execute(select(AgentRun.thread_id, func.count(ApprovalRequest.id)).join(
        ApprovalRequest, ApprovalRequest.run_id == AgentRun.id
    ).where(AgentRun.thread_id.in_(thread_ids), AgentRun.workspace_id == workspace_id,
            ApprovalRequest.workspace_id == workspace_id, ApprovalRequest.status == "pending")
        .group_by(AgentRun.thread_id))).all()
    by_id = {a.thread_id: a for a in agents if a.is_moderator}
    for row in agents:
        by_id.setdefault(row.thread_id, row)
    agent_by_id = {a.id: a for a in agents}
    active_by_thread = {}
    for run in runs:
        active_by_thread.setdefault(run.thread_id, run)
    pending_by_thread = dict(approvals)
    return {thread_id: (_agent_projection(by_id[thread_id]),
                         _agent_run_projection(active_by_thread.get(thread_id), agent_by_id.get(active_by_thread[thread_id].agent_id)) if thread_id in active_by_thread else None,
                        int(pending_by_thread.get(thread_id, 0)))
            for thread_id in by_id}


def _build_thread_response(thread, messages=None, is_generating=False, discord_link=None,
                           agent=None, latest_active_run=None, pending_approvals=0,
                           agents=None, active_runs=None) -> ThreadResponse:
    msgs = messages or []
    config = get_llm_config()
    reachy_thread_id = str((config.get("reachy") or {}).get("thread_id") or "")
    overrides = thread.llm_overrides or {}
    config = apply_thread_llm_overrides(config, overrides)
    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        parent_id=thread.parent_id,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        messages=[_build_message_response(m) for m in msgs],
        is_generating=is_generating,
        discord_link=_build_discord_link_response(discord_link),
        reachy_connected=reachy_thread_id == str(thread.id),
        estimated_tokens=_estimate_context_tokens(msgs),
        context_window=int(config.get("context_window", 8192)),
        has_llm_overrides=bool(overrides),
        is_pinned=bool(thread.is_pinned),
        mode=thread.mode or "chat",
        archived_at=thread.archived_at,
        agent=agent,
        latest_active_run=latest_active_run,
        pending_approvals=pending_approvals,
        agents=agents or ([agent] if agent else []),
        active_runs=active_runs or ([latest_active_run] if latest_active_run else []),
        agent_turn_limit=getattr(thread, "agent_turn_limit", 4) or 4,
        moderator=next((item for item in (agents or []) if item.get("is_moderator") and item.get("status") == "active"), agent if agent and agent.get("status") == "active" else None),
    )


async def _build_reachy_binding_response(db: AsyncSession) -> ReachyBindingResponse:
    from app.config import load_settings_from_db

    await load_settings_from_db()
    config = get_reachy_config()
    thread_id_raw = str(config.get("thread_id") or "").strip()
    thread_id = None
    thread_title = None
    if thread_id_raw:
        try:
            parsed = UUID(thread_id_raw)
            thread = await get_thread(db, parsed)
            if thread:
                thread_id = thread.id
                thread_title = thread.title
        except Exception:
            pass
    return ReachyBindingResponse(
        enabled=bool(config.get("enabled")),
        thread_id=thread_id,
        thread_title=thread_title,
        wake_word=config.get("wake_word") or "Reachy",
        task_queue=config.get("task_queue") or "reachy-local",
    )


@router.post("/threads", response_model=ThreadResponse)
async def create_thread_endpoint(
    request: ThreadCreateRequest,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_actor),
):
    thread = await create_thread(db, request.title, request.parent_id, mode=request.mode, workspace_id=actor.workspace_id)
    if request.mode == "agent":
        from app.agents.autonomy_service import create_agent
        try:
            await create_agent(db, actor.workspace_id, actor, {
                "name": request.agent_name or request.title, "thread_id": thread.id,
            })
        except (LookupError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if request.tool_overrides:
        overrides = [
            {
                "server_id": UUID(o.server_id),
                "tool_name": o.tool_name,
                "enabled": o.enabled,
            }
            for o in request.tool_overrides
        ]
        await set_thread_tool_overrides(db, thread.id, overrides)
    if request.skill_overrides:
        skill_overrides = [
            {
                "skill_id": UUID(o.skill_id),
                "enabled": o.enabled,
            }
            for o in request.skill_overrides
        ]
        await set_thread_skill_overrides(db, thread.id, skill_overrides)
    if request.tool_overrides or request.skill_overrides:
        await db.commit()
    summary, active, pending = await _thread_agent_summary(db, thread.id, actor.workspace_id)
    return _build_thread_response(thread, agent=summary, latest_active_run=active, pending_approvals=pending)


@router.post("/threads/{thread_id}/agent", response_model=ThreadResponse)
async def configure_thread_agent(thread_id: UUID, request: ThreadModeRequest, db: AsyncSession = Depends(get_db), fastapi_request: Request = None):
    """Attach the single agent to an existing thread, without replacing it."""
    from app.models.agent_models import Agent
    from app.agents.autonomy_service import create_agent
    actor = getattr(fastapi_request.state, "actor", None) if fastapi_request else None
    actor = actor or local_actor()
    thread = await db.scalar(select(Thread).where(Thread.id == thread_id))
    if not thread:
        raise HTTPException(404, "Thread not found")
    existing = await db.scalar(select(Agent).where(Agent.thread_id == thread_id))
    if existing:
        if existing.workspace_id != actor.workspace_id:
            raise HTTPException(404, "Thread not found")
        agent = existing
    else:
        try:
            agent = await create_agent(db, actor.workspace_id, actor, {"name": request.agent_name or thread.title, "thread_id": thread_id})
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc
    thread.mode = "agent"
    await db.flush()
    # The server-managed updated_at value is expired after the UPDATE. Refresh
    # it explicitly so response serialization never triggers async lazy I/O.
    await db.refresh(thread)
    messages = list((await db.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at))).scalars())
    summary, active, pending = await _thread_agent_summary(db, thread_id, actor.workspace_id)
    return _build_thread_response(thread, messages, agent=summary, latest_active_run=active, pending_approvals=pending)


@router.patch("/threads/{thread_id}/mode", response_model=ThreadResponse)
async def set_thread_mode(thread_id: UUID, request: ThreadModeRequest, db: AsyncSession = Depends(get_db), fastapi_request: Request = None):
    actor = getattr(fastapi_request.state, "actor", None) if fastapi_request else None
    actor = actor or local_actor()
    thread = await db.scalar(select(Thread).where(Thread.id == thread_id))
    if not thread:
        raise HTTPException(404, "Thread not found")
    if request.mode == "agent":
        return await configure_thread_agent(thread_id, request, db, fastapi_request)
    else:
        from app.models.agent_models import Agent
        agent = await db.scalar(select(Agent).where(Agent.thread_id == thread_id))
        if agent and agent.workspace_id != actor.workspace_id:
            raise HTTPException(404, "Thread not found")
        thread.mode = "chat"
        await db.flush()
        await db.refresh(thread)
    messages = list((await db.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at))).scalars())
    summary, active, pending = await _thread_agent_summary(db, thread_id, actor.workspace_id)
    return _build_thread_response(thread, messages, agent=summary, latest_active_run=active, pending_approvals=pending)


@router.get("/threads/{thread_id}/agent")
async def thread_agent(thread_id: UUID, db: AsyncSession = Depends(get_db), fastapi_request: Request = None):
    actor = getattr(fastapi_request.state, "actor", None) if fastapi_request else None
    actor = actor or local_actor()
    summary, active, pending = await _thread_agent_summary(db, thread_id, actor.workspace_id)
    if not summary:
        raise HTTPException(404, "Agent not found")
    return {"agent": summary, "latest_active_run": active, "pending_approvals": pending}


@router.put("/threads/{thread_id}/agent/draft")
async def thread_agent_draft(thread_id: UUID, body: dict, db: AsyncSession = Depends(get_db), fastapi_request: Request = None):
    from app.models.agent_models import Agent
    from app.agents.autonomy_service import upsert_draft
    from app.contracts.autonomy import DraftUpsert
    actor = getattr(fastapi_request.state, "actor", None) if fastapi_request else None
    actor = actor or local_actor()
    agent = await db.scalar(select(Agent).where(Agent.thread_id == thread_id, Agent.workspace_id == actor.workspace_id))
    if not agent:
        raise HTTPException(404, "Agent not found")
    draft = await upsert_draft(db, agent.id, actor.workspace_id, DraftUpsert.model_validate(body).model_dump(mode="json"))
    return draft


@router.post("/threads/{thread_id}/agent/activate")
async def thread_agent_activate(thread_id: UUID, db: AsyncSession = Depends(get_db), fastapi_request: Request = None):
    from app.models.agent_models import Agent
    from app.agents.autonomy_service import activate_draft
    actor = getattr(fastapi_request.state, "actor", None) if fastapi_request else None
    actor = actor or local_actor()
    agent = await db.scalar(select(Agent).where(Agent.thread_id == thread_id, Agent.workspace_id == actor.workspace_id))
    if not agent:
        raise HTTPException(404, "Agent not found")
    try:
        return await activate_draft(db, agent.id, actor.workspace_id, actor)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/threads/{thread_id}/agent/run")
async def thread_agent_run(thread_id: UUID, body: dict, db: AsyncSession = Depends(get_db), fastapi_request: Request = None, idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    from app.models.agent_models import Agent, AgentVersion
    from app.agents.autonomy_service import create_run
    from app.agent_mentions import parse_agent_mention
    actor = getattr(fastapi_request.state, "actor", None) if fastapi_request else None
    actor = actor or local_actor()
    message = str(body.get("message") or "")
    roster = list((await db.execute(select(Agent).where(
        Agent.thread_id == thread_id,
        Agent.workspace_id == actor.workspace_id,
        Agent.status != "archived",
    ).order_by(Agent.is_moderator.desc(), Agent.created_at, Agent.id))).scalars())
    mention = parse_agent_mention(message, [item.handle for item in roster])
    if mention.target_handle:
        agent = next((item for item in roster if item.handle.casefold() == mention.target_handle.casefold()), None)
        if agent and agent.status != "active":
            raise HTTPException(409, f"agent @{agent.handle} is {agent.status} and cannot receive runs")
    else:
        agent = next((item for item in roster if item.is_moderator and item.status == "active"), None)
    if not agent or not agent.active_version_id:
        raise HTTPException(409, "Agent thread has no active moderator or mentioned agent version")
    if not idempotency_key:
        raise HTTPException(422, "Idempotency-Key header is required")
    version = await db.get(AgentVersion, agent.active_version_id)
    run = await create_run(db, actor.workspace_id, actor, agent, version, message, str(body.get("mode") or "live"), None, idempotency_key, str(body.get("response_mode") or "both"), route="user_mention" if mention.target_handle else "moderator")
    await db.commit()
    client = get_temporal_client()
    if client:
        from app.workflows.agent_workflows import TriggerDispatchWorkflow
        try:
            await client.start_workflow(TriggerDispatchWorkflow.run, {"agent_id": str(agent.id), "event_id": str(run.trigger_event_id)}, id=f"trigger-dispatch:{run.trigger_event_id}", task_queue=get_settings().AGENT_TASK_QUEUE)
        except Exception as exc:
            from app.agents.autonomy_service import fail_queued_run
            await fail_queued_run(db, run.id, str(exc))
            await db.commit()
            raise HTTPException(status_code=503, detail="autonomy dispatch failed") from exc
    return run


@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    fastapi_request: Request,
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(status_code=426, detail="Chat streaming now uses /api/chat/ws WebSocket")


@router.websocket("/broadcast/ws")
async def broadcast_websocket(websocket: WebSocket):
    if await authenticate_websocket(websocket) is None:
        return
    await websocket.accept()
    _broadcast_clients.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _broadcast_clients.discard(websocket)


@router.websocket("/chat/ws")
async def chat_websocket(websocket: WebSocket):
    actor = await authenticate_websocket(websocket, {"owner", "admin"})
    if actor is None:
        return
    await websocket.accept()

    temporal_client = get_temporal_client()
    if not temporal_client:
        await websocket.send_json({"type": "error", "content": "Temporal client not available"})
        await websocket.close(code=1011)
        return

    try:
        payload = await websocket.receive_json()
        request = ChatRequest(**payload)
    except Exception as e:
        await websocket.send_json({"type": "error", "content": f"Invalid chat request: {e}"})
        await websocket.close(code=1003)
        return

    from app.config import load_settings_from_db
    from app.database import AsyncSessionLocal
    from app.database.autonomy import acquire_thread_lease
    from datetime import datetime, timezone
    from uuid import uuid4

    await load_settings_from_db()
    settings = get_settings()
    llm_config = get_llm_config().copy()
    chat_execution_id = f"chat-{uuid4().hex}"
    image_attachments = _image_attachments_from_urls(request.image_urls)
    message_metadata = {"image_attachments": image_attachments} if image_attachments else None
    message_content = _content_with_image_lines(request.content, image_attachments)

    async with AsyncSessionLocal() as setup_db:
        if request.thread_id:
            thread = await get_thread(setup_db, UUID(request.thread_id))
            if not thread:
                await websocket.send_json({"type": "error", "content": "Thread not found"})
                await websocket.close(code=1008)
                return
            thread_id = thread.id
            if (thread.mode or "chat") == "agent":
                from app.agents.autonomy_service import create_run
                from app.models.agent_models import Agent, AgentVersion
                if actor.workspace_id != (await setup_db.scalar(select(Agent.workspace_id).where(Agent.thread_id == thread.id))):
                    await websocket.send_json({"type": "error", "content": "Thread is not available"})
                    await websocket.close(code=1008)
                    return
                roster = list((await setup_db.execute(select(Agent).where(Agent.thread_id == thread.id, Agent.workspace_id == actor.workspace_id).order_by(Agent.is_moderator.desc(), Agent.created_at))).scalars().all())
                from app.agent_mentions import parse_agent_mention
                mention = parse_agent_mention(request.content, [item.handle for item in roster])
                agent = next((item for item in roster if item.handle.casefold() == (mention.target_handle or "").casefold()), None) if mention.target_handle else next((item for item in roster if item.is_moderator and item.status == "active"), None)
                if mention.target_handle and agent and agent.status != "active":
                    await websocket.send_json({"type": "error", "content": f"Agent @{agent.handle} is {agent.status} and cannot receive runs"})
                    await websocket.close(code=409)
                    return
                version = await setup_db.get(AgentVersion, agent.active_version_id) if agent and agent.active_version_id else None
                if not agent or not version:
                    await websocket.send_json({"type": "error", "content": "Agent thread is not activated"})
                    await websocket.close(code=409)
                    return
                import uuid as uuid_mod
                idempotency_key = f"thread-message:{thread.id}:{uuid_mod.uuid4()}"
                agent_message = _content_with_image_lines(request.content, _image_attachments_from_urls(request.image_urls))
                run = await create_run(setup_db, actor.workspace_id, actor, agent, version, agent_message, "live", None, idempotency_key, request.response_mode, message_metadata)
                await setup_db.commit()
                try:
                    from app.workflows.agent_workflows import TriggerDispatchWorkflow
                    await temporal_client.start_workflow(TriggerDispatchWorkflow.run, {"agent_id": str(agent.id), "event_id": str(run.trigger_event_id)}, id=f"trigger-dispatch:{run.trigger_event_id}", task_queue=get_settings().AGENT_TASK_QUEUE)
                except Exception as exc:
                    from app.agents.autonomy_service import fail_queued_run
                    await fail_queued_run(setup_db, run.id, str(exc))
                    await setup_db.commit()
                    await websocket.send_json({"type": "error", "content": f"Failed to start agent run: {exc}"})
                    await websocket.close(code=1011)
                    return
                await websocket.send_json({"type": "thread", "thread_id": str(thread.id), "run_id": str(run.id), "mode": "agent"})
                await websocket.send_json({"type": "done"})
                await websocket.close()
                return

        elif request.parent_id:
            thread = await create_thread(setup_db, "Reply", parent_id=request.parent_id, workspace_id=actor.workspace_id)
            thread_id = thread.id
            if request.tool_overrides:
                overrides = [
                    {
                        "server_id": UUID(o.server_id),
                        "tool_name": o.tool_name,
                        "enabled": o.enabled,
                    }
                    for o in request.tool_overrides
                ]
                await set_thread_tool_overrides(setup_db, thread_id, overrides)
            if request.skill_overrides:
                skill_overrides = [
                    {"skill_id": UUID(o.skill_id), "enabled": o.enabled}
                    for o in request.skill_overrides
                ]
                await set_thread_skill_overrides(setup_db, thread_id, skill_overrides)
        else:
            thread = await create_thread(setup_db, "New Thread", parent_id=None, workspace_id=actor.workspace_id)
            thread_id = thread.id
            if request.tool_overrides:
                overrides = [
                    {
                        "server_id": UUID(o.server_id),
                        "tool_name": o.tool_name,
                        "enabled": o.enabled,
                    }
                    for o in request.tool_overrides
                ]
                await set_thread_tool_overrides(setup_db, thread_id, overrides)
            if request.skill_overrides:
                skill_overrides = [
                    {"skill_id": UUID(o.skill_id), "enabled": o.enabled}
                    for o in request.skill_overrides
                ]
                await set_thread_skill_overrides(setup_db, thread_id, skill_overrides)

        await add_message(setup_db, thread_id, "user", message_content, metadata=message_metadata)

        # Load per-thread tool overrides (if any)
        thread_overrides = await get_thread_tool_overrides(setup_db, thread_id)
        if thread_overrides:
            llm_config["tool_overrides"] = [
                {
                    "server_id": str(o.server_id),
                    "tool_name": o.tool_name,
                    "enabled": o.enabled,
                }
                for o in thread_overrides
            ]

        enabled_skills = await get_enabled_thread_skills(setup_db, thread_id)
        if enabled_skills:
            llm_config["skills"] = _skills_for_llm(enabled_skills)

        # Apply per-thread LLM overrides on top of the global config.
        thread_llm_overrides = await get_thread_llm_overrides(setup_db, thread_id)
        if thread_llm_overrides:
            llm_config = apply_thread_llm_overrides(llm_config, thread_llm_overrides)

        discord_link = await get_discord_link(setup_db, thread_id)
        workflow_discord_config = _build_workflow_discord_config(get_discord_config(), discord_link)
        if workflow_discord_config:
            llm_config["discord"] = workflow_discord_config

        await setup_db.commit()

        if not await acquire_thread_lease(setup_db, actor.workspace_id, thread_id, None, chat_execution_id,
                                          datetime.now(timezone.utc) + timedelta(minutes=30),
                                          "chat_workflow", chat_execution_id):
            await websocket.send_json({"type": "error", "content": "Thread is busy with another execution"})
            await websocket.close(code=409)
            return
        await setup_db.commit()

    from app.discord_integration import sync_message_to_discord
    try:
        discord_message_id = await sync_message_to_discord(
            thread_id,
            "user",
            message_content,
            metadata=message_metadata or {},
            discord_config=llm_config.get("discord"),
        )
    except Exception:
        async with AsyncSessionLocal() as lease_db:
            from app.database.autonomy import release_thread_execution
            await release_thread_execution(lease_db, thread_id, "chat_workflow", chat_execution_id)
            await lease_db.commit()
        raise
    if discord_message_id and llm_config.get("discord"):
        llm_config["discord"]["reply_to_message_id"] = discord_message_id

    import uuid as uuid_mod

    run_id = f"thread-{thread_id}-{uuid_mod.uuid4().hex[:8]}"
    if llm_config.get("discord"):
        llm_config["discord"]["workflow_id"] = run_id

    try:
        workflow_handle = await temporal_client.start_workflow(
            RunThreadWorkflow.run,
            {"thread_id": str(thread_id), "message": message_content, "llm_config": llm_config},
            id=run_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
        if llm_config.get("discord"):
            import asyncio
            from app.discord_integration import _keep_discord_typing_until_done
            asyncio.create_task(_keep_discord_typing_until_done(workflow_handle, llm_config["discord"]))
        await websocket.send_json({"type": "thread", "thread_id": str(thread_id), "workflow_id": run_id})
    except Exception as e:
        async with AsyncSessionLocal() as lease_db:
            from app.database.autonomy import release_thread_execution
            await release_thread_execution(lease_db, thread_id, "chat_workflow", chat_execution_id)
            await lease_db.commit()
        await websocket.send_json({"type": "error", "content": f"Failed to start workflow: {e}"})
        await websocket.close(code=1011)
        return

    async def receive_controls():
        try:
            while True:
                msg = await websocket.receive_json()
                if msg.get("type") == "cancel":
                    handle = temporal_client.get_workflow_handle(run_id)
                    await handle.cancel()
                    await websocket.send_json({"type": "error", "content": "Generation cancelled"})
                    break
        except WebSocketDisconnect:
            return
        except Exception:
            return

    import asyncio
    control_task = asyncio.create_task(receive_controls())
    try:
        await _relay_workflow_until_complete(
            websocket,
            temporal_client,
            run_id,
            discord_config=llm_config.get("discord"),
        )
    except WebSocketDisconnect:
        pass
    finally:
        control_task.cancel()
        async with AsyncSessionLocal() as lease_db:
            from app.database.autonomy import release_thread_execution
            await release_thread_execution(lease_db, thread_id, "chat_workflow", chat_execution_id)
            await lease_db.commit()


@router.get("/generated-images/{filename}")
async def get_generated_image(filename: str, db: AsyncSession = Depends(get_db)):
    import os
    from app.config import get_llm_config

    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=404, detail="Image not found")
    image_dir = get_llm_config().get("generated_image_dir") or "/tmp/threadbot-generated-images"
    path = os.path.join(image_dir, filename)
    if not os.path.isfile(path):
        result = await db.execute(select(GeneratedImage).where(GeneratedImage.filename == filename))
        image = result.scalar_one_or_none()
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        return Response(content=image.content, media_type=image.content_type or "image/png")
    return FileResponse(path)


@router.get("/generated-media/{filename}")
async def get_generated_media(filename: str, db: AsyncSession = Depends(get_db)):
    import os
    from app.config import get_llm_config

    if "/" in filename or "\\" in filename or filename.startswith("."):
        raise HTTPException(status_code=404, detail="Media not found")
    media_dir = get_llm_config().get("generated_media_dir") or "/tmp/threadbot-generated-media"
    path = os.path.join(media_dir, filename)
    if not os.path.isfile(path):
        result = await db.execute(select(GeneratedMedia).where(GeneratedMedia.filename == filename))
        media = result.scalar_one_or_none()
        if not media:
            raise HTTPException(status_code=404, detail="Media not found")
        return Response(content=media.content, media_type=media.content_type or "application/octet-stream")
    return FileResponse(path)


@router.post("/uploads/images", response_model=ImageUploadResponse)
async def upload_images_endpoint(
    request: Request,
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
):
    import mimetypes
    import os
    import uuid as uuid_mod

    from app.config import get_llm_config

    max_files = 8
    max_image_bytes = 15 * 1024 * 1024
    max_total_bytes = 40 * 1024 * 1024

    if len(files) > max_files:
        raise HTTPException(status_code=413, detail=f"Too many images; maximum is {max_files}")

    image_dir = get_llm_config().get("generated_image_dir") or "/tmp/threadbot-generated-images"
    os.makedirs(image_dir, exist_ok=True)

    public_base_url = str(get_llm_config().get("public_base_url") or str(request.base_url).rstrip("/")).rstrip("/")
    uploaded: list[UploadedImageResponse] = []
    total_bytes = 0

    for upload in files:
        filename = upload.filename or "image"
        content_type = upload.content_type or ""
        if not content_type.startswith("image/"):
            content_type = mimetypes.guess_type(filename)[0] or content_type
        if not content_type.startswith("image/"):
            continue
        raw = await upload.read(max_image_bytes + 1)
        if not raw:
            continue
        if len(raw) > max_image_bytes:
            raise HTTPException(status_code=413, detail=f"Image {filename} exceeds 15MB")
        total_bytes += len(raw)
        if total_bytes > max_total_bytes:
            raise HTTPException(status_code=413, detail="Combined image upload exceeds 40MB")
        ext = os.path.splitext(filename)[1].lower()
        if not ext:
            ext = mimetypes.guess_extension(content_type) or ".png"
        if ext == ".jpe":
            ext = ".jpg"
        stored_filename = f"upload-{uuid_mod.uuid4().hex}{ext}"
        path = os.path.join(image_dir, stored_filename)
        with open(path, "wb") as f:
            f.write(raw)
        await db.merge(GeneratedImage(filename=stored_filename, content=raw, content_type=content_type))
        uploaded.append(
            UploadedImageResponse(
                filename=stored_filename,
                url=f"{public_base_url}/api/generated-images/{stored_filename}",
                content_type=content_type,
            )
        )

    if not uploaded:
        raise HTTPException(status_code=400, detail="No valid image files uploaded")

    await db.commit()
    return ImageUploadResponse(images=uploaded)


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads_endpoint(
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_actor),
    limit: int = 200,
    offset: int = 0,
):
    threads = list((await db.execute(select(Thread).where(
        Thread.parent_id.is_(None),
        Thread.archived_at.is_(None),
        Thread.workspace_id == actor.workspace_id,
    )
        .order_by(Thread.is_pinned.desc(), Thread.updated_at.desc()).limit(limit).offset(offset))).scalars())
    thread_items = []
    thread_ids = [t.id for t in threads]
    agent_summaries = await _thread_agent_summaries(db, thread_ids, actor.workspace_id)
    counts = dict((await db.execute(select(Message.thread_id, func.count(Message.id)).where(
        Message.thread_id.in_(thread_ids)).group_by(Message.thread_id))).all()) if thread_ids else {}
    reachy_thread_id = str(get_reachy_config().get("thread_id") or "")
    for t in threads:
        msg_count = int(counts.get(t.id, 0))
        discord_link = await _get_discord_link_for_thread(db, t.id)
        discord_server_name = await _get_discord_server_name_for_thread(db, t.id)
        agent_summary, active_run, pending = agent_summaries.get(t.id, (None, None, 0))
        roster, active_runs = await _thread_roster_projection(db, t.id, actor.workspace_id)
        thread_items.append(ThreadListItem(
            id=t.id,
            title=t.title,
            parent_id=t.parent_id,
            created_at=t.created_at,
            updated_at=t.updated_at,
            message_count=msg_count,
            is_discord_thread=bool(discord_link and discord_link.is_active),
            discord_server_name=discord_server_name,
            is_reachy_thread=reachy_thread_id == str(t.id),
            has_llm_overrides=bool(t.llm_overrides),
            is_pinned=bool(t.is_pinned),
            mode=t.mode or "chat", agent=agent_summary, latest_active_run=active_run, pending_approvals=pending,
            agents=roster, active_runs=active_runs, agent_turn_limit=getattr(t, "agent_turn_limit", 4) or 4,
            moderator=next((a for a in roster if a.get("is_moderator") and a.get("status") == "active"), None),
        ))
    return ThreadListResponse(threads=thread_items)


@router.get("/threads/{thread_id}", response_model=ThreadResponse)
async def get_thread_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_actor),
):
    thread = await db.scalar(select(Thread).outerjoin(Agent, Agent.thread_id == Thread.id)
        .where(Thread.id == thread_id, or_(Agent.id.is_(None), Agent.workspace_id == actor.workspace_id)))
    messages = []
    if thread:
        result = await db.execute(select(Message).where(Message.thread_id == thread_id)
                                  .order_by(Message.created_at, Message.id))
        messages = list(result.scalars())
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    is_generating = await _thread_is_generating(thread_id)

    discord_link = await _get_discord_link_for_thread(db, thread_id)
    agent_summary, active_run, pending = await _thread_agent_summary(db, thread_id, actor.workspace_id)
    roster, active_runs = await _thread_roster_projection(db, thread_id, actor.workspace_id)
    return _build_thread_response(thread, messages, is_generating=is_generating, discord_link=discord_link, agent=agent_summary, latest_active_run=active_run, pending_approvals=pending, agents=roster, active_runs=active_runs)


@router.get("/threads/{thread_id}/context", response_model=ThreadContextResponse)
async def get_thread_context_endpoint(thread_id: UUID, db: AsyncSession = Depends(get_db), actor: ActorContext = Depends(require_actor)):
    thread = await db.scalar(select(Thread).outerjoin(Agent, Agent.thread_id == Thread.id)
                             .where(Thread.id == thread_id,
                                    or_(Agent.id.is_(None), Agent.workspace_id == actor.workspace_id)))
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    result = await db.execute(
        select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at, Message.id)
    )
    messages = result.scalars().all()
    config = apply_thread_llm_overrides(get_llm_config(), thread.llm_overrides or {})
    context_window = int(config.get("context_window") or 8192)
    max_output_tokens = int(config.get("max_tokens") or 0)
    threshold = float(config.get("compaction_threshold") or 0.75)
    groups = {
        "user": ("User", 0, 0),
        "assistant": ("Assistant", 0, 0),
        "tool_context": ("Tool context", 0, 0),
        "summaries": ("Summaries", 0, 0),
        "system_context": ("System context", 0, 0),
        "other": ("Other", 0, 0),
    }
    for message in messages:
        if message.role == "thinking":
            continue
        content = message.content or ""
        key = {
            "user": "user", "assistant": "assistant",
            "tool_call": "tool_context", "tool_result": "tool_context",
        }.get(message.role)
        if message.role == "system":
            metadata = message.metadata_ or {}
            key = "summaries" if metadata.get("type") in {"compaction_summary", "internal_context_summary", "conversation_summary"} else "system_context"
        key = key or "other"
        label, chars, count = groups[key]
        groups[key] = (label, chars + len(content), count + 1)
    total_chars = sum(chars for _, chars, _ in groups.values())
    estimated_tokens = int(total_chars / 4)
    remainder = estimated_tokens
    for key, (label, chars, count) in groups.items():
        if count:
            tokens = int(chars / 4)
            groups[key] = (label, tokens, count)
            remainder -= tokens
    if remainder:
        for key, (label, tokens, count) in groups.items():
            if count:
                groups[key] = (label, tokens + remainder, count)
                break
    composition = [
        ContextCompositionItem(key=key, label=label, tokens=tokens, message_count=count)
        for key, (label, tokens, count) in groups.items() if tokens or count
    ]
    input_budget = max(context_window - max_output_tokens, 0)
    ratio = estimated_tokens / input_budget if input_budget else 0.0
    compaction_at = int(context_window * threshold)
    summary = None
    if thread.conversation_summary:
        turn_count = int(thread.conversation_summary_turn_count or 0)
        summary = ContextSummaryResponse(
            content=thread.conversation_summary,
            updated_at=thread.conversation_summary_updated_at,
            turn_count=turn_count,
            current_turn_count=int(thread.completed_turns or 0),
            stale=turn_count < int(thread.completed_turns or 0),
        )
    return ThreadContextResponse(
        thread_id=thread_id,
        budget=ContextBudgetResponse(
            context_window=context_window, max_output_tokens=max_output_tokens,
            input_budget=input_budget, estimated_tokens=estimated_tokens,
            remaining_tokens=max(input_budget - estimated_tokens, 0),
            usage_ratio=ratio, compaction_threshold=threshold,
            compaction_at_tokens=compaction_at,
            tokens_until_compaction=max(compaction_at - estimated_tokens, 0),
        ),
        composition=composition, summary=summary,
    )


@router.post("/threads/{thread_id}/continue")
async def continue_thread_workflow_endpoint(
    thread_id: UUID,
    request: ContinueWorkflowRequest,
    db: AsyncSession = Depends(get_db),
):
    thread = await get_thread(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    temporal_client = get_temporal_client()
    if not temporal_client:
        raise HTTPException(status_code=503, detail="Temporal client not available")
    workflow_id = await _active_thread_workflow_id(temporal_client, thread_id)
    if not workflow_id:
        raise HTTPException(status_code=409, detail="No active workflow for thread")
    handle = temporal_client.get_workflow_handle(workflow_id)
    await handle.signal("respond_continue", request.should_continue)
    return {"ok": True, "workflow_id": workflow_id}


@router.websocket("/threads/{thread_id}/ws")
async def reconnect_thread_websocket(websocket: WebSocket, thread_id: UUID, offset: int = 0):
    if await authenticate_websocket(websocket, {"owner", "admin"}) is None:
        return
    await websocket.accept()
    temporal_client = get_temporal_client()
    if not temporal_client:
        await websocket.send_json({"type": "error", "content": "Temporal client not available"})
        await websocket.close(code=1011)
        return

    workflow_id = await _active_thread_workflow_id(temporal_client, thread_id)
    if not workflow_id:
        await websocket.send_json({"type": "done"})
        await websocket.close()
        return

    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        discord_link = await _get_discord_link_for_thread(db, thread_id)
    discord_config = _build_workflow_discord_config(get_discord_config(), discord_link)

    await websocket.send_json({"type": "thread", "thread_id": str(thread_id), "workflow_id": workflow_id})

    async def receive_controls():
        try:
            while True:
                msg = await websocket.receive_json()
                if msg.get("type") == "cancel":
                    handle = temporal_client.get_workflow_handle(workflow_id)
                    await handle.cancel()
                    await websocket.send_json({"type": "error", "content": "Generation cancelled"})
                    break
        except WebSocketDisconnect:
            return
        except Exception:
            return

    import asyncio
    control_task = asyncio.create_task(receive_controls())
    try:
        await _relay_workflow_until_complete(
            websocket,
            temporal_client,
            workflow_id,
            from_offset=offset,
            discord_config=discord_config,
        )
    except WebSocketDisconnect:
        pass
    finally:
        control_task.cancel()


@router.get("/threads/{thread_id}/replies", response_model=list[ThreadListItem])
async def get_thread_replies_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    replies = await get_child_threads(db, thread_id)
    items = []
    reachy_thread_id = str(get_reachy_config().get("thread_id") or "")
    for t in replies:
        cnt = await db.execute(select(func.count(Message.id)).where(Message.thread_id == t.id))
        discord_link = await _get_discord_link_for_thread(db, t.id)
        discord_server_name = await _get_discord_server_name_for_thread(db, t.id)
        items.append(ThreadListItem(
            id=t.id,
            title=t.title,
            parent_id=t.parent_id,
            created_at=t.created_at,
            updated_at=t.updated_at,
            message_count=cnt.scalar_one(),
            is_discord_thread=bool(discord_link and discord_link.is_active),
            discord_server_name=discord_server_name,
            is_reachy_thread=reachy_thread_id == str(t.id),
            has_llm_overrides=bool(t.llm_overrides),
            is_pinned=bool(t.is_pinned),
        ))
    return items


@router.patch("/threads/{thread_id}", response_model=ThreadResponse)
async def update_thread_endpoint(
    thread_id: UUID,
    request: RenameRequest,
    db: AsyncSession = Depends(get_db),
):
    thread = await update_thread_title(db, thread_id, request.title)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    msg_result = await db.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at))
    messages = list(msg_result.scalars().all())

    from app.discord_integration import sync_title_to_discord
    await sync_title_to_discord(thread_id, request.title)

    await broadcast_thread_updated(str(thread_id))

    discord_link = await _get_discord_link_for_thread(db, thread_id)
    return _build_thread_response(thread, messages, discord_link=discord_link)


@router.patch("/threads/{thread_id}/pin", response_model=ThreadResponse)
async def pin_thread_endpoint(
    thread_id: UUID,
    request: ThreadPinRequest,
    db: AsyncSession = Depends(get_db),
):
    thread = await set_thread_pinned(db, thread_id, request.is_pinned)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    msg_result = await db.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at))
    messages = list(msg_result.scalars().all())
    discord_link = await _get_discord_link_for_thread(db, thread_id)
    await broadcast_thread_updated(str(thread_id))
    return _build_thread_response(thread, messages, discord_link=discord_link)


@router.delete("/threads/{thread_id}")
async def delete_thread_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_actor),
):
    from app.models.agent_models import Agent
    agent = await db.scalar(select(Agent).where(Agent.thread_id == thread_id))
    if agent and agent.workspace_id != actor.workspace_id:
        raise HTTPException(status_code=404, detail="Thread not found")
    if agent:
        thread = await get_thread(db, thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        thread.archived_at = datetime.now(timezone.utc)
        thread.mode = "agent"
        agent.status = "archived"
        await db.commit()
        return {"detail": "Thread archived"}
    discord_link = await get_discord_link(db, thread_id)
    if discord_link and discord_link.is_active:
        from app.discord_integration import DiscordIntegrationError, delete_discord_thread
        try:
            await delete_discord_thread(discord_link.discord_thread_id)
        except DiscordIntegrationError as e:
            print(
                f"[discord] failed to delete Discord thread {discord_link.discord_thread_id} "
                f"for local thread {thread_id}: {e}",
                flush=True,
            )
            if e.status == 403 and e.discord_code == 50013:
                raise HTTPException(status_code=409, detail=str(e)) from e
            raise HTTPException(status_code=502, detail=f"Failed to delete Discord thread: {e}") from e
        except Exception as e:
            print(
                f"[discord] failed to delete Discord thread {discord_link.discord_thread_id} "
                f"for local thread {thread_id}: {e}",
                flush=True,
            )
            raise HTTPException(status_code=502, detail=f"Failed to delete Discord thread: {e}") from e

    deleted = await delete_thread(db, thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    if str(get_reachy_config().get("thread_id") or "") == str(thread_id):
        update_settings(reachy_thread_id="")
        await upsert_settings(db, {"reachy_thread_id": ""})
        await db.commit()
    return {"detail": "Thread deleted"}


@router.delete("/threads")
async def delete_all_threads_endpoint(
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_actor),
):
    result = await db.execute(select(Thread).outerjoin(Agent, Agent.thread_id == Thread.id)
                              .where(or_(Agent.id.is_(None), Agent.workspace_id == actor.workspace_id)))
    threads = result.scalars().all()
    from app.discord_integration import delete_discord_thread

    for t in threads:
        discord_link = await get_discord_link(db, t.id)
        if discord_link and discord_link.is_active:
            try:
                await delete_discord_thread(discord_link.discord_thread_id)
            except Exception as exc:
                print(f"[discord] failed to delete Discord thread {discord_link.discord_thread_id}: {exc}", flush=True)
        agent = await db.scalar(select(Agent).where(Agent.thread_id == t.id,
                                                   Agent.workspace_id == actor.workspace_id))
        if agent:
            t.archived_at = datetime.now(timezone.utc)
            t.mode = "agent"
            agent.status = "archived"
        else:
            await db.delete(t)
    if get_reachy_config().get("thread_id"):
        update_settings(reachy_thread_id="")
        await upsert_settings(db, {"reachy_thread_id": ""})
    await db.commit()
    return {"detail": "All threads deleted"}


@router.get("/settings")
async def get_settings_endpoint():
    # Reload overrides from DB to ensure consistency across multiple backend pods
    from app.config import load_settings_from_db
    await load_settings_from_db()
    config = get_llm_config()
    return {
        "llm_model": config["model"],
        "llm_provider": config["provider"],
        "llm_api_url": config["api_url"],
        "llm_image_enabled": config["image_enabled"],
        "llm_image_api_url": config["image_api_url"],
        "llm_image_model": config["image_model"],
        "llm_image_provider": config["image_provider"],
        "llm_comfyui_api_url": config["comfyui_api_url"],
        "llm_comfyui_output_node": config["comfyui_output_node"],
        "llm_comfyui_negative_prompt": config["comfyui_negative_prompt"],
        "llm_comfyui_width": config["comfyui_width"],
        "llm_comfyui_height": config["comfyui_height"],
        "llm_comfyui_steps": config["comfyui_steps"],
        "llm_comfyui_cfg": config["comfyui_cfg"],
        "llm_comfyui_sampler": config["comfyui_sampler"],
        "llm_comfyui_scheduler": config["comfyui_scheduler"],
        "llm_comfyui_seed": config["comfyui_seed"],
        "llm_video_enabled": config["video_enabled"],
        "llm_comfyui_video_workflow": config["comfyui_video_workflow"],
        "llm_comfyui_image_to_video_workflow": config["comfyui_image_to_video_workflow"],
        "llm_comfyui_video_output_node": config["comfyui_video_output_node"],
        "llm_comfyui_video_input_image_node": config["comfyui_video_input_image_node"],
        "llm_comfyui_video_prompt_node": config["comfyui_video_prompt_node"],
        "llm_comfyui_video_negative_node": config["comfyui_video_negative_node"],
        "llm_comfyui_video_negative_prompt": config["comfyui_video_negative_prompt"],
        "llm_comfyui_video_width": config["comfyui_video_width"],
        "llm_comfyui_video_height": config["comfyui_video_height"],
        "llm_comfyui_video_frames": config["comfyui_video_frames"],
        "llm_comfyui_video_fps": config["comfyui_video_fps"],
        "llm_comfyui_video_steps": config["comfyui_video_steps"],
        "llm_comfyui_video_cfg": config["comfyui_video_cfg"],
        "llm_comfyui_video_sampler": config["comfyui_video_sampler"],
        "llm_comfyui_video_scheduler": config["comfyui_video_scheduler"],
        "llm_comfyui_video_seed": config["comfyui_video_seed"],
        "llm_comfyui_video_timeout": config["comfyui_video_timeout"],
        "llm_audio_enabled": config["audio_enabled"],
        "llm_tts_provider": config["tts_provider"],
        "llm_tts_api_url": config["tts_api_url"],
        "llm_tts_model": config["tts_model"],
        "llm_tts_voice": config["tts_voice"],
        "llm_tts_format": config["tts_format"],
        "llm_tts_timeout": config["tts_timeout"],
        "llm_lipsync_enabled": config["lipsync_enabled"],
        "llm_comfyui_lipsync_workflow": config["comfyui_lipsync_workflow"],
        "llm_comfyui_lipsync_output_node": config["comfyui_lipsync_output_node"],
        "llm_comfyui_lipsync_input_image_node": config["comfyui_lipsync_input_image_node"],
        "llm_comfyui_lipsync_input_audio_node": config["comfyui_lipsync_input_audio_node"],
        "llm_comfyui_lipsync_prompt_node": config["comfyui_lipsync_prompt_node"],
        "llm_comfyui_lipsync_negative_node": config["comfyui_lipsync_negative_node"],
        "llm_comfyui_lipsync_model": config["comfyui_lipsync_model"],
        "llm_comfyui_lipsync_patch": config["comfyui_lipsync_patch"],
        "llm_comfyui_lipsync_audio_encoder": config["comfyui_lipsync_audio_encoder"],
        "llm_comfyui_lipsync_vae": config["comfyui_lipsync_vae"],
        "llm_comfyui_lipsync_clip": config["comfyui_lipsync_clip"],
        "llm_comfyui_lipsync_width": config["comfyui_lipsync_width"],
        "llm_comfyui_lipsync_height": config["comfyui_lipsync_height"],
        "llm_comfyui_lipsync_frames": config["comfyui_lipsync_frames"],
        "llm_comfyui_lipsync_fps": config["comfyui_lipsync_fps"],
        "llm_comfyui_lipsync_steps": config["comfyui_lipsync_steps"],
        "llm_comfyui_lipsync_cfg": config["comfyui_lipsync_cfg"],
        "llm_comfyui_lipsync_audio_scale": config["comfyui_lipsync_audio_scale"],
        "llm_comfyui_lipsync_seed": config["comfyui_lipsync_seed"],
        "llm_comfyui_lipsync_timeout": config["comfyui_lipsync_timeout"],
        "llm_vision_enabled": config["vision_enabled"],
        "llm_vision_api_url": config["vision_api_url"],
        "llm_vision_model": config["vision_model"],
        "llm_vision_provider": config["vision_provider"],
        "llm_vision_max_tokens": config["vision_max_tokens"],
        "llm_vision_recipe_enabled": config["vision_recipe_enabled"],
        "llm_vision_pipeline_enabled": config["vision_pipeline_enabled"],
        "llm_vision_ocr_api_url": config["vision_ocr_api_url"],
        "llm_vision_ocr_model": config["vision_ocr_model"],
        "llm_vision_detail_api_url": config["vision_detail_api_url"],
        "llm_vision_detail_model": config["vision_detail_model"],
        "llm_vision_style_api_url": config["vision_style_api_url"],
        "llm_vision_style_model": config["vision_style_model"],
        "llm_comfyui_workflow": get_setting("LLM_COMFYUI_WORKFLOW") or "",
        "llm_comfyui_workflow_presets": get_comfyui_workflow_presets(),
        "llm_comfyui_selected_workflow": get_setting("LLM_COMFYUI_SELECTED_WORKFLOW") or "Flux.2 Klein 9B",
        "app_public_base_url": config["public_base_url"],
        "llm_temperature": config["temperature"],
        "llm_max_tokens": config["max_tokens"],
        "llm_stream_timeout": config["stream_timeout"],
        "llm_video_tool_timeout": config["video_tool_timeout"],
        "llm_max_iterations": config["max_iterations"],
        "llm_context_window": config["context_window"],
        "llm_compaction_threshold": config["compaction_threshold"],
        "llm_preserve_recent": config["preserve_recent"],
        "llm_tool_result_max_chars": config["tool_result_max_chars"],
        "has_api_key": bool(config["api_key"]),
        "discord": DiscordSettingsResponse(
            enabled=get_discord_config()["enabled"],
            has_bot_token=bool(get_discord_config()["bot_token"]),
            guild_id=get_discord_config()["guild_id"],
            channel_id=get_discord_config()["channel_id"],
            poll_interval_seconds=get_discord_config()["poll_interval_seconds"],
        ).model_dump(),
    }


@router.post("/auth/session")
async def create_session(request: Request, response: Response):
    """Exchange a bearer token for a short-lived HttpOnly browser cookie."""
    if security_mode() != "admin_token":
        raise HTTPException(status_code=400, detail="Browser sessions are only used in admin_token mode")
    authorization = request.headers.get("Authorization", "")
    if not authorization.lower().startswith("bearer ") or not authorization[7:].strip():
        raise HTTPException(status_code=401, detail="A bearer token is required to create a session")
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        from app.security import actor_from_request
        await actor_from_request(request, db)
    token = authorization[7:].strip()
    response.set_cookie(
        "threadbot_session",
        token,
        httponly=True,
        secure=browser_cookie_secure(request),
        samesite="strict",
        max_age=SESSION_MAX_AGE_SECONDS,
    )
    return {"ok": True, "expires_in": SESSION_MAX_AGE_SECONDS}


@router.get("/security", response_model=SecurityResponse)
async def get_security():
    mode = security_mode()
    return SecurityResponse(mode=mode, token_auth_enabled=mode == "admin_token")


@router.patch("/security/mode", response_model=SecurityResponse)
async def update_security_mode(
    payload: SecurityModeRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    actor: ActorContext = Depends(require_owner_or_admin),
):
    target_mode = payload.mode

    if target_mode == "admin_token":
        token = "tb_" + secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        rows = (await db.execute(
            select(ApiToken).where(
                ApiToken.workspace_id == LOCAL_WORKSPACE_ID,
                ApiToken.revoked_at.is_(None),
            )
        )).scalars().all()
        for row in rows:
            row.revoked_at = now
        db.add(ApiToken(
            workspace_id=LOCAL_WORKSPACE_ID,
            actor_id=actor.actor_id,
            token_hash=hash_token(token),
            token_prefix=token[:12],
            roles=["owner", "admin"],
        ))
        await upsert_settings(db, {"security_mode": "admin_token"})
        await db.commit()
        update_settings(SECURITY_MODE="admin_token")
        response.set_cookie(
            "threadbot_session",
            token,
            httponly=True,
            secure=browser_cookie_secure(request),
            samesite="strict",
            max_age=SESSION_MAX_AGE_SECONDS,
        )
        return SecurityResponse(mode="admin_token", token_auth_enabled=True, token=token)

    now = datetime.now(timezone.utc)
    rows = (await db.execute(
        select(ApiToken).where(
            ApiToken.workspace_id == LOCAL_WORKSPACE_ID,
            ApiToken.revoked_at.is_(None),
        )
    )).scalars().all()
    for row in rows:
        row.revoked_at = now
    await upsert_settings(db, {"security_mode": "local"})
    await db.commit()
    update_settings(SECURITY_MODE="local")
    response.delete_cookie("threadbot_session", httponly=True, secure=browser_cookie_secure(request), samesite="strict")
    return SecurityResponse(mode="local", token_auth_enabled=False)


@router.post("/auth/bootstrap")
async def bootstrap_token(request: Request, db: AsyncSession = Depends(get_db)):
    """Create an API token from a one-time configured bootstrap secret.

    The generated token is returned once and only its Argon2id hash is persisted.
    """
    if security_mode() != "admin_token":
        raise HTTPException(status_code=400, detail="Token bootstrap requires admin_token mode")
    configured = str(get_setting("ADMIN_BOOTSTRAP_TOKEN") or "")
    supplied = request.headers.get("Authorization", "")
    supplied = supplied[7:].strip() if supplied.lower().startswith("bearer ") else ""
    if not configured or not supplied or not secrets.compare_digest(supplied, configured):
        raise HTTPException(status_code=401, detail="Invalid bootstrap credentials")
    token = "tb_" + secrets.token_urlsafe(32)
    db.add(ApiToken(workspace_id=LOCAL_WORKSPACE_ID, actor_id="admin", token_hash=hash_token(token),
                    token_prefix=token[:12], roles=["owner", "admin"]))
    await db.commit()
    return {"token": token, "token_prefix": token[:12]}


@router.get("/events")
async def get_durable_events(
    actor: Annotated[ActorContext, Depends(require_actor)],
    after: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
):
    events = await list_events(db, actor.workspace_id, after=max(after, 0), limit=limit)
    return {"events": [{"cursor": e.sequence, "event_id": str(e.id), "event_type": e.event_type,
                         "payload": e.payload, "created_at": e.created_at} for e in events],
            "next_cursor": events[-1].sequence if events else after}


@router.websocket("/events/ws")
async def durable_events_websocket(websocket: WebSocket, after: int = 0):
    actor = await authenticate_websocket(websocket)
    if actor is None:
        return
    await websocket.accept()
    from app.database import AsyncSessionLocal
    import asyncio
    try:
        cursor = max(0, after)
        while True:
            # PostgreSQL rows are authoritative. A bounded poll also works when
            # LISTEN is unavailable and avoids a process-local event gap.
            async with AsyncSessionLocal() as db:
                events = await list_events(db, actor.workspace_id, after=cursor, limit=500)
            for event in events:
                cursor = event.sequence
                await websocket.send_json({"cursor": event.sequence, "event_id": str(event.id),
                                           "event_type": event.event_type, "payload": event.payload})
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
    except (WebSocketDisconnect, RuntimeError):
        return


@router.patch("/settings")
async def update_settings_endpoint(
    request: dict,
    db: AsyncSession = Depends(get_db),
):
    valid_keys = {
        "llm_api_url": "llm_api_url",
        "llm_api_key": "llm_api_key",
        "llm_model": "llm_model",
        "llm_image_enabled": "llm_image_enabled",
        "llm_image_api_url": "llm_image_api_url",
        "llm_image_model": "llm_image_model",
        "llm_image_provider": "llm_image_provider",
        "llm_comfyui_api_url": "llm_comfyui_api_url",
        "llm_comfyui_workflow": "llm_comfyui_workflow",
        "llm_comfyui_workflow_presets": "llm_comfyui_workflow_presets",
        "llm_comfyui_selected_workflow": "llm_comfyui_selected_workflow",
        "llm_comfyui_output_node": "llm_comfyui_output_node",
        "llm_comfyui_negative_prompt": "llm_comfyui_negative_prompt",
        "llm_comfyui_width": "llm_comfyui_width",
        "llm_comfyui_height": "llm_comfyui_height",
        "llm_comfyui_steps": "llm_comfyui_steps",
        "llm_comfyui_cfg": "llm_comfyui_cfg",
        "llm_comfyui_sampler": "llm_comfyui_sampler",
        "llm_comfyui_scheduler": "llm_comfyui_scheduler",
        "llm_comfyui_seed": "llm_comfyui_seed",
        "llm_video_enabled": "llm_video_enabled",
        "llm_comfyui_video_workflow": "llm_comfyui_video_workflow",
        "llm_comfyui_image_to_video_workflow": "llm_comfyui_image_to_video_workflow",
        "llm_comfyui_video_output_node": "llm_comfyui_video_output_node",
        "llm_comfyui_video_input_image_node": "llm_comfyui_video_input_image_node",
        "llm_comfyui_video_prompt_node": "llm_comfyui_video_prompt_node",
        "llm_comfyui_video_negative_node": "llm_comfyui_video_negative_node",
        "llm_comfyui_video_negative_prompt": "llm_comfyui_video_negative_prompt",
        "llm_comfyui_video_width": "llm_comfyui_video_width",
        "llm_comfyui_video_height": "llm_comfyui_video_height",
        "llm_comfyui_video_frames": "llm_comfyui_video_frames",
        "llm_comfyui_video_fps": "llm_comfyui_video_fps",
        "llm_comfyui_video_steps": "llm_comfyui_video_steps",
        "llm_comfyui_video_cfg": "llm_comfyui_video_cfg",
        "llm_comfyui_video_sampler": "llm_comfyui_video_sampler",
        "llm_comfyui_video_scheduler": "llm_comfyui_video_scheduler",
        "llm_comfyui_video_seed": "llm_comfyui_video_seed",
        "llm_comfyui_video_timeout": "llm_comfyui_video_timeout",
        "llm_audio_enabled": "llm_audio_enabled",
        "llm_tts_provider": "llm_tts_provider",
        "llm_tts_api_url": "llm_tts_api_url",
        "llm_tts_api_key": "llm_tts_api_key",
        "llm_tts_model": "llm_tts_model",
        "llm_tts_voice": "llm_tts_voice",
        "llm_tts_format": "llm_tts_format",
        "llm_tts_timeout": "llm_tts_timeout",
        "llm_lipsync_enabled": "llm_lipsync_enabled",
        "llm_comfyui_lipsync_workflow": "llm_comfyui_lipsync_workflow",
        "llm_comfyui_lipsync_output_node": "llm_comfyui_lipsync_output_node",
        "llm_comfyui_lipsync_input_image_node": "llm_comfyui_lipsync_input_image_node",
        "llm_comfyui_lipsync_input_audio_node": "llm_comfyui_lipsync_input_audio_node",
        "llm_comfyui_lipsync_prompt_node": "llm_comfyui_lipsync_prompt_node",
        "llm_comfyui_lipsync_negative_node": "llm_comfyui_lipsync_negative_node",
        "llm_comfyui_lipsync_model": "llm_comfyui_lipsync_model",
        "llm_comfyui_lipsync_patch": "llm_comfyui_lipsync_patch",
        "llm_comfyui_lipsync_audio_encoder": "llm_comfyui_lipsync_audio_encoder",
        "llm_comfyui_lipsync_vae": "llm_comfyui_lipsync_vae",
        "llm_comfyui_lipsync_clip": "llm_comfyui_lipsync_clip",
        "llm_comfyui_lipsync_width": "llm_comfyui_lipsync_width",
        "llm_comfyui_lipsync_height": "llm_comfyui_lipsync_height",
        "llm_comfyui_lipsync_frames": "llm_comfyui_lipsync_frames",
        "llm_comfyui_lipsync_fps": "llm_comfyui_lipsync_fps",
        "llm_comfyui_lipsync_steps": "llm_comfyui_lipsync_steps",
        "llm_comfyui_lipsync_cfg": "llm_comfyui_lipsync_cfg",
        "llm_comfyui_lipsync_audio_scale": "llm_comfyui_lipsync_audio_scale",
        "llm_comfyui_lipsync_seed": "llm_comfyui_lipsync_seed",
        "llm_comfyui_lipsync_timeout": "llm_comfyui_lipsync_timeout",
        "llm_vision_enabled": "llm_vision_enabled",
        "llm_vision_api_url": "llm_vision_api_url",
        "llm_vision_api_key": "llm_vision_api_key",
        "llm_vision_model": "llm_vision_model",
        "llm_vision_provider": "llm_vision_provider",
        "llm_vision_max_tokens": "llm_vision_max_tokens",
        "llm_vision_recipe_enabled": "llm_vision_recipe_enabled",
        "llm_vision_pipeline_enabled": "llm_vision_pipeline_enabled",
        "llm_vision_ocr_api_url": "llm_vision_ocr_api_url",
        "llm_vision_ocr_model": "llm_vision_ocr_model",
        "llm_vision_detail_api_url": "llm_vision_detail_api_url",
        "llm_vision_detail_model": "llm_vision_detail_model",
        "llm_vision_style_api_url": "llm_vision_style_api_url",
        "llm_vision_style_model": "llm_vision_style_model",
        "app_public_base_url": "app_public_base_url",
        "llm_provider": "llm_provider",
        "llm_temperature": "llm_temperature",
        "llm_max_tokens": "llm_max_tokens",
        "llm_stream_timeout": "llm_stream_timeout",
        "llm_video_tool_timeout": "llm_video_tool_timeout",
        "llm_max_iterations": "llm_max_iterations",
        "llm_context_window": "llm_context_window",
        "llm_compaction_threshold": "llm_compaction_threshold",
        "llm_preserve_recent": "llm_preserve_recent",
        "llm_tool_result_max_chars": "llm_tool_result_max_chars",
        "discord_enabled": "discord_enabled",
        "discord_bot_token": "discord_bot_token",
        "discord_guild_id": "discord_guild_id",
        "discord_channel_id": "discord_channel_id",
        "discord_poll_interval_seconds": "discord_poll_interval_seconds",
    }
    updates = {valid_keys[k]: v for k, v in request.items() if k in valid_keys}
    for key in ("discord_guild_id", "discord_channel_id"):
        if updates.get(key) == "":
            updates.pop(key, None)
    if updates:
        update_settings(**updates)
        # Persist to DB so values survive restarts
        persisted = {}
        for k, v in updates.items():
            persisted[k] = json.dumps(v) if k == "llm_comfyui_workflow_presets" else str(v)
        await upsert_settings(db, persisted)

    config = get_llm_config()
    return {
        "llm_model": config["model"],
        "llm_provider": config["provider"],
        "llm_api_url": config["api_url"],
        "llm_image_enabled": config["image_enabled"],
        "llm_image_api_url": config["image_api_url"],
        "llm_image_model": config["image_model"],
        "llm_image_provider": config["image_provider"],
        "llm_comfyui_api_url": config["comfyui_api_url"],
        "llm_comfyui_output_node": config["comfyui_output_node"],
        "llm_comfyui_negative_prompt": config["comfyui_negative_prompt"],
        "llm_comfyui_width": config["comfyui_width"],
        "llm_comfyui_height": config["comfyui_height"],
        "llm_comfyui_steps": config["comfyui_steps"],
        "llm_comfyui_cfg": config["comfyui_cfg"],
        "llm_comfyui_sampler": config["comfyui_sampler"],
        "llm_comfyui_scheduler": config["comfyui_scheduler"],
        "llm_comfyui_seed": config["comfyui_seed"],
        "llm_video_enabled": config["video_enabled"],
        "llm_comfyui_video_workflow": config["comfyui_video_workflow"],
        "llm_comfyui_image_to_video_workflow": config["comfyui_image_to_video_workflow"],
        "llm_comfyui_video_output_node": config["comfyui_video_output_node"],
        "llm_comfyui_video_input_image_node": config["comfyui_video_input_image_node"],
        "llm_comfyui_video_prompt_node": config["comfyui_video_prompt_node"],
        "llm_comfyui_video_negative_node": config["comfyui_video_negative_node"],
        "llm_comfyui_video_negative_prompt": config["comfyui_video_negative_prompt"],
        "llm_comfyui_video_width": config["comfyui_video_width"],
        "llm_comfyui_video_height": config["comfyui_video_height"],
        "llm_comfyui_video_frames": config["comfyui_video_frames"],
        "llm_comfyui_video_fps": config["comfyui_video_fps"],
        "llm_comfyui_video_steps": config["comfyui_video_steps"],
        "llm_comfyui_video_cfg": config["comfyui_video_cfg"],
        "llm_comfyui_video_sampler": config["comfyui_video_sampler"],
        "llm_comfyui_video_scheduler": config["comfyui_video_scheduler"],
        "llm_comfyui_video_seed": config["comfyui_video_seed"],
        "llm_comfyui_video_timeout": config["comfyui_video_timeout"],
        "llm_audio_enabled": config["audio_enabled"],
        "llm_tts_provider": config["tts_provider"],
        "llm_tts_api_url": config["tts_api_url"],
        "llm_tts_model": config["tts_model"],
        "llm_tts_voice": config["tts_voice"],
        "llm_tts_format": config["tts_format"],
        "llm_tts_timeout": config["tts_timeout"],
        "llm_lipsync_enabled": config["lipsync_enabled"],
        "llm_comfyui_lipsync_workflow": config["comfyui_lipsync_workflow"],
        "llm_comfyui_lipsync_output_node": config["comfyui_lipsync_output_node"],
        "llm_comfyui_lipsync_input_image_node": config["comfyui_lipsync_input_image_node"],
        "llm_comfyui_lipsync_input_audio_node": config["comfyui_lipsync_input_audio_node"],
        "llm_comfyui_lipsync_prompt_node": config["comfyui_lipsync_prompt_node"],
        "llm_comfyui_lipsync_negative_node": config["comfyui_lipsync_negative_node"],
        "llm_comfyui_lipsync_model": config["comfyui_lipsync_model"],
        "llm_comfyui_lipsync_patch": config["comfyui_lipsync_patch"],
        "llm_comfyui_lipsync_audio_encoder": config["comfyui_lipsync_audio_encoder"],
        "llm_comfyui_lipsync_vae": config["comfyui_lipsync_vae"],
        "llm_comfyui_lipsync_clip": config["comfyui_lipsync_clip"],
        "llm_comfyui_lipsync_width": config["comfyui_lipsync_width"],
        "llm_comfyui_lipsync_height": config["comfyui_lipsync_height"],
        "llm_comfyui_lipsync_frames": config["comfyui_lipsync_frames"],
        "llm_comfyui_lipsync_fps": config["comfyui_lipsync_fps"],
        "llm_comfyui_lipsync_steps": config["comfyui_lipsync_steps"],
        "llm_comfyui_lipsync_cfg": config["comfyui_lipsync_cfg"],
        "llm_comfyui_lipsync_audio_scale": config["comfyui_lipsync_audio_scale"],
        "llm_comfyui_lipsync_seed": config["comfyui_lipsync_seed"],
        "llm_comfyui_lipsync_timeout": config["comfyui_lipsync_timeout"],
        "llm_vision_enabled": config["vision_enabled"],
        "llm_vision_api_url": config["vision_api_url"],
        "llm_vision_model": config["vision_model"],
        "llm_vision_provider": config["vision_provider"],
        "llm_vision_max_tokens": config["vision_max_tokens"],
        "llm_vision_recipe_enabled": config["vision_recipe_enabled"],
        "llm_vision_pipeline_enabled": config["vision_pipeline_enabled"],
        "llm_vision_ocr_api_url": config["vision_ocr_api_url"],
        "llm_vision_ocr_model": config["vision_ocr_model"],
        "llm_vision_detail_api_url": config["vision_detail_api_url"],
        "llm_vision_detail_model": config["vision_detail_model"],
        "llm_vision_style_api_url": config["vision_style_api_url"],
        "llm_vision_style_model": config["vision_style_model"],
        "llm_comfyui_workflow": get_setting("LLM_COMFYUI_WORKFLOW") or "",
        "llm_comfyui_workflow_presets": get_comfyui_workflow_presets(),
        "llm_comfyui_selected_workflow": get_setting("LLM_COMFYUI_SELECTED_WORKFLOW") or "Flux.2 Klein 9B",
        "app_public_base_url": config["public_base_url"],
        "llm_temperature": config["temperature"],
        "llm_max_tokens": config["max_tokens"],
        "llm_stream_timeout": config["stream_timeout"],
        "llm_video_tool_timeout": config["video_tool_timeout"],
        "llm_max_iterations": config["max_iterations"],
        "llm_context_window": config["context_window"],
        "llm_compaction_threshold": config["compaction_threshold"],
        "llm_preserve_recent": config["preserve_recent"],
        "llm_tool_result_max_chars": config["tool_result_max_chars"],
        "has_api_key": bool(config["api_key"]),
    }


# ── Discord Integration ──────────────────────────────────────────────


@router.get("/discord/settings", response_model=DiscordSettingsResponse)
async def get_discord_settings_endpoint():
    from app.config import load_settings_from_db
    await load_settings_from_db()
    config = get_discord_config()
    return DiscordSettingsResponse(
        enabled=config["enabled"],
        has_bot_token=bool(config["bot_token"]),
        guild_id=config["guild_id"],
        channel_id=config["channel_id"],
        poll_interval_seconds=config["poll_interval_seconds"],
    )


@router.patch("/discord/settings", response_model=DiscordSettingsResponse)
async def update_discord_settings_endpoint(
    request: DiscordSettingsRequest,
    db: AsyncSession = Depends(get_db),
):
    updates = {}
    if request.enabled is not None:
        updates["discord_enabled"] = request.enabled
    if request.bot_token:
        updates["discord_bot_token"] = request.bot_token
    if request.guild_id is not None:
        updates["discord_guild_id"] = request.guild_id
    if request.channel_id is not None:
        updates["discord_channel_id"] = request.channel_id
    if request.poll_interval_seconds is not None:
        updates["discord_poll_interval_seconds"] = request.poll_interval_seconds

    if updates:
        update_settings(**updates)
        await upsert_settings(db, {k: str(v) for k, v in updates.items()})

    config = get_discord_config()
    return DiscordSettingsResponse(
        enabled=config["enabled"],
        has_bot_token=bool(config["bot_token"]),
        guild_id=config["guild_id"],
        channel_id=config["channel_id"],
        poll_interval_seconds=config["poll_interval_seconds"],
    )


@router.get("/discord/servers", response_model=DiscordServerListResponse)
async def list_discord_servers_endpoint(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import func
    from app.discord_integration import get_discord_guild

    servers = await get_discord_servers(db)
    response = []
    changed = False
    for server in servers:
        guild_name = server.guild_name
        if not guild_name or guild_name == server.guild_id:
            guild = await get_discord_guild(server.guild_id)
            guild_name = str(guild.get("name") or server.guild_id)
            if guild_name != server.guild_name:
                await upsert_discord_server(db, server.guild_id, guild_name, server.default_channel_id)
                changed = True
        cnt_result = await db.execute(
            select(func.count(DiscordThreadLink.id)).where(DiscordThreadLink.guild_id == server.guild_id)
        )
        response.append(_build_discord_server_response(server, cnt_result.scalar_one()))
    if changed:
        await db.commit()
    return DiscordServerListResponse(servers=response)


@router.get("/discord/servers/{guild_id}/mcp-overrides", response_model=DiscordServerMcpOverridesResponse)
async def get_discord_server_mcp_overrides_endpoint(guild_id: str, db: AsyncSession = Depends(get_db)):
    from app.discord_integration import get_discord_guild
    from app.database.crud import get_mcp_servers

    server = await get_discord_server(db, guild_id)
    if not server:
        guild = await get_discord_guild(guild_id)
        server = await upsert_discord_server(db, guild_id, str(guild.get("name") or guild_id))
        await db.commit()

    mcp_servers = await get_mcp_servers(db)
    overrides = await get_discord_server_tool_overrides(db, guild_id)
    return DiscordServerMcpOverridesResponse(
        guild_id=server.guild_id,
        guild_name=server.guild_name,
        servers=[_build_available_server(mcp_server) for mcp_server in mcp_servers],
        overrides=[
            ToolOverrideItem(
                server_id=str(o.server_id),
                tool_name=o.tool_name,
                enabled=o.enabled,
            )
            for o in overrides
        ],
    )


@router.put("/discord/servers/{guild_id}/mcp-overrides", response_model=DiscordServerMcpOverridesResponse)
async def set_discord_server_mcp_overrides_endpoint(
    guild_id: str,
    request: DiscordServerMcpOverridesRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.discord_integration import get_discord_guild
    from app.database.crud import get_mcp_servers

    server = await get_discord_server(db, guild_id)
    if not server:
        guild = await get_discord_guild(guild_id)
        server = await upsert_discord_server(db, guild_id, str(guild.get("name") or guild_id))

    await set_discord_server_tool_overrides(
        db,
        guild_id,
        [
            {
                "server_id": UUID(item.server_id),
                "tool_name": item.tool_name,
                "enabled": item.enabled,
            }
            for item in request.overrides
        ],
    )
    await db.commit()

    mcp_servers = await get_mcp_servers(db)
    return DiscordServerMcpOverridesResponse(
        guild_id=server.guild_id,
        guild_name=server.guild_name,
        servers=[_build_available_server(mcp_server) for mcp_server in mcp_servers],
        overrides=request.overrides,
    )


@router.post("/threads/{thread_id}/discord", response_model=DiscordThreadLinkResponse)
async def share_thread_to_discord_endpoint(
    thread_id: UUID,
    request: DiscordShareRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.discord_integration import (
        apply_discord_server_tool_defaults,
        create_discord_thread,
        get_discord_guild,
        post_existing_thread_to_discord,
    )

    thread = await get_thread(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    existing = await get_discord_link(db, thread_id)
    if existing:
        if not existing.is_active:
            existing.is_active = True
            await db.commit()
            await db.refresh(existing)
        return _build_discord_link_response(existing)

    config = get_discord_config()
    if not config["enabled"] or not config["bot_token"]:
        raise HTTPException(status_code=400, detail="Discord integration is not enabled or configured")

    guild_id = request.guild_id or config["guild_id"]
    channel_id = request.channel_id or config["channel_id"]
    if not guild_id or not channel_id:
        raise HTTPException(status_code=400, detail="Discord guild and channel are required")

    guild = await get_discord_guild(guild_id)
    await upsert_discord_server(db, guild_id, str(guild.get("name") or guild_id), channel_id)

    name = (request.name or thread.title or "ThreadBot Thread")[:100]
    try:
        discord_thread = await create_discord_thread(channel_id, name)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    link = await create_discord_link(
        db,
        thread_id,
        guild_id,
        channel_id,
        str(discord_thread["id"]),
        str(discord_thread.get("name") or name),
    )
    await apply_discord_server_tool_defaults(db, thread.id, guild_id)
    await db.commit()
    await post_existing_thread_to_discord(thread_id)
    return _build_discord_link_response(link)


@router.delete("/threads/{thread_id}/discord")
async def unshare_thread_from_discord_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    link = await set_discord_link_active(db, thread_id, False)
    if not link:
        raise HTTPException(status_code=404, detail="Discord link not found")
    await db.commit()
    return {"detail": "Discord sync disabled for thread"}


# ── Reachy Mini Binding ──────────────────────────────────────────────


@router.get("/reachy", response_model=ReachyBindingResponse)
async def get_reachy_binding_endpoint(db: AsyncSession = Depends(get_db)):
    return await _build_reachy_binding_response(db)


@router.post("/threads/{thread_id}/reachy", response_model=ReachyBindingResponse)
async def connect_thread_to_reachy_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    thread = await get_thread(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    updates = {
        "reachy_enabled": True,
        "reachy_thread_id": str(thread_id),
    }
    update_settings(**updates)
    await upsert_settings(db, {k: str(v) for k, v in updates.items()})
    await db.commit()
    await broadcast_thread_updated(str(thread_id))
    return await _build_reachy_binding_response(db)


@router.delete("/threads/{thread_id}/reachy", response_model=ReachyBindingResponse)
async def disconnect_thread_from_reachy_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    config = get_reachy_config()
    if str(config.get("thread_id") or "") != str(thread_id):
        return await _build_reachy_binding_response(db)

    updates = {"reachy_thread_id": ""}
    update_settings(**updates)
    await upsert_settings(db, updates)
    await db.commit()
    await broadcast_thread_updated(str(thread_id))
    return await _build_reachy_binding_response(db)


def _build_thread_llm_overrides_response(thread_id: UUID, overrides: dict, defaults: dict) -> ThreadLlmOverridesResponse:
    schema = {
        key: {
            "label": THREAD_OVERRIDABLE_LABELS.get(key, key),
            "type": (
                "boolean" if key in THREAD_OVERRIDABLE_BOOLEAN
                else "number" if key in THREAD_OVERRIDABLE_NUMERIC
                else "string"
            ),
        }
        for key in THREAD_OVERRIDABLE_KEYS
    }
    return ThreadLlmOverridesResponse(
        thread_id=thread_id,
        overrides=overrides or {},
        defaults=defaults or {},
        schema=schema,
    )


@router.get("/threads/{thread_id}/llm-overrides", response_model=ThreadLlmOverridesResponse)
async def get_thread_llm_overrides_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    thread = await get_thread(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    overrides = await get_thread_llm_overrides(db, thread_id)
    defaults = get_llm_config()
    return _build_thread_llm_overrides_response(thread_id, overrides, defaults)


@router.put("/threads/{thread_id}/llm-overrides", response_model=ThreadLlmOverridesResponse)
async def put_thread_llm_overrides_endpoint(
    thread_id: UUID,
    request: ThreadLlmOverridesRequest,
    db: AsyncSession = Depends(get_db),
):
    thread = await get_thread(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    cleaned = clean_thread_llm_overrides(request.overrides or {})
    if cleaned:
        await set_thread_llm_overrides(db, thread_id, cleaned)
    else:
        await clear_thread_llm_overrides(db, thread_id)
    await db.commit()
    await broadcast_thread_updated(str(thread_id))
    defaults = get_llm_config()
    return _build_thread_llm_overrides_response(thread_id, cleaned, defaults)


@router.delete("/threads/{thread_id}/llm-overrides", response_model=ThreadLlmOverridesResponse)
async def delete_thread_llm_overrides_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    thread = await get_thread(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    await clear_thread_llm_overrides(db, thread_id)
    await db.commit()
    await broadcast_thread_updated(str(thread_id))
    defaults = get_llm_config()
    return _build_thread_llm_overrides_response(thread_id, {}, defaults)


@router.get("/mcp", response_model=list[MCPServerResponse])
async def list_mcp_servers_endpoint(db: AsyncSession = Depends(get_db)):
    from app.encryption import decrypt_dict
    servers = await get_mcp_servers(db)
    result = []
    for s in servers:
        s.env_vars = await decrypt_dict(s.env_vars) or {}
        s.args = await decrypt_dict(s.args) or {}
        s.registry_credentials = await decrypt_dict(s.registry_credentials) or {}
        result.append(s)
    return result


@router.get("/skills", response_model=list[SkillResponse])
async def list_skills_endpoint(db: AsyncSession = Depends(get_db)):
    return await get_skills(db)


@router.post("/skills", response_model=SkillResponse)
async def create_skill_endpoint(request: SkillCreate, db: AsyncSession = Depends(get_db)):
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Skill content is required")
    return await create_skill(db, request.name.strip(), request.description or "", request.content)


@router.patch("/skills/{skill_id}", response_model=SkillResponse)
async def update_skill_endpoint(
    skill_id: UUID,
    request: SkillCreate,
    db: AsyncSession = Depends(get_db),
):
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Skill content is required")
    skill = await update_skill(
        db,
        skill_id,
        name=request.name.strip(),
        description=request.description or "",
        content=request.content,
    )
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.patch("/skills/{skill_id}/toggle", response_model=SkillResponse)
async def toggle_skill_endpoint(skill_id: UUID, db: AsyncSession = Depends(get_db)):
    skill = await toggle_skill(db, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill


@router.delete("/skills/{skill_id}")
async def delete_skill_endpoint(skill_id: UUID, db: AsyncSession = Depends(get_db)):
    deleted = await delete_skill(db, skill_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"detail": "Skill deleted"}


@router.get("/skills/thread-overrides", response_model=SkillOverridesResponse)
async def get_global_skill_overrides(db: AsyncSession = Depends(get_db)):
    return SkillOverridesResponse(skills=await get_skills(db), overrides=[])


@router.post("/mcp", response_model=MCPServerResponse)
async def create_mcp_server_endpoint(request: MCPServerCreate, db: AsyncSession = Depends(get_db)):
    from app.encryption import decrypt_dict
    server = await create_mcp_server(
        db,
        request.name,
        request.image,
        request.env_vars,
        request.args,
        request.registry_credentials,
    )
    # Return decrypted values so the frontend can display them
    server.env_vars = await decrypt_dict(server.env_vars) or {}
    server.args = await decrypt_dict(server.args) or {}
    server.registry_credentials = await decrypt_dict(server.registry_credentials) or {}
    return server


@router.delete("/mcp/{server_id}")
async def delete_mcp_server_endpoint(server_id: UUID, db: AsyncSession = Depends(get_db)):
    deleted = await delete_mcp_server(db, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"detail": "Server deleted"}


@router.patch("/mcp/{server_id}/toggle", response_model=MCPServerResponse)
async def toggle_mcp_server_endpoint(server_id: UUID, db: AsyncSession = Depends(get_db)):
    from app.encryption import decrypt_dict
    server = await toggle_mcp_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    server.env_vars = await decrypt_dict(server.env_vars) or {}
    server.args = await decrypt_dict(server.args) or {}
    server.registry_credentials = await decrypt_dict(server.registry_credentials) or {}
    return server


@router.patch("/mcp/{server_id}", response_model=MCPServerResponse)
async def update_mcp_server_endpoint(
    server_id: UUID,
    server_data: MCPServerCreate,
    db: AsyncSession = Depends(get_db)
):
    from app.encryption import decrypt_dict
    server = await update_mcp_server(
        db, 
        server_id, 
        name=server_data.name, 
        image=server_data.image, 
        env_vars=server_data.env_vars,
        args=server_data.args,
        registry_credentials=server_data.registry_credentials,
    )
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    await db.commit()
    # Return decrypted values so the frontend can display them
    server.env_vars = await decrypt_dict(server.env_vars) or {}
    server.args = await decrypt_dict(server.args) or {}
    server.registry_credentials = await decrypt_dict(server.registry_credentials) or {}
    return server


@router.post("/mcp/{server_id}/test", response_model=MCPTestResponse)
async def test_mcp_server_endpoint(server_id: UUID, db: AsyncSession = Depends(get_db)):
    from app.models.models import MCPServer
    from app.encryption import decrypt_dict
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    from app.mcp_helper import get_mcp_server_params
    import json

    result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    decrypted_env = await decrypt_dict(server.env_vars) or {}
    decrypted_args = await decrypt_dict(server.args) or {}
    decrypted_registry_credentials = await decrypt_dict(server.registry_credentials) or {}
    params = get_mcp_server_params(server.image, decrypted_env, decrypted_args, decrypted_registry_credentials)

    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                # Cache discovered tools for instant retrieval
                server.cached_tools = [
                    {"name": t.name, "description": t.description or ""}
                    for t in tools_result.tools
                ]
                await db.flush()
                return MCPTestResponse(
                    success=True, tools=[t.name for t in tools_result.tools]
                )
    except Exception as e:
        return MCPTestResponse(success=False, tools=[], error=str(e))


@router.get("/mcp/tool-overrides", response_model=ToolOverridesResponse)
async def get_global_tool_overrides(db: AsyncSession = Depends(get_db)):
    """Get all available MCP servers and tools without any thread-specific overrides."""
    from app.models.models import MCPServer as MCPServerModel

    # Get all globally active servers
    result = await db.execute(
        select(MCPServerModel).where(MCPServerModel.is_active == True)
    )
    active_servers = list(result.scalars().all())

    servers = []
    for server in active_servers:
        servers.append(AvailableServer(
            id=str(server.id),
            name=server.name,
            tools=_available_tools_from_cache(server.cached_tools),
        ))

    return ToolOverridesResponse(servers=servers, overrides=[])


# ── Thread Tool Overrides ─────────────────────────────────────────────


@router.get("/threads/{thread_id}/tool-overrides")
async def get_tool_overrides(thread_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get available MCP servers and per-thread overrides.

    Returns servers with cached tool lists (populated by test or first chat).
    Does NOT spin up MCP containers.
    """
    from app.models.models import MCPServer as MCPServerModel

    # Get all globally active servers
    result = await db.execute(
        select(MCPServerModel).where(MCPServerModel.is_active == True)
    )
    active_servers = list(result.scalars().all())

    servers = []
    for server in active_servers:
        servers.append(AvailableServer(
            id=str(server.id),
            name=server.name,
            tools=_available_tools_from_cache(server.cached_tools),
        ))

    # Get existing overrides for this thread
    overrides = await get_thread_tool_overrides(db, thread_id)
    override_items = [
        ToolOverrideItem(
            server_id=str(o.server_id),
            tool_name=o.tool_name,
            enabled=o.enabled,
        )
        for o in overrides
    ]

    return ToolOverridesResponse(servers=servers, overrides=override_items)


@router.put("/threads/{thread_id}/tool-overrides")
async def put_tool_overrides(
    thread_id: UUID,
    request: ToolOverrideRequest,
    db: AsyncSession = Depends(get_db),
):
    """Set per-thread tool overrides (replaces all existing overrides)."""
    overrides = [
        {
            "server_id": UUID(o.server_id),
            "tool_name": o.tool_name,
            "enabled": o.enabled,
        }
        for o in request.overrides
    ]
    await set_thread_tool_overrides(db, thread_id, overrides)
    await db.commit()
    return {"detail": "Overrides saved"}


# ── Thread Skill Overrides ────────────────────────────────────────────


@router.get("/threads/{thread_id}/skill-overrides", response_model=SkillOverridesResponse)
async def get_skill_overrides(thread_id: UUID, db: AsyncSession = Depends(get_db)):
    overrides = await get_thread_skill_overrides(db, thread_id)
    return SkillOverridesResponse(
        skills=await get_skills(db),
        overrides=[
            SkillOverrideItem(skill_id=str(o.skill_id), enabled=o.enabled)
            for o in overrides
        ],
    )


@router.put("/threads/{thread_id}/skill-overrides")
async def put_skill_overrides(
    thread_id: UUID,
    request: SkillOverrideRequest,
    db: AsyncSession = Depends(get_db),
):
    overrides = [
        {"skill_id": UUID(o.skill_id), "enabled": o.enabled}
        for o in request.overrides
    ]
    await set_thread_skill_overrides(db, thread_id, overrides)
    await db.commit()
    return {"detail": "Skill overrides saved"}
