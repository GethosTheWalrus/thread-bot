import aiohttp
from temporalio.activity import defn


@defn
async def call_llm(args: dict) -> dict:
    """Call the OpenAI-compatible LLM API with MCP tool support.
    
    Returns a dict with:
        content: str  — final assistant response text
        intermediate_messages: list[dict]  — tool_call / tool_result rows to persist
    """
    messages = args.get("messages", [])
    config = args.get("llm_config", {})
    stream_url = config.get("stream_url")

    # ── MCP Tool Setup ────────────────────────────────────────────────
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.models import MCPServer
    import json
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    active_servers = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(MCPServer).where(MCPServer.is_active == True))
        active_servers = list(result.scalars().all())

    print(f"Discovered {len(active_servers)} active MCP servers", flush=True)

    # Map of tool_name -> server_info
    mcp_tools_map = {}
    openai_tools = []

    for server in active_servers:
        print(f"Loading tools from MCP server: {server.name} ({server.image})", flush=True)
        try:
            params = StdioServerParameters(
                command="/usr/local/bin/docker",
                args=[
                    "run", "-i", "--rm",
                    "--add-host=host.docker.internal:host-gateway",
                    *[item for k, v in server.env_vars.items() for item in ["-e", f"{k}={v}"]],
                    server.image
                ],
                env=None
            )

            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    print(f"Found {len(tools_result.tools)} tools on server {server.name}", flush=True)
                    for tool in tools_result.tools:
                        full_name = f"{server.name}_{tool.name}"
                        mcp_tools_map[full_name] = {
                            "server_params": params,
                            "original_name": tool.name,
                            "server_name": server.name
                        }
                        openai_tools.append({
                            "type": "function",
                            "function": {
                                "name": full_name,
                                "description": tool.description or "",
                                "parameters": tool.inputSchema
                            }
                        })
        except Exception as e:
            print(f"ERROR: Failed to load MCP server {server.name}: {e}", flush=True)

    print(f"Total tools available to LLM: {len(openai_tools)}", flush=True)

    # ── LLM Interaction Loop ──────────────────────────────────────────
    api_url = config["api_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }

    current_messages = list(messages)
    full_response_content = ""
    # Intermediate messages to be persisted to the DB
    intermediate_messages = []

    async with aiohttp.ClientSession() as session:
        while True:
            payload = {
                "model": config["model"],
                "messages": current_messages,
                "temperature": config.get("temperature", 0.7),
                "max_tokens": config.get("max_tokens", 2048),
            }
            if openai_tools:
                payload["tools"] = openai_tools

            timeout = aiohttp.ClientTimeout(total=config.get("stream_timeout", 600))

            async with session.post(api_url, headers=headers, json=payload, timeout=timeout) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    if stream_url:
                        await session.post(stream_url, data=f"[ERROR] {resp.status}: {error_text}".encode('utf-8'))
                    raise RuntimeError(f"LLM API error {resp.status}: {error_text}")

                data = await resp.json()
                choice = data["choices"][0]
                message = choice["message"]

                # Handle Tool Calls
                if message.get("tool_calls"):
                    current_messages.append(message)

                    # Build a human-readable description of what's being called
                    call_descriptions = []
                    for tc in message["tool_calls"]:
                        info = mcp_tools_map.get(tc["function"]["name"], {})
                        call_descriptions.append(
                            f"{info.get('server_name', '?')}:{info.get('original_name', tc['function']['name'])}"
                        )

                    # Record the tool_call turn for persistence
                    intermediate_messages.append({
                        "role": "tool_call",
                        "content": "Calling " + ", ".join(call_descriptions),
                        "metadata": {"tool_calls": message["tool_calls"]}
                    })

                    for tool_call in message["tool_calls"]:
                        tool_name = tool_call["function"]["name"]
                        tool_args = json.loads(tool_call["function"]["arguments"])

                        if tool_name in mcp_tools_map:
                            info = mcp_tools_map[tool_name]
                            if stream_url:
                                await session.post(
                                    stream_url,
                                    data=f"🔧 Executing {info['server_name']}:{info['original_name']}...\n".encode('utf-8')
                                )

                            try:
                                async with stdio_client(StdioServerParameters(
                                    command="/usr/local/bin/docker",
                                    args=info["server_params"].args,
                                    env=info["server_params"].env
                                )) as (read, write):
                                    async with ClientSession(read, write) as mcp_session:
                                        await mcp_session.initialize()
                                        result = await mcp_session.call_tool(info["original_name"], tool_args)
                                        result_text = "\n".join([c.text for c in result.content if hasattr(c, 'text')])

                                        current_messages.append({
                                            "role": "tool",
                                            "tool_call_id": tool_call["id"],
                                            "name": tool_name,
                                            "content": result_text
                                        })
                                        # Record tool result for persistence
                                        intermediate_messages.append({
                                            "role": "tool_result",
                                            "content": result_text,
                                            "metadata": {
                                                "tool_call_id": tool_call["id"],
                                                "tool_name": tool_name
                                            }
                                        })
                            except Exception as e:
                                error_content = f"Error executing tool: {str(e)}"
                                current_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call["id"],
                                    "name": tool_name,
                                    "content": error_content
                                })
                                intermediate_messages.append({
                                    "role": "tool_result",
                                    "content": error_content,
                                    "metadata": {
                                        "tool_call_id": tool_call["id"],
                                        "tool_name": tool_name
                                    }
                                })
                        else:
                            not_found = "Tool not found"
                            current_messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "name": tool_name,
                                "content": not_found
                            })
                            intermediate_messages.append({
                                "role": "tool_result",
                                "content": not_found,
                                "metadata": {
                                    "tool_call_id": tool_call["id"],
                                    "tool_name": tool_name
                                }
                            })
                    continue  # Loop back to LLM with tool results

                # Final response
                full_response_content = message.get("content", "")
                if stream_url:
                    await session.post(stream_url, data=full_response_content.encode('utf-8'))
                    await session.post(stream_url, data=b"[DONE]")
                break

    return {
        "content": full_response_content,
        "intermediate_messages": intermediate_messages,
    }


@defn
async def save_message(args: dict) -> None:
    """Save a message to the database."""
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.database.crud import add_message

    thread_id = args["thread_id"]
    role = args["role"]
    content = args["content"]
    metadata = args.get("metadata")
    async with AsyncSessionLocal() as db:
        await add_message(db, UUID(thread_id), role, content, metadata=metadata)
        await db.commit()


@defn
async def get_messages(thread_id: str) -> list[dict]:
    """Get chat history for a thread, reconstructing OpenAI-compatible message format."""
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.database.crud import get_thread_messages

    async with AsyncSessionLocal() as db:
        messages = await get_thread_messages(db, UUID(thread_id))

    result = []
    for m in messages:
        if m.role == "tool_call":
            # Reconstruct as assistant message with tool_calls for the LLM
            meta = m.metadata_ or {}
            result.append({
                "role": "assistant",
                "content": None,
                "tool_calls": meta.get("tool_calls", [])
            })
        elif m.role == "tool_result":
            meta = m.metadata_ or {}
            result.append({
                "role": "tool",
                "tool_call_id": meta.get("tool_call_id", ""),
                "name": meta.get("tool_name", ""),
                "content": m.content
            })
        elif m.role == "system":
            # Compaction summaries — pass through as system messages
            result.append({"role": "system", "content": m.content})
        else:
            result.append({"role": m.role, "content": m.content})

    return result


@defn
async def update_title(args: dict) -> None:
    """Update thread title."""
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.database.crud import update_thread_title

    thread_id = args["thread_id"]
    title = args["title"]
    async with AsyncSessionLocal() as db:
        await update_thread_title(db, UUID(thread_id), title)
        await db.commit()


@defn
async def compact_history(args: dict) -> dict:
    """Compact old messages in a thread into a summary.

    Returns:
        compacted: bool
        summary: str | None
        messages: list[dict]  — new message list to send to the LLM
        compacted_count: int
    """
    import aiohttp

    messages = args["messages"]
    config = args["llm_config"]
    context_window = args.get("context_window", 8192)
    threshold = args.get("compaction_threshold", 0.75)
    preserve_recent = args.get("preserve_recent", 10)

    # Estimate tokens using character count heuristic (chars / 4)
    total_chars = sum(len(m.get("content", "") or "") for m in messages)
    estimated_tokens = total_chars / 4
    token_limit = context_window * threshold

    print(
        f"Compaction check: ~{int(estimated_tokens)} tokens estimated, "
        f"limit={int(token_limit)} (window={context_window} × threshold={threshold})",
        flush=True
    )

    if estimated_tokens <= token_limit:
        return {"compacted": False, "summary": None, "messages": messages, "compacted_count": 0}

    if len(messages) <= preserve_recent:
        print("Compaction skipped: not enough messages to compact", flush=True)
        return {"compacted": False, "summary": None, "messages": messages, "compacted_count": 0}

    to_compact = messages[:-preserve_recent]
    to_keep = messages[-preserve_recent:]

    print(f"Compacting {len(to_compact)} messages, keeping {len(to_keep)}", flush=True)

    # Build readable conversation text for the summariser (skip null-content tool_call turns)
    conversation_lines = []
    for m in to_compact:
        content = m.get("content")
        role = m.get("role", "unknown")
        if content:
            conversation_lines.append(f"{role}: {content}")
        elif m.get("tool_calls"):
            names = [tc.get("function", {}).get("name", "?") for tc in m["tool_calls"]]
            conversation_lines.append(f"assistant (tool call): {', '.join(names)}")

    conversation_text = "\n".join(conversation_lines)

    summary_prompt = [
        {
            "role": "system",
            "content": (
                "You are a conversation summarizer. Summarize the following conversation history "
                "into a concise but comprehensive summary. Preserve all important facts, decisions, "
                "tool results, code snippets, and context that would be needed to continue the "
                "conversation naturally. Be thorough but concise. Output ONLY the summary, no preamble."
            )
        },
        {
            "role": "user",
            "content": f"Summarize this conversation:\n\n{conversation_text}"
        }
    ]

    api_url = config["api_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }
    payload = {
        "model": config["model"],
        "messages": summary_prompt,
        "temperature": 0.3,
        "max_tokens": 1024,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    print(f"Compaction LLM call failed ({resp.status}): {error_text}", flush=True)
                    return {"compacted": False, "summary": None, "messages": messages, "compacted_count": 0}

                data = await resp.json()
                summary = data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Compaction failed with exception: {e}", flush=True)
        return {"compacted": False, "summary": None, "messages": messages, "compacted_count": 0}

    print(f"Compaction summary generated ({len(summary)} chars)", flush=True)

    summary_message = {
        "role": "system",
        "content": (
            "[CONVERSATION SUMMARY]\n"
            f"{summary}\n"
            "[END SUMMARY]\n\n"
            "The above is a summary of the earlier conversation. Continue naturally from here."
        ),
    }

    new_messages = [summary_message] + to_keep

    return {
        "compacted": True,
        "summary": summary,
        "messages": new_messages,
        "compacted_count": len(to_compact),
    }


@defn
async def delete_messages_before(args: dict) -> None:
    """Delete older messages from a thread, keeping the most recent N plus system messages."""
    from uuid import UUID
    from sqlalchemy import select, delete as sql_delete
    from app.database import AsyncSessionLocal
    from app.models.models import Message

    thread_id = UUID(args["thread_id"])
    keep_recent = args.get("keep_recent", 10)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Message.id, Message.role)
            .where(Message.thread_id == thread_id)
            .order_by(Message.created_at)
        )
        all_msgs = result.all()

        # Always keep system/compaction messages
        to_keep_ids = set()
        non_system = []
        for mid, role in all_msgs:
            if role == "system":
                to_keep_ids.add(mid)
            else:
                non_system.append(mid)

        # Keep the last `keep_recent` non-system messages
        for mid in non_system[-keep_recent:]:
            to_keep_ids.add(mid)

        to_delete = [mid for mid, _ in all_msgs if mid not in to_keep_ids]
        if to_delete:
            print(f"Deleting {len(to_delete)} compacted messages from thread {thread_id}", flush=True)
            await db.execute(
                sql_delete(Message).where(Message.id.in_(to_delete))
            )
            await db.commit()
