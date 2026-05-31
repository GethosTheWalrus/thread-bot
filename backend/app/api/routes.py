from app.database import get_db
from app.database.crud import (
    create_thread,
    get_thread,
    get_thread_with_messages,
    get_root_threads,
    get_child_threads,
    add_message,
    update_thread_title,
    delete_thread,
    create_mcp_server,
    get_mcp_servers,
    delete_mcp_server,
    toggle_mcp_server,
    update_mcp_server,
    upsert_settings,
    get_thread_tool_overrides,
    set_thread_tool_overrides,
)
from app.models.models import Thread, Message
from app.models.schemas import (
    ThreadCreateRequest,
    ChatRequest,
    ThreadResponse,
    MessageResponse,
    ThreadListItem,
    ThreadListResponse,
    RenameRequest,
    MCPServerCreate,
    MCPServerResponse,
    MCPTestResponse,
    ToolOverrideRequest,
    ToolOverridesResponse,
    ToolOverrideItem,
    AvailableServer,
    AvailableTool,
)
from fastapi import APIRouter, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.config import get_settings, get_llm_config, update_settings
from temporalio.client import Client as TemporalClient
from temporalio.contrib.workflow_streams import WorkflowStreamClient
from app.workflows.thread_workflow import RunThreadWorkflow

router = APIRouter(prefix="/api", tags=["chatbot"])


def get_temporal_client():
    """Get Temporal client from app state."""
    return getattr(router, "_temporal_client", None)


def set_temporal_client(client: TemporalClient):
    router._temporal_client = client


async def _active_thread_workflow_id(client: TemporalClient, thread_id: UUID) -> str | None:
    query = f'ExecutionStatus="Running" AND WorkflowId STARTS_WITH "thread-{thread_id}-"'
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
) -> None:
    stream = WorkflowStreamClient.create(temporal_client, workflow_id)
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
        await handle.result()
        await websocket.send_json({"type": "done"})
    except Exception as e:
        await websocket.send_json({"type": "error", "content": str(e)})


async def _relay_workflow_until_complete(
    websocket: WebSocket,
    temporal_client: TemporalClient,
    workflow_id: str,
    *,
    from_offset: int = 0,
) -> None:
    import asyncio

    relay_task = asyncio.create_task(
        _relay_workflow_stream(websocket, temporal_client, workflow_id, from_offset=from_offset)
    )
    completion_task = asyncio.create_task(
        _send_workflow_terminal_event(websocket, temporal_client, workflow_id)
    )
    done, pending = await asyncio.wait(
        {relay_task, completion_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    for task in done:
        task.result()


def _build_message_response(m) -> MessageResponse:
    return MessageResponse(
        id=m.id,
        thread_id=m.thread_id,
        role=m.role,
        content=m.content,
        created_at=m.created_at,
        metadata=m.metadata_,
    )


def _estimate_context_tokens(messages) -> int:
    total_chars = 0
    for message in messages or []:
        role = getattr(message, "role", None)
        if role == "thinking":
            continue
        total_chars += len(getattr(message, "content", None) or "")
    return int(total_chars / 4)


def _build_thread_response(thread, messages=None, is_generating=False) -> ThreadResponse:
    msgs = messages or []
    config = get_llm_config()
    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        parent_id=thread.parent_id,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        messages=[_build_message_response(m) for m in msgs],
        is_generating=is_generating,
        estimated_tokens=_estimate_context_tokens(msgs),
        context_window=config.get("context_window", 8192),
    )


@router.post("/threads", response_model=ThreadResponse)
async def create_thread_endpoint(
    request: ThreadCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    thread = await create_thread(db, request.title, request.parent_id)
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
        await db.commit()
    return _build_thread_response(thread)


@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    fastapi_request: Request,
    db: AsyncSession = Depends(get_db),
):
    raise HTTPException(status_code=426, detail="Chat streaming now uses /api/chat/ws WebSocket")


@router.websocket("/chat/ws")
async def chat_websocket(websocket: WebSocket):
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

    from app.database import AsyncSessionLocal

    settings = get_settings()
    llm_config = get_llm_config().copy()

    async with AsyncSessionLocal() as setup_db:
        if request.thread_id:
            thread = await get_thread(setup_db, UUID(request.thread_id))
            if not thread:
                await websocket.send_json({"type": "error", "content": "Thread not found"})
                await websocket.close(code=1008)
                return
            thread_id = thread.id
        elif request.parent_id:
            thread = await create_thread(setup_db, "Reply", parent_id=request.parent_id)
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
        else:
            thread = await create_thread(setup_db, "New Thread", parent_id=None)
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

        await add_message(setup_db, thread_id, "user", request.content)

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

        await setup_db.commit()

    import uuid as uuid_mod

    run_id = f"thread-{thread_id}-{uuid_mod.uuid4().hex[:8]}"

    try:
        await temporal_client.start_workflow(
            RunThreadWorkflow.run,
            {"thread_id": str(thread_id), "message": request.content, "llm_config": llm_config},
            id=run_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
        await websocket.send_json({"type": "thread", "thread_id": str(thread_id), "workflow_id": run_id})
    except Exception as e:
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
        await _relay_workflow_until_complete(websocket, temporal_client, run_id)
    except WebSocketDisconnect:
        pass
    finally:
        control_task.cancel()


@router.get("/threads", response_model=ThreadListResponse)
async def list_threads_endpoint(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    threads = await get_root_threads(db, limit=limit, offset=offset)
    thread_items = []
    for t in threads:
        msg_count_result = await db.execute(
            select(func.count(Message.id)).where(Message.thread_id == t.id)
        )
        msg_count = msg_count_result.scalar_one()
        thread_items.append(ThreadListItem(
            id=t.id,
            title=t.title,
            parent_id=t.parent_id,
            created_at=t.created_at,
            updated_at=t.updated_at,
            message_count=msg_count,
        ))
    return ThreadListResponse(threads=thread_items)


@router.get("/threads/{thread_id}", response_model=ThreadResponse)
async def get_thread_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    thread = await get_thread_with_messages(db, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    is_generating = await _thread_is_generating(thread_id)

    return _build_thread_response(thread, thread.messages, is_generating=is_generating)


@router.websocket("/threads/{thread_id}/ws")
async def reconnect_thread_websocket(websocket: WebSocket, thread_id: UUID, offset: int = 0):
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
        await _relay_workflow_until_complete(websocket, temporal_client, workflow_id, from_offset=offset)
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
    for t in replies:
        cnt = await db.execute(select(func.count(Message.id)).where(Message.thread_id == t.id))
        items.append(ThreadListItem(
            id=t.id,
            title=t.title,
            parent_id=t.parent_id,
            created_at=t.created_at,
            updated_at=t.updated_at,
            message_count=cnt.scalar_one(),
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

    return _build_thread_response(thread, messages)


@router.delete("/threads/{thread_id}")
async def delete_thread_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_thread(db, thread_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Thread not found")
    return {"detail": "Thread deleted"}


@router.delete("/threads")
async def delete_all_threads_endpoint(
    db: AsyncSession = Depends(get_db),
):
    # Delete all threads (cascades to messages)
    await db.execute(select(Thread))
    result = await db.execute(select(Thread))
    threads = result.scalars().all()
    for t in threads:
        await db.delete(t)
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
        "llm_api_key": config["api_key"],
        "llm_temperature": config["temperature"],
        "llm_max_tokens": config["max_tokens"],
        "llm_stream_timeout": config["stream_timeout"],
        "llm_max_iterations": config["max_iterations"],
        "llm_context_window": config["context_window"],
        "llm_compaction_threshold": config["compaction_threshold"],
        "llm_preserve_recent": config["preserve_recent"],
        "has_api_key": bool(config["api_key"]),
    }


@router.patch("/settings")
async def update_settings_endpoint(
    request: dict,
    db: AsyncSession = Depends(get_db),
):
    valid_keys = {
        "llm_api_url": "llm_api_url",
        "llm_api_key": "llm_api_key",
        "llm_model": "llm_model",
        "llm_provider": "llm_provider",
        "llm_temperature": "llm_temperature",
        "llm_max_tokens": "llm_max_tokens",
        "llm_stream_timeout": "llm_stream_timeout",
        "llm_max_iterations": "llm_max_iterations",
        "llm_context_window": "llm_context_window",
        "llm_compaction_threshold": "llm_compaction_threshold",
        "llm_preserve_recent": "llm_preserve_recent",
        "llm_tool_result_max_chars": "llm_tool_result_max_chars",
    }
    updates = {valid_keys[k]: v for k, v in request.items() if k in valid_keys}
    if updates:
        update_settings(**updates)
        # Persist to DB so values survive restarts
        await upsert_settings(db, {k: str(v) for k, v in updates.items()})

    config = get_llm_config()
    return {
        "llm_model": config["model"],
        "llm_provider": config["provider"],
        "llm_api_url": config["api_url"],
        "llm_temperature": config["temperature"],
        "llm_max_tokens": config["max_tokens"],
        "llm_stream_timeout": config["stream_timeout"],
        "llm_max_iterations": config["max_iterations"],
        "llm_context_window": config["context_window"],
        "llm_compaction_threshold": config["compaction_threshold"],
        "llm_preserve_recent": config["preserve_recent"],
        "llm_tool_result_max_chars": config["tool_result_max_chars"],
        "has_api_key": bool(config["api_key"]),
    }


@router.get("/mcp", response_model=list[MCPServerResponse])
async def list_mcp_servers_endpoint(db: AsyncSession = Depends(get_db)):
    from app.encryption import decrypt_dict
    servers = await get_mcp_servers(db)
    result = []
    for s in servers:
        s.env_vars = await decrypt_dict(s.env_vars) or {}
        s.args = await decrypt_dict(s.args) or {}
        result.append(s)
    return result


@router.post("/mcp", response_model=MCPServerResponse)
async def create_mcp_server_endpoint(request: MCPServerCreate, db: AsyncSession = Depends(get_db)):
    from app.encryption import decrypt_dict
    server = await create_mcp_server(db, request.name, request.image, request.env_vars, request.args)
    # Return decrypted values so the frontend can display them
    server.env_vars = await decrypt_dict(server.env_vars) or {}
    server.args = await decrypt_dict(server.args) or {}
    return server


@router.delete("/mcp/{server_id}")
async def delete_mcp_server_endpoint(server_id: UUID, db: AsyncSession = Depends(get_db)):
    deleted = await delete_mcp_server(db, server_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"detail": "Server deleted"}


@router.patch("/mcp/{server_id}/toggle", response_model=MCPServerResponse)
async def toggle_mcp_server_endpoint(server_id: UUID, db: AsyncSession = Depends(get_db)):
    server = await toggle_mcp_server(db, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
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
    )
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    await db.commit()
    # Return decrypted values so the frontend can display them
    server.env_vars = await decrypt_dict(server.env_vars) or {}
    server.args = await decrypt_dict(server.args) or {}
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
    params = get_mcp_server_params(server.image, decrypted_env, decrypted_args)

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
        tools = []
        if server.cached_tools and isinstance(server.cached_tools, list):
            tools = [
                AvailableTool(name=t["name"], description=t.get("description", ""))
                for t in server.cached_tools
            ]
        servers.append(AvailableServer(
            id=str(server.id),
            name=server.name,
            tools=tools,
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
        tools = []
        if server.cached_tools and isinstance(server.cached_tools, list):
            tools = [
                AvailableTool(name=t["name"], description=t.get("description", ""))
                for t in server.cached_tools
            ]
        servers.append(AvailableServer(
            id=str(server.id),
            name=server.name,
            tools=tools,
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
