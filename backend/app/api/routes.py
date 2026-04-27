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
)
from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from app.config import get_settings, get_llm_config, update_settings
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


def _build_thread_response(thread, messages=None) -> ThreadResponse:
    msgs = messages or []
    return ThreadResponse(
        id=thread.id,
        title=thread.title,
        parent_id=thread.parent_id,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        messages=[_build_message_response(m) for m in msgs],
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

    # Construct full LLM config to pass as workflow input
    llm_config = get_llm_config().copy()
    if request.llm_api_url:
        llm_config["api_url"] = request.llm_api_url
    if request.llm_api_key:
        llm_config["api_key"] = request.llm_api_key
    if request.llm_model:
        llm_config["model"] = request.llm_model

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
        await setup_db.commit()

    import asyncio
    import uuid as uuid_mod
    from fastapi.responses import StreamingResponse
    from temporalio.client import WorkflowFailureError

    run_id = f"thread-{thread_id}-{uuid_mod.uuid4().hex[:8]}"
    llm_config["stream_url"] = f"http://backend:8000/api/internal/stream/{run_id}"

    # We must ensure the global queue exists
    if not hasattr(fastapi_request.app.state, "stream_queues"):
        fastapi_request.app.state.stream_queues = {}
    
    fastapi_request.app.state.stream_queues[run_id] = asyncio.Queue()

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
        if run_id in fastapi_request.app.state.stream_queues:
            del fastapi_request.app.state.stream_queues[run_id]
        raise HTTPException(status_code=502, detail=f"Failed to start workflow: {str(e)}")

    async def stream_generator():
        try:
            # Yield the thread_id as the first chunk so the frontend knows the new thread ID
            yield f"THREAD_ID:{thread_id}\n\n".encode("utf-8")
            
            while True:
                try:
                    # Wait for a chunk with a timeout to allow sending heartbeats
                    chunk = await asyncio.wait_for(
                        fastapi_request.app.state.stream_queues[run_id].get(),
                        timeout=5.0
                    )
                    
                    if chunk == b"[DONE]":
                        break
                    if chunk.startswith(b"[ERROR]"):
                        yield chunk
                        break
                    yield chunk
                except asyncio.TimeoutError:
                    # Send a null heartbeat to keep the connection alive
                    yield b"\x00"
                except Exception as e:
                    yield f"[ERROR] Stream interrupted: {str(e)}".encode("utf-8")
                    break
        finally:
            if run_id in fastapi_request.app.state.stream_queues:
                del fastapi_request.app.state.stream_queues[run_id]

    return StreamingResponse(
        stream_generator(), 
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
            "Connection": "keep-alive",
        }
    )

@router.post("/internal/stream/{run_id}")
async def internal_stream(run_id: str, request: Request):
    if hasattr(request.app.state, "stream_queues") and run_id in request.app.state.stream_queues:
        body = await request.body()
        await request.app.state.stream_queues[run_id].put(body)
    return {"ok": True}


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

    return _build_thread_response(thread, thread.messages)


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
async def update_settings_endpoint(request: dict):
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
    return await get_mcp_servers(db)


@router.post("/mcp", response_model=MCPServerResponse)
async def create_mcp_server_endpoint(request: MCPServerCreate, db: AsyncSession = Depends(get_db)):
    return await create_mcp_server(db, request.name, request.image, request.env_vars)


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
    server = await update_mcp_server(
        db, 
        server_id, 
        name=server_data.name, 
        image=server_data.image, 
        env_vars=server_data.env_vars
    )
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    await db.commit()
    return server


@router.post("/mcp/{server_id}/test", response_model=MCPTestResponse)
async def test_mcp_server_endpoint(server_id: UUID, db: AsyncSession = Depends(get_db)):
    from app.models.models import MCPServer
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    import json

    result = await db.execute(select(MCPServer).where(MCPServer.id == server_id))
    server = result.scalar_one_or_none()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    params = StdioServerParameters(
        command="/usr/local/bin/docker",
        args=[
            "run",
            "-i",
            "--rm",
            "--add-host=host.docker.internal:host-gateway",
            *[item for k, v in server.env_vars.items() for item in ["-e", f"{k}={v}"]],
            server.image,
        ],
        env=None,
    )

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
