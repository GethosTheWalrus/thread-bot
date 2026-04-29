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
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.config import get_settings, get_llm_config, get_redis_url, update_settings
from temporalio.client import Client as TemporalClient
from app.workflows.thread_workflow import RunThreadWorkflow

router = APIRouter(prefix="/api", tags=["chatbot"])


def get_temporal_client():
    """Get Temporal client from app state."""
    return getattr(router, "_temporal_client", None)


def set_temporal_client(client: TemporalClient):
    router._temporal_client = client


def _build_message_response(m) -> MessageResponse:
    return MessageResponse(
        id=m.id,
        thread_id=m.thread_id,
        role=m.role,
        content=m.content,
        created_at=m.created_at,
        metadata=m.metadata_,
    )


def _build_thread_response(thread, messages=None, is_generating=False) -> ThreadResponse:
    msgs = messages or []
    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        parent_id=thread.parent_id,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        messages=[_build_message_response(m) for m in msgs],
        is_generating=is_generating,
    )


@router.post("/threads", response_model=ThreadResponse)
async def create_thread_endpoint(
    request: ThreadCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    thread = await create_thread(db, request.title, request.parent_id)
    return _build_thread_response(thread)


@router.post("/chat")
async def chat_endpoint(
    request: ChatRequest,
    fastapi_request: Request,
    db: AsyncSession = Depends(get_db),
):
    from app.database import AsyncSessionLocal

    temporal_client = get_temporal_client()
    if not temporal_client:
        raise HTTPException(status_code=503, detail="Temporal client not available")

    settings = get_settings()

    # LLM config comes entirely from server-side settings (env + DB overrides)
    llm_config = get_llm_config().copy()

    # Create thread and user message in a committed session so workflow can see them
    async with AsyncSessionLocal() as setup_db:
        if request.thread_id:
            # Continue existing thread
            thread = await get_thread(setup_db, UUID(request.thread_id))
            if not thread:
                raise HTTPException(status_code=404, detail="Thread not found")
            thread_id = thread.id
        elif request.parent_id:
            # Branch from parent
            thread = await create_thread(setup_db, "Reply", parent_id=request.parent_id)
            thread_id = thread.id
        else:
            # New root thread
            thread = await create_thread(setup_db, "New Thread", parent_id=None)
            thread_id = thread.id

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

    import asyncio
    import uuid as uuid_mod
    from fastapi.responses import StreamingResponse
    from temporalio.client import WorkflowFailureError

    run_id = f"thread-{thread_id}-{uuid_mod.uuid4().hex[:8]}"
    channel = f"stream:{run_id}"

    # Pass redis_url so the worker activity can publish directly to Redis
    redis_url = get_redis_url()
    llm_config["redis_url"] = redis_url
    llm_config["stream_channel"] = channel

    # Subscribe to Redis BEFORE starting the workflow to avoid race condition.
    # Redis pub/sub doesn't buffer — if the worker publishes before we subscribe,
    # those messages (including [DONE]) are lost and the stream hangs forever.
    import redis.asyncio as aioredis

    r = aioredis.from_url(redis_url)
    pubsub = r.pubsub()
    await pubsub.subscribe(channel)

    # Mark this thread as actively generating so reconnect works after page refresh
    await r.set(f"generating:{thread_id}", channel, ex=600)

    try:
        await temporal_client.start_workflow(
            RunThreadWorkflow.run,
            {"thread_id": str(thread_id), "message": request.content, "llm_config": llm_config},
            id=run_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        await r.close()
        raise HTTPException(status_code=502, detail=f"Failed to start workflow: {str(e)}")

    async def stream_generator():
        try:
            # Yield the thread_id as the first chunk so the frontend knows the new thread ID
            yield f"THREAD_ID:{thread_id}\n\n".encode("utf-8")

            while True:
                try:
                    msg = await asyncio.wait_for(
                        pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                        timeout=5.0,
                    )
                    if msg is None:
                        # No message yet — send heartbeat to keep connection alive
                        yield b"\x00"
                        continue

                    data = msg["data"]
                    if isinstance(data, str):
                        data = data.encode("utf-8")

                    if data == b"[DONE]":
                        break
                    if data.startswith(b"[ERROR]"):
                        yield data
                        break
                    yield data
                except asyncio.TimeoutError:
                    yield b"\x00"
                except Exception as e:
                    yield f"[ERROR] Stream interrupted: {str(e)}".encode("utf-8")
                    break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            await r.close()

    return StreamingResponse(
        stream_generator(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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

    # Check if this thread is actively generating
    import redis.asyncio as aioredis
    redis_url = get_redis_url()
    r = aioredis.from_url(redis_url)
    try:
        channel = await r.get(f"generating:{thread_id}")
        is_generating = channel is not None
    finally:
        await r.close()

    return _build_thread_response(thread, thread.messages, is_generating=is_generating)


@router.get("/threads/{thread_id}/stream")
async def reconnect_stream_endpoint(
    thread_id: UUID,
):
    """Reconnect to an in-progress generation stream.
    
    Uses the Redis event buffer (list) to replay all events from the beginning,
    then polls for new events until [DONE]. This allows the frontend to resume
    streaming after a page refresh without losing any events.
    
    Returns 204 if the thread is not currently generating.
    """
    import asyncio
    import redis.asyncio as aioredis
    from fastapi.responses import StreamingResponse, Response

    redis_url = get_redis_url()
    r = aioredis.from_url(redis_url)

    try:
        channel = await r.get(f"generating:{thread_id}")
    except Exception:
        await r.close()
        return Response(status_code=204)

    if not channel:
        await r.close()
        return Response(status_code=204)

    # Decode channel name (Redis returns bytes)
    if isinstance(channel, bytes):
        channel = channel.decode("utf-8")

    events_key = f"events:{channel}"

    async def stream_generator():
        try:
            cursor = 0
            while True:
                # Get all events from cursor position onward
                events = await r.lrange(events_key, cursor, -1)
                if events:
                    for event_data in events:
                        if event_data == b"[DONE]":
                            return
                        if event_data.startswith(b"[ERROR]"):
                            yield event_data
                            return
                        yield event_data
                    cursor += len(events)
                else:
                    # No new events — send heartbeat and wait
                    yield b"\x00"
                    await asyncio.sleep(0.2)
        finally:
            await r.close()

    return StreamingResponse(
        stream_generator(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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
        "llm_api_url": config["api_url"],
        "llm_api_key": config["api_key"],
        "llm_temperature": config["temperature"],
        "llm_max_tokens": config["max_tokens"],
        "llm_stream_timeout": config["stream_timeout"],
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
        "llm_temperature": "llm_temperature",
        "llm_max_tokens": "llm_max_tokens",
        "llm_stream_timeout": "llm_stream_timeout",
        "llm_context_window": "llm_context_window",
        "llm_compaction_threshold": "llm_compaction_threshold",
        "llm_preserve_recent": "llm_preserve_recent",
    }
    updates = {valid_keys[k]: v for k, v in request.items() if k in valid_keys}
    if updates:
        update_settings(**updates)
        # Persist to DB so values survive restarts
        await upsert_settings(db, {k: str(v) for k, v in updates.items()})

    config = get_llm_config()
    return {
        "llm_model": config["model"],
        "llm_api_url": config["api_url"],
        "llm_temperature": config["temperature"],
        "llm_max_tokens": config["max_tokens"],
        "llm_stream_timeout": config["stream_timeout"],
        "llm_context_window": config["context_window"],
        "llm_compaction_threshold": config["compaction_threshold"],
        "llm_preserve_recent": config["preserve_recent"],
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
                return MCPTestResponse(
                    success=True, tools=[t.name for t in tools_result.tools]
                )
    except Exception as e:
        return MCPTestResponse(success=False, tools=[], error=str(e))


# ── Thread Tool Overrides ─────────────────────────────────────────────


@router.get("/threads/{thread_id}/tool-overrides")
async def get_tool_overrides(thread_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get available MCP servers/tools and per-thread overrides."""
    from app.encryption import decrypt_dict
    from app.mcp_helper import get_mcp_server_params
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    # Get all globally active servers
    result = await db.execute(
        select(MCPServer).where(MCPServer.is_active == True)
    )
    active_servers = list(result.scalars().all())

    # Discover tools from each server
    servers = []
    for server in active_servers:
        tools = []
        try:
            decrypted_env = await decrypt_dict(server.env_vars) or {}
            decrypted_args = await decrypt_dict(server.args) or {}
            params = get_mcp_server_params(server.image, decrypted_env, decrypted_args)
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    tools = [
                        AvailableTool(name=t.name, description=t.description or "")
                        for t in tools_result.tools
                    ]
        except Exception as e:
            print(f"ERROR: Failed to list tools for {server.name}: {e}", flush=True)

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
