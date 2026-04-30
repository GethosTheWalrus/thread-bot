from temporalio.activity import defn, heartbeat


# ── Redis publish helper (used by multiple activities) ────────────────
async def _publish(redis_url: str, stream_channel: str, event):
    """Publish a structured JSON event (or raw sentinel) to Redis.

    Events are both PUBLISHed (for the live SSE connection) and RPUSHed
    to an events list (for reconnect after page refresh).
    """
    if not redis_url or not stream_channel:
        return
    import json as _json
    import redis.asyncio as aioredis

    r = aioredis.from_url(redis_url)
    try:
        if isinstance(event, dict):
            data = _json.dumps(event).encode("utf-8")
        elif isinstance(event, str):
            data = event.encode("utf-8")
        else:
            data = event
        events_key = f"events:{stream_channel}"
        await r.publish(stream_channel, data)
        await r.rpush(events_key, data)
        await r.expire(events_key, 600)
    finally:
        await r.close()


# ── Inline DB save helper (used by multiple activities) ───────────────
async def _save_inline(thread_id: str, role: str, content: str, metadata: dict | None = None):
    """Persist a message to the DB immediately."""
    if not thread_id:
        return
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.database.crud import add_message
    async with AsyncSessionLocal() as db:
        await add_message(db, UUID(thread_id), role, content, metadata=metadata)
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════
#  NEW DECOMPOSED ACTIVITIES — agent loop split into discrete steps
# ═══════════════════════════════════════════════════════════════════════

@defn
async def discover_tools(args: dict) -> dict:
    """Discover available MCP tools and apply per-thread overrides.

    Spins up each active MCP server container to list tools, caches the
    discovered tools in the DB, and filters by per-thread overrides.

    Returns:
        mcp_tools_map: dict  — tool_name -> {image, env_vars, args, original_name, server_name}
        openai_tools: list   — OpenAI-compatible tool definitions for the LLM
    """
    from sqlalchemy import select, update
    from app.database import AsyncSessionLocal
    from app.models.models import MCPServer
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    from app.mcp_helper import get_mcp_server_params
    from app.encryption import decrypt_dict

    thread_id = args.get("thread_id")
    tool_overrides = args.get("tool_overrides", [])

    active_servers = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(MCPServer).where(MCPServer.is_active == True))
        active_servers = list(result.scalars().all())

    print(f"Discovered {len(active_servers)} active MCP servers", flush=True)
    heartbeat({"step": "discover_tools", "servers": len(active_servers)})

    mcp_tools_map = {}
    openai_tools = []
    server_id_to_name = {}

    for i, server in enumerate(active_servers):
        server_id_to_name[str(server.id)] = server.name
        print(f"Loading tools from MCP server: {server.name} ({server.image})", flush=True)
        heartbeat({"step": "discover_tools", "server": server.name, "index": i + 1})
        try:
            decrypted_env = await decrypt_dict(server.env_vars) or {}
            decrypted_args = await decrypt_dict(server.args) or {}
            params = get_mcp_server_params(server.image, decrypted_env, decrypted_args)

            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools_result = await session.list_tools()
                    print(f"Found {len(tools_result.tools)} tools on server {server.name}", flush=True)

                    # Cache discovered tools for the tool-overrides UI
                    cached = [
                        {"name": t.name, "description": t.description or ""}
                        for t in tools_result.tools
                    ]
                    async with AsyncSessionLocal() as cache_db:
                        await cache_db.execute(
                            update(MCPServer)
                            .where(MCPServer.id == server.id)
                            .values(cached_tools=cached)
                        )
                        await cache_db.commit()

                    for tool in tools_result.tools:
                        full_name = f"{server.name}_{tool.name}"
                        mcp_tools_map[full_name] = {
                            "image": server.image,
                            "env_vars": decrypted_env,
                            "args": decrypted_args,
                            "original_name": tool.name,
                            "server_name": server.name,
                        }
                        openai_tools.append({
                            "type": "function",
                            "function": {
                                "name": full_name,
                                "description": tool.description or "",
                                "parameters": tool.inputSchema,
                            },
                        })
        except Exception as e:
            print(f"ERROR: Failed to load MCP server {server.name}: {e}", flush=True)

    print(f"Total tools available to LLM: {len(openai_tools)}", flush=True)

    # ── Apply per-thread tool overrides ───────────────────────────────
    if tool_overrides:
        server_enabled = {}
        tool_enabled = {}

        for o in tool_overrides:
            server_name = server_id_to_name.get(o["server_id"])
            if server_name is None:
                continue
            if o.get("tool_name") is None:
                server_enabled[server_name] = o["enabled"]
            else:
                tool_enabled[(server_name, o["tool_name"])] = o["enabled"]

        filtered_tools = []
        filtered_map = {}
        for tool_def in openai_tools:
            full_name = tool_def["function"]["name"]
            info = mcp_tools_map.get(full_name, {})
            sname = info.get("server_name", "")
            tname = info.get("original_name", "")

            if (sname, tname) in tool_enabled:
                enabled = tool_enabled[(sname, tname)]
            elif sname in server_enabled:
                enabled = server_enabled[sname]
            else:
                enabled = True

            if enabled:
                filtered_tools.append(tool_def)
                filtered_map[full_name] = mcp_tools_map[full_name]

        removed = len(openai_tools) - len(filtered_tools)
        if removed > 0:
            print(f"Thread overrides: disabled {removed} tool(s), {len(filtered_tools)} remaining", flush=True)
        openai_tools = filtered_tools
        mcp_tools_map = filtered_map

    return {
        "mcp_tools_map": mcp_tools_map,
        "openai_tools": openai_tools,
    }


@defn
async def llm_turn(args: dict) -> dict:
    """Execute a single LLM call (non-streaming).

    If the LLM returns tool_calls, this activity publishes thinking events
    and returns the tool_calls for the workflow to dispatch to execute_tools.
    If the LLM returns a text response (no tool_calls), the workflow should
    call stream_response next.

    Returns:
        has_tool_calls: bool
        llm_message: dict        — the raw LLM response message (for appending to context)
        tool_calls: list | None  — tool_calls array if present
        thinking_content: str | None
        text_content: str | None — non-streaming fallback content (used if streaming fails)
    """
    import aiohttp

    messages = args.get("messages", [])
    config = args.get("llm_config", {})
    thread_id = args.get("thread_id")
    openai_tools = args.get("openai_tools", [])
    iteration = args.get("iteration", 1)
    max_iterations = args.get("max_iterations", 25)
    redis_url = config.get("redis_url")
    stream_channel = config.get("stream_channel")

    heartbeat({"step": "llm_call", "iteration": iteration})
    print(f"[agent-loop] iteration {iteration}/{max_iterations} | messages={len(messages)}", flush=True)

    api_url = config["api_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }

    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 2048),
    }
    if openai_tools:
        payload["tools"] = openai_tools

    timeout = aiohttp.ClientTimeout(total=config.get("stream_timeout", 600))

    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, headers=headers, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                await _publish(redis_url, stream_channel, f"[ERROR] {resp.status}: {error_text}")
                raise RuntimeError(f"LLM API error {resp.status}: {error_text}")

            data = await resp.json()
            choice = data["choices"][0]
            message = choice["message"]

            if message.get("tool_calls"):
                print(f"[agent-loop] LLM requested {len(message['tool_calls'])} tool call(s)", flush=True)
                thinking_content = message.get("content")

                # Publish thinking event if LLM returned content alongside tool_calls
                if thinking_content:
                    await _save_inline(thread_id, "thinking", thinking_content)
                    await _publish(redis_url, stream_channel, {"type": "thinking", "content": thinking_content})

                heartbeat({"step": "llm_call_done", "iteration": iteration, "tool_calls": len(message["tool_calls"])})

                return {
                    "has_tool_calls": True,
                    "llm_message": message,
                    "tool_calls": message["tool_calls"],
                    "thinking_content": thinking_content,
                    "text_content": None,
                }
            else:
                print(
                    f"[agent-loop] completed after {iteration} iteration(s) | "
                    f"streaming final response",
                    flush=True,
                )
                heartbeat({"step": "llm_call_done", "iteration": iteration, "tool_calls": 0})

                return {
                    "has_tool_calls": False,
                    "llm_message": message,
                    "tool_calls": None,
                    "thinking_content": None,
                    "text_content": message.get("content", ""),
                }


@defn
async def execute_tools(args: dict) -> dict:
    """Execute MCP tool calls and publish results.

    Launches ephemeral containers for each tool call, publishes tool_call
    and tool_result events to Redis, and saves intermediate messages to DB.

    Returns:
        tool_messages: list[dict]  — tool role messages to append to LLM context
    """
    import json
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    from app.mcp_helper import get_mcp_server_params

    tool_calls = args.get("tool_calls", [])
    mcp_tools_map = args.get("mcp_tools_map", {})
    thread_id = args.get("thread_id")
    config = args.get("llm_config", {})
    llm_message = args.get("llm_message", {})
    iteration = args.get("iteration", 1)
    redis_url = config.get("redis_url")
    stream_channel = config.get("stream_channel")

    heartbeat({"step": "execute_tools", "iteration": iteration, "count": len(tool_calls)})

    # Build human-readable description and publish tool_call event
    call_descriptions = []
    tool_list_for_event = []
    for tc in tool_calls:
        info = mcp_tools_map.get(tc["function"]["name"], {})
        desc = f"{info.get('server_name', '?')}:{info.get('original_name', tc['function']['name'])}"
        call_descriptions.append(desc)
        tool_list_for_event.append(desc)

    tool_call_content = "Calling " + ", ".join(call_descriptions)
    tool_call_metadata = {"tool_calls": tool_calls}

    await _save_inline(thread_id, "tool_call", tool_call_content, metadata=tool_call_metadata)
    await _publish(redis_url, stream_channel, {
        "type": "tool_call",
        "content": tool_call_content,
        "tools": tool_list_for_event,
        "tool_calls": tool_calls,
    })

    # Execute each tool call
    tool_messages = []
    for i, tool_call in enumerate(tool_calls):
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])

        if tool_name in mcp_tools_map:
            info = mcp_tools_map[tool_name]
            tool_display = f"{info['server_name']}:{info['original_name']}"

            heartbeat({
                "step": "tool_execution",
                "iteration": iteration,
                "tool": tool_display,
                "index": i + 1,
                "total": len(tool_calls),
            })

            try:
                exec_params = get_mcp_server_params(info["image"], info["env_vars"], info.get("args"))
                async with stdio_client(exec_params) as (read, write):
                    async with ClientSession(read, write) as mcp_session:
                        await mcp_session.initialize()
                        result = await mcp_session.call_tool(info["original_name"], tool_args)
                        result_text = "\n".join([c.text for c in result.content if hasattr(c, "text")])

                        # Truncate for LLM context if configured (0 = no limit)
                        max_chars = config.get("tool_result_max_chars", 0)
                        if max_chars and len(result_text) > max_chars:
                            llm_result_text = (
                                result_text[:max_chars]
                                + f"\n\n[TRUNCATED — result was {len(result_text):,} chars, "
                                f"showing first {max_chars:,}. "
                                "Consider using more specific parameters to narrow results.]"
                            )
                        else:
                            llm_result_text = result_text

                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "name": tool_name,
                            "content": llm_result_text,
                        })
                        result_meta = {
                            "tool_call_id": tool_call["id"],
                            "tool_name": tool_name,
                        }
                        # Save full (untruncated) result to DB and stream
                        await _save_inline(thread_id, "tool_result", result_text, metadata=result_meta)
                        await _publish(redis_url, stream_channel, {
                            "type": "tool_result",
                            "tool": tool_display,
                            "content": result_text,
                            "success": True,
                        })

                        heartbeat({
                            "step": "tool_result",
                            "iteration": iteration,
                            "tool": tool_display,
                            "success": True,
                        })
            except Exception as e:
                error_content = f"Error executing tool: {str(e)}"
                tool_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": tool_name,
                    "content": error_content,
                })
                result_meta = {
                    "tool_call_id": tool_call["id"],
                    "tool_name": tool_name,
                }
                await _save_inline(thread_id, "tool_result", error_content, metadata=result_meta)
                await _publish(redis_url, stream_channel, {
                    "type": "tool_result",
                    "tool": tool_display,
                    "content": error_content,
                    "success": False,
                })
                heartbeat({
                    "step": "tool_result",
                    "iteration": iteration,
                    "tool": tool_display,
                    "success": False,
                })
        else:
            not_found = "Tool not found"
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": tool_name,
                "content": not_found,
            })
            result_meta = {
                "tool_call_id": tool_call["id"],
                "tool_name": tool_name,
            }
            await _save_inline(thread_id, "tool_result", not_found, metadata=result_meta)
            await _publish(redis_url, stream_channel, {
                "type": "tool_result",
                "tool": tool_name,
                "content": not_found,
                "success": False,
            })

    return {"tool_messages": tool_messages}


@defn
async def stream_response(args: dict) -> dict:
    """Re-issue the final LLM call with stream:true for token-by-token output.

    Publishes each token to Redis. Falls back to the non-streaming text
    if the streaming call fails.

    Returns:
        content: str  — the full response text
    """
    import aiohttp
    import json as _json

    messages = args.get("messages", [])
    config = args.get("llm_config", {})
    fallback_content = args.get("fallback_content", "")
    redis_url = config.get("redis_url")
    stream_channel = config.get("stream_channel")

    heartbeat({"step": "streaming", "tokens": 0})

    api_url = config["api_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }

    # Omit tools — we already know this is the final text response,
    # and sending tool schemas forces the model to re-process them
    # for no reason, adding significant latency.
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 2048),
        "stream": True,
    }

    timeout = aiohttp.ClientTimeout(total=config.get("stream_timeout", 600))
    full_response_content = ""
    token_count = 0

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=payload, timeout=timeout) as resp:
                if resp.status != 200:
                    # Fall back to the non-streaming response we already have
                    full_response_content = fallback_content
                    await _publish(redis_url, stream_channel, {"type": "text", "content": full_response_content})
                    return {"content": full_response_content}

                buffer = ""
                async for raw_chunk in resp.content.iter_any():
                    buffer += raw_chunk.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[len("data: "):]
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk_data = _json.loads(data_str)
                            delta = chunk_data.get("choices", [{}])[0].get("delta", {})
                            token = delta.get("content")
                            if token:
                                full_response_content += token
                                token_count += 1
                                await _publish(redis_url, stream_channel, {"type": "token", "content": token})
                                if token_count % 50 == 0:
                                    heartbeat({"step": "streaming", "tokens": token_count})
                        except (ValueError, KeyError, IndexError):
                            continue
    except Exception as e:
        print(f"[stream_response] Streaming failed, using fallback: {e}", flush=True)
        if not full_response_content:
            full_response_content = fallback_content
            if full_response_content:
                await _publish(redis_url, stream_channel, {"type": "text", "content": full_response_content})

    heartbeat({"step": "streaming_done", "tokens": token_count})
    return {"content": full_response_content}


# ═══════════════════════════════════════════════════════════════════════
#  LIGHTWEIGHT generate_title — used for auto-title generation only
# ═══════════════════════════════════════════════════════════════════════

@defn
async def generate_title(args: dict) -> dict:
    """Simple LLM call without tools or streaming.

    Used exclusively for auto-title generation and other simple LLM tasks
    that don't need MCP tools, Redis streaming, or the agent loop.

    Returns:
        content: str  — the LLM response text
    """
    import aiohttp

    messages = args.get("messages", [])
    config = args.get("llm_config", {})

    api_url = config["api_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }
    payload = {
        "model": config["model"],
        "messages": messages,
        "temperature": config.get("temperature", 0.7),
        "max_tokens": config.get("max_tokens", 2048),
    }

    timeout = aiohttp.ClientTimeout(total=config.get("stream_timeout", 60))

    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, headers=headers, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                raise RuntimeError(f"LLM API error {resp.status}: {error_text}")

            data = await resp.json()
            content = data["choices"][0]["message"]["content"]
            return {"content": content}


# ═══════════════════════════════════════════════════════════════════════
#  EXISTING ACTIVITIES — unchanged
# ═══════════════════════════════════════════════════════════════════════

@defn
async def publish_done(args: dict) -> None:
    """Publish [DONE] sentinel to Redis stream channel.

    Called by the workflow AFTER all messages are saved to DB,
    so the frontend can safely reload from DB when it receives this.
    Also buffers [DONE] in the events list and cleans up the generating flag.
    """
    redis_url = args.get("redis_url")
    stream_channel = args.get("stream_channel")
    thread_id = args.get("thread_id")
    if not redis_url or not stream_channel:
        return

    import redis.asyncio as aioredis
    r = aioredis.from_url(redis_url)
    try:
        events_key = f"events:{stream_channel}"
        await r.publish(stream_channel, b"[DONE]")
        await r.rpush(events_key, b"[DONE]")
        # Keep events list for 60s so a reconnecting client can still read it
        await r.expire(events_key, 60)
        # Clear the generating flag
        if thread_id:
            await r.delete(f"generating:{thread_id}")
    finally:
        await r.close()


@defn
async def publish_title(args: dict) -> None:
    """Publish a title event to Redis so the frontend sidebar updates in real-time."""
    import json
    redis_url = args.get("redis_url")
    stream_channel = args.get("stream_channel")
    title = args.get("title", "")
    if not redis_url or not stream_channel:
        return

    import redis.asyncio as aioredis
    r = aioredis.from_url(redis_url)
    try:
        event = json.dumps({"type": "title", "content": title})
        data = event.encode("utf-8")
        await r.publish(stream_channel, data)
        events_key = f"events:{stream_channel}"
        await r.rpush(events_key, data)
        await r.expire(events_key, 600)
    finally:
        await r.close()


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
        # Skip thinking messages — they're display-only, not part of LLM context
        if m.role == "thinking":
            continue
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
        f"limit={int(token_limit)} (window={context_window} x threshold={threshold})",
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
