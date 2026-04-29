from temporalio.activity import defn


@defn
async def call_llm(args: dict) -> dict:
    """Call the OpenAI-compatible LLM API with MCP tool support.
    
    Saves intermediate messages (thinking, tool_call, tool_result) to the DB
    inline as they happen. Publishes structured JSON events to Redis so the
    frontend can render each step in real time.

    Returns a dict with:
        content: str  — final assistant response text
    """
    import aiohttp

    messages = args.get("messages", [])
    config = args.get("llm_config", {})
    thread_id = args.get("thread_id")
    redis_url = config.get("redis_url")
    stream_channel = config.get("stream_channel")

    # ── Redis publisher setup ─────────────────────────────────────────
    redis_client = None
    if redis_url and stream_channel:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(redis_url)

    import json as _json

    async def publish(event: dict | str | bytes):
        """Publish a structured JSON event (or raw sentinel) to Redis.
        
        Events are both PUBLISHed (for the live SSE connection) and RPUSHed
        to an events list (for reconnect after page refresh).
        """
        if redis_client and stream_channel:
            if isinstance(event, dict):
                data = _json.dumps(event).encode("utf-8")
            elif isinstance(event, str):
                data = event.encode("utf-8")
            else:
                data = event
            events_key = f"events:{stream_channel}"
            await redis_client.publish(stream_channel, data)
            await redis_client.rpush(events_key, data)
            await redis_client.expire(events_key, 600)

    # ── Inline DB save helper ─────────────────────────────────────────
    async def save_inline(role: str, content: str, metadata: dict | None = None):
        """Persist a message to the DB immediately (non-blocking to workflow)."""
        if not thread_id:
            return
        from uuid import UUID
        from app.database import AsyncSessionLocal
        from app.database.crud import add_message
        async with AsyncSessionLocal() as db:
            await add_message(db, UUID(thread_id), role, content, metadata=metadata)
            await db.commit()

    # ── MCP Tool Setup ────────────────────────────────────────────────
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.models import MCPServer
    import json
    import asyncio
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    from app.mcp_helper import get_mcp_server_params

    active_servers = []
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(MCPServer).where(MCPServer.is_active == True))
        active_servers = list(result.scalars().all())

    print(f"Discovered {len(active_servers)} active MCP servers", flush=True)

    # Decrypt env_vars and args for each server
    from app.encryption import decrypt_dict

    # Map of tool_name -> server_info
    mcp_tools_map = {}
    openai_tools = []

    for server in active_servers:
        print(f"Loading tools from MCP server: {server.name} ({server.image})", flush=True)
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
                        from sqlalchemy import update
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

    # ── Apply per-thread tool overrides ───────────────────────────────
    tool_overrides = config.get("tool_overrides", [])
    if tool_overrides:
        # Build lookup: (server_name) -> server-level enabled
        # and (server_name, tool_name) -> tool-level enabled
        server_enabled = {}
        tool_enabled = {}
        # We need to map server_id -> server_name. Build from active_servers.
        server_id_to_name = {str(s.id): s.name for s in active_servers}

        for o in tool_overrides:
            server_name = server_id_to_name.get(o["server_id"])
            if server_name is None:
                continue
            if o.get("tool_name") is None:
                # Server-level override
                server_enabled[server_name] = o["enabled"]
            else:
                # Tool-level override
                tool_enabled[(server_name, o["tool_name"])] = o["enabled"]

        # Filter openai_tools and mcp_tools_map
        filtered_tools = []
        filtered_map = {}
        for tool_def in openai_tools:
            full_name = tool_def["function"]["name"]
            info = mcp_tools_map.get(full_name, {})
            sname = info.get("server_name", "")
            tname = info.get("original_name", "")

            # Check tool-level override first, then server-level, default to enabled
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

    # ── LLM Interaction Loop ──────────────────────────────────────────
    api_url = config["api_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config['api_key']}",
    }

    current_messages = list(messages)
    full_response_content = ""
    max_iterations = config.get("max_iterations", 25)
    iteration = 0
    used_tools = False

    # Inject a system message when tools are available to encourage multi-step use
    if openai_tools and (not current_messages or current_messages[0].get("role") != "system"):
        current_messages.insert(0, {
            "role": "system",
            "content": (
                "You are a helpful assistant with access to tools. "
                "Use tools as many times as needed to thoroughly answer the user's question. "
                "Think step by step: gather information, verify it, and refine your answer "
                "before providing a final response. You may call multiple tools in sequence."
            ),
        })

    async with aiohttp.ClientSession() as session:
        while iteration < max_iterations:
            iteration += 1
            print(f"[agent-loop] iteration {iteration}/{max_iterations} | messages={len(current_messages)}", flush=True)

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
                    await publish(f"[ERROR] {resp.status}: {error_text}")
                    raise RuntimeError(f"LLM API error {resp.status}: {error_text}")

                data = await resp.json()
                choice = data["choices"][0]
                message = choice["message"]

                # Handle Tool Calls
                if message.get("tool_calls"):
                    used_tools = True
                    print(f"[agent-loop] LLM requested {len(message['tool_calls'])} tool call(s)", flush=True)
                    # If the LLM also returned content alongside tool_calls, that's "thinking"
                    thinking_content = message.get("content")
                    if thinking_content:
                        await save_inline("thinking", thinking_content)
                        await publish({"type": "thinking", "content": thinking_content})

                    current_messages.append(message)

                    # Build a human-readable description of what's being called
                    call_descriptions = []
                    tool_list_for_event = []
                    for tc in message["tool_calls"]:
                        info = mcp_tools_map.get(tc["function"]["name"], {})
                        desc = f"{info.get('server_name', '?')}:{info.get('original_name', tc['function']['name'])}"
                        call_descriptions.append(desc)
                        tool_list_for_event.append(desc)

                    tool_call_content = "Calling " + ", ".join(call_descriptions)
                    tool_call_metadata = {"tool_calls": message["tool_calls"]}

                    # Save tool_call to DB inline
                    await save_inline("tool_call", tool_call_content, metadata=tool_call_metadata)
                    await publish({
                        "type": "tool_call",
                        "content": tool_call_content,
                        "tools": tool_list_for_event,
                        "tool_calls": message["tool_calls"],
                    })

                    for tool_call in message["tool_calls"]:
                        tool_name = tool_call["function"]["name"]
                        tool_args = json.loads(tool_call["function"]["arguments"])

                        if tool_name in mcp_tools_map:
                            info = mcp_tools_map[tool_name]
                            tool_display = f"{info['server_name']}:{info['original_name']}"

                            try:
                                exec_params = get_mcp_server_params(info["image"], info["env_vars"], info.get("args"))
                                async with stdio_client(exec_params) as (read, write):
                                    async with ClientSession(read, write) as mcp_session:
                                        await mcp_session.initialize()
                                        result = await mcp_session.call_tool(info["original_name"], tool_args)
                                        result_text = "\n".join([c.text for c in result.content if hasattr(c, 'text')])

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

                                        current_messages.append({
                                            "role": "tool",
                                            "tool_call_id": tool_call["id"],
                                            "name": tool_name,
                                            "content": llm_result_text
                                        })
                                        result_meta = {
                                            "tool_call_id": tool_call["id"],
                                            "tool_name": tool_name,
                                        }
                                        # Save full (untruncated) result to DB and stream
                                        await save_inline("tool_result", result_text, metadata=result_meta)
                                        await publish({
                                            "type": "tool_result",
                                            "tool": tool_display,
                                            "content": result_text,
                                            "success": True,
                                        })
                            except Exception as e:
                                error_content = f"Error executing tool: {str(e)}"
                                current_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call["id"],
                                    "name": tool_name,
                                    "content": error_content
                                })
                                result_meta = {
                                    "tool_call_id": tool_call["id"],
                                    "tool_name": tool_name,
                                }
                                await save_inline("tool_result", error_content, metadata=result_meta)
                                await publish({
                                    "type": "tool_result",
                                    "tool": tool_display,
                                    "content": error_content,
                                    "success": False,
                                })
                        else:
                            not_found = "Tool not found"
                            current_messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "name": tool_name,
                                "content": not_found
                            })
                            result_meta = {
                                "tool_call_id": tool_call["id"],
                                "tool_name": tool_name,
                            }
                            await save_inline("tool_result", not_found, metadata=result_meta)
                            await publish({
                                "type": "tool_result",
                                "tool": tool_name,
                                "content": not_found,
                                "success": False,
                            })
                    continue  # Loop back to LLM with tool results

                # Final response — re-issue with streaming for token-by-token output
                print(
                    f"[agent-loop] completed after {iteration} iteration(s) | "
                    f"used_tools={used_tools} | streaming final response",
                    flush=True,
                )

                # Re-issue the same call with stream:true to get token-by-token output
                # Omit tools — we already know this is the final text response,
                # and sending 21 tool schemas forces the model to re-process them
                # for no reason, adding significant latency.
                stream_payload = dict(payload, stream=True)
                stream_payload.pop("tools", None)
                full_response_content = ""
                async with session.post(api_url, headers=headers, json=stream_payload, timeout=timeout) as stream_resp:
                    if stream_resp.status != 200:
                        # Fall back to the non-streaming response we already have
                        full_response_content = message.get("content", "")
                        await publish({"type": "text", "content": full_response_content})
                        break

                    buffer = ""
                    async for raw_chunk in stream_resp.content.iter_any():
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
                                    await publish({"type": "token", "content": token})
                            except (ValueError, KeyError, IndexError):
                                continue
                break
        else:
            # Safety exit — max iterations reached
            print(
                f"[agent-loop] WARNING: max iterations ({max_iterations}) reached, "
                f"forcing final response",
                flush=True,
            )
            if not full_response_content:
                full_response_content = "(Agent reached maximum iteration limit.)"
            await publish({"type": "text", "content": full_response_content})

    if redis_client:
        await redis_client.close()

    return {
        "content": full_response_content,
        "used_tools": used_tools,
        "iterations": iteration,
    }


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
