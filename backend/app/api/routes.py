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
    get_discord_link,
    create_discord_link,
    set_discord_link_active,
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
    DiscordSettingsRequest,
    DiscordSettingsResponse,
    DiscordShareRequest,
    DiscordThreadLinkResponse,
)
from fastapi import APIRouter, HTTPException, Depends, Request, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.config import get_settings, get_llm_config, get_redis_url, update_settings, get_discord_config
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


async def _get_discord_link_for_thread(db: AsyncSession, thread_id: UUID):
    return await get_discord_link(db, thread_id)


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


def _build_thread_response(thread, messages=None, is_generating=False, discord_link=None) -> ThreadResponse:
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
        discord_link=_build_discord_link_response(discord_link),
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

        discord_link = await get_discord_link(setup_db, thread_id)
        workflow_discord_config = _build_workflow_discord_config(get_discord_config(), discord_link)
        if workflow_discord_config:
            llm_config["discord"] = workflow_discord_config

        await setup_db.commit()

    from app.discord_integration import sync_message_to_discord
    discord_message_id = await sync_message_to_discord(
        thread_id,
        "user",
        request.content,
        discord_config=llm_config.get("discord"),
    )
    if discord_message_id and llm_config.get("discord"):
        llm_config["discord"]["reply_to_message_id"] = discord_message_id

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
        discord_link = await _get_discord_link_for_thread(db, t.id)
        thread_items.append(ThreadListItem(
            id=t.id,
            title=t.title,
            parent_id=t.parent_id,
            created_at=t.created_at,
            updated_at=t.updated_at,
            message_count=msg_count,
            is_discord_thread=bool(discord_link and discord_link.is_active),
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

    discord_link = await _get_discord_link_for_thread(db, thread_id)
    return _build_thread_response(thread, thread.messages, is_generating=is_generating, discord_link=discord_link)


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
        discord_link = await _get_discord_link_for_thread(db, t.id)
        items.append(ThreadListItem(
            id=t.id,
            title=t.title,
            parent_id=t.parent_id,
            created_at=t.created_at,
            updated_at=t.updated_at,
            message_count=cnt.scalar_one(),
            is_discord_thread=bool(discord_link and discord_link.is_active),
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

    discord_link = await _get_discord_link_for_thread(db, thread_id)
    return _build_thread_response(thread, messages, discord_link=discord_link)


@router.delete("/threads/{thread_id}")
async def delete_thread_endpoint(
    thread_id: UUID,
    db: AsyncSession = Depends(get_db),
):
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
    return {"detail": "Thread deleted"}


@router.delete("/threads")
async def delete_all_threads_endpoint(
    db: AsyncSession = Depends(get_db),
):
    # Delete all threads (cascades to messages)
    result = await db.execute(select(Thread))
    threads = result.scalars().all()
    from app.discord_integration import delete_discord_thread

    for t in threads:
        discord_link = await get_discord_link(db, t.id)
        if discord_link and discord_link.is_active:
            try:
                await delete_discord_thread(discord_link.discord_thread_id)
            except Exception as exc:
                print(f"[discord] failed to delete Discord thread {discord_link.discord_thread_id}: {exc}", flush=True)
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
        "discord": DiscordSettingsResponse(
            enabled=get_discord_config()["enabled"],
            has_bot_token=bool(get_discord_config()["bot_token"]),
            guild_id=get_discord_config()["guild_id"],
            channel_id=get_discord_config()["channel_id"],
            poll_interval_seconds=get_discord_config()["poll_interval_seconds"],
        ).model_dump(),
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
        "discord_enabled": "discord_enabled",
        "discord_bot_token": "discord_bot_token",
        "discord_guild_id": "discord_guild_id",
        "discord_channel_id": "discord_channel_id",
        "discord_poll_interval_seconds": "discord_poll_interval_seconds",
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


@router.post("/threads/{thread_id}/discord", response_model=DiscordThreadLinkResponse)
async def share_thread_to_discord_endpoint(
    thread_id: UUID,
    request: DiscordShareRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.discord_integration import create_discord_thread, post_existing_thread_to_discord

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
