from temporalio.activity import defn, heartbeat


# ── Workflow stream publish helper (used by multiple activities) ──────
async def _publish(redis_url: str, stream_channel: str, event):
    """Publish a structured event to the parent workflow stream.

    The first two parameters are ignored and kept only for compatibility with
    older call sites.
    """
    if not isinstance(event, dict):
        if isinstance(event, str) and event.startswith("[ERROR]"):
            event = {"type": "error", "content": event[7:].strip()}
        elif event == "[DONE]":
            event = {"type": "done"}
        else:
            return

    try:
        from temporalio.contrib.workflow_streams import WorkflowStreamClient

        client = WorkflowStreamClient.from_within_activity(max_batch_size=1)
        events = client.topic("events", type=dict)
        async with client:
            events.publish(event, force_flush=True)
    except Exception as e:
        print(f"[stream] Failed to publish workflow stream event: {e}", flush=True)


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
    from app.discord_integration import sync_message_to_discord
    await sync_message_to_discord(UUID(thread_id), role, content, metadata=metadata)


def _agents_model_settings(config: dict, *, temperature: float | None = None, max_tokens: int | None = None):
    from agents import ModelSettings

    return ModelSettings(
        temperature=config.get("temperature", 0.7) if temperature is None else temperature,
        max_tokens=config.get("max_tokens", 2048) if max_tokens is None else max_tokens,
        include_usage=True,
    )


def _agents_provider_and_model(config: dict):
    """Build an OpenAI Agents SDK model, using local providers when configured."""
    from app.agents_provider import build_agents_model_provider

    provider = build_agents_model_provider(config)
    return provider, provider.get_model(config.get("model"))


async def _close_agents_provider(provider) -> None:
    close = getattr(provider, "aclose", None) or getattr(provider, "close", None)
    if close:
        result = close()
        if hasattr(result, "__await__"):
            await result


def _agents_tools(openai_tools: list[dict], mcp_tools_map: dict | None = None, thread_id: str | None = None, config: dict | None = None) -> list:
    from agents import FunctionTool

    mcp_tools_map = mcp_tools_map or {}
    config = config or {}
    tools = []
    for tool_def in openai_tools:
        fn = tool_def.get("function", {})
        tool_name = fn.get("name", "")

        async def invoke_tool(ctx, args: str, *, name=tool_name) -> str:
            return await _execute_agent_tool(name, args, ctx.tool_call_id, mcp_tools_map, thread_id, config)

        tools.append(
            FunctionTool(
                name=tool_name,
                description=fn.get("description") or "",
                params_json_schema=fn.get("parameters") or {"type": "object", "properties": {}},
                on_invoke_tool=invoke_tool,
                strict_json_schema=False,
            )
        )
    return tools


def _dump_agents_item(item) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    if hasattr(item, "dict"):
        return item.dict()
    return item if isinstance(item, dict) else {}


def _extract_agents_response(response) -> dict:
    content_parts = []
    reasoning_parts = []
    tool_calls = []

    for item in response.output:
        data = _dump_agents_item(item)
        item_type = data.get("type")

        if item_type == "message":
            for part in data.get("content") or []:
                if part.get("type") == "output_text":
                    content_parts.append(part.get("text") or "")
                elif part.get("type") == "refusal":
                    content_parts.append(part.get("refusal") or "")

        elif item_type == "reasoning":
            for summary in data.get("summary") or []:
                text = summary.get("text")
                if text:
                    reasoning_parts.append(text)
            for part in data.get("content") or []:
                text = part.get("text")
                if text:
                    reasoning_parts.append(text)

        elif item_type == "function_call":
            call_id = data.get("call_id") or data.get("id") or f"call_{len(tool_calls) + 1}"
            tool_calls.append({
                "id": call_id,
                "type": "function",
                "function": {
                    "name": data.get("name") or "",
                    "arguments": data.get("arguments") or "{}",
                },
            })

    usage = getattr(response, "usage", None)
    total_tokens = getattr(usage, "total_tokens", 0) if usage else 0
    content = "".join(content_parts)
    reasoning = "\n".join(reasoning_parts)
    message = {
        "role": "assistant",
        "content": content if content else None,
    }
    if reasoning:
        message["reasoning"] = reasoning
    if tool_calls:
        message["tool_calls"] = tool_calls

    return {
        "message": message,
        "content": content,
        "reasoning": reasoning,
        "tool_calls": tool_calls,
        "total_tokens": total_tokens,
    }


async def _agents_chat_completion(
    messages: list[dict],
    config: dict,
    *,
    openai_tools: list[dict] | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict:
    from agents.models.interface import ModelTracing

    provider, model = _agents_provider_and_model(config)
    try:
        response = await model.get_response(
            system_instructions=None,
            input=messages,
            model_settings=_agents_model_settings(config, temperature=temperature, max_tokens=max_tokens),
            tools=_agents_tools(openai_tools or []),
            output_schema=None,
            handoffs=[],
            tracing=ModelTracing.DISABLED,
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
        return _extract_agents_response(response)
    finally:
        await _close_agents_provider(provider)


async def _execute_agent_tool(
    tool_name: str,
    arguments: str,
    tool_call_id: str,
    mcp_tools_map: dict,
    thread_id: str | None,
    config: dict,
) -> str:
    import json

    from mcp import ClientSession
    from mcp.client.stdio import stdio_client
    from app.mcp_helper import get_mcp_server_params

    redis_url = config.get("redis_url")
    stream_channel = config.get("stream_channel")
    builtin_tools = {
        "continue_thinking", "web_fetch", "current_datetime", "calculator",
        "json_parse", "text_count", "base64_decode", "base64_encode",
    }
    tool_args = json.loads(arguments or "{}")
    tool_call = {
        "id": tool_call_id,
        "type": "function",
        "function": {"name": tool_name, "arguments": arguments or "{}"},
    }

    if tool_name in builtin_tools:
        display_name = f"built-in:{tool_name}"
        if tool_name != "continue_thinking":
            await _save_inline(
                thread_id,
                "tool_call",
                f"Calling {display_name}",
                metadata={"tool_calls": [tool_call]},
            )
            await _publish(redis_url, stream_channel, {
                "type": "tool_call",
                "content": f"Calling {display_name}",
                "tools": [display_name],
                "tool_calls": [tool_call],
            })

        result_text = await _execute_builtin(tool_name, tool_args, thread_id, redis_url, stream_channel)
        if tool_name != "continue_thinking":
            await _save_inline(
                thread_id,
                "tool_result",
                result_text,
                metadata={"tool_call_id": tool_call_id, "tool_name": tool_name},
            )
            await _publish(redis_url, stream_channel, {
                "type": "tool_result",
                "tool": display_name,
                "content": result_text,
                "success": True,
            })
        return result_text

    if tool_name not in mcp_tools_map:
        not_found = "Tool not found"
        await _save_inline(
            thread_id,
            "tool_result",
            not_found,
            metadata={"tool_call_id": tool_call_id, "tool_name": tool_name},
        )
        await _publish(redis_url, stream_channel, {
            "type": "tool_result",
            "tool": tool_name,
            "content": not_found,
            "success": False,
        })
        return not_found

    info = mcp_tools_map[tool_name]
    display_name = f"{info['server_name']}:{info['original_name']}"
    await _save_inline(
        thread_id,
        "tool_call",
        f"Calling {display_name}",
        metadata={"tool_calls": [tool_call]},
    )
    await _publish(redis_url, stream_channel, {
        "type": "tool_call",
        "content": f"Calling {display_name}",
        "tools": [display_name],
        "tool_calls": [tool_call],
    })

    try:
        exec_params = get_mcp_server_params(info["image"], info["env_vars"], info.get("args"))
        async with stdio_client(exec_params) as (read, write):
            async with ClientSession(read, write) as mcp_session:
                await mcp_session.initialize()
                result = await mcp_session.call_tool(info["original_name"], tool_args)
                result_text = "\n".join([c.text for c in result.content if hasattr(c, "text")])
    except Exception as e:
        result_text = f"Error executing tool: {str(e)}"
        await _save_inline(
            thread_id,
            "tool_result",
            result_text,
            metadata={"tool_call_id": tool_call_id, "tool_name": tool_name},
        )
        await _publish(redis_url, stream_channel, {
            "type": "tool_result",
            "tool": display_name,
            "content": result_text,
            "success": False,
        })
        return result_text

    await _save_inline(
        thread_id,
        "tool_result",
        result_text,
        metadata={"tool_call_id": tool_call_id, "tool_name": tool_name},
    )
    await _publish(redis_url, stream_channel, {
        "type": "tool_result",
        "tool": display_name,
        "content": result_text,
        "success": True,
    })

    max_chars = config.get("tool_result_max_chars", 0)
    if max_chars and len(result_text) > max_chars:
        return (
            result_text[:max_chars]
            + f"\n\n[TRUNCATED — result was {len(result_text):,} chars, "
            f"showing first {max_chars:,}. "
            "Consider using more specific parameters to narrow results.]"
        )
    return result_text


@defn
async def execute_agent_tool_activity(args: dict) -> str:
    """Execute one Agents SDK tool call as a Temporal activity."""
    return await _execute_agent_tool(
        args["tool_name"],
        args.get("arguments") or "{}",
        args.get("tool_call_id") or "",
        args.get("mcp_tools_map") or {},
        args.get("thread_id"),
        args.get("llm_config") or {},
    )


# ═══════════════════════════════════════════════════════════════════════
#  Tool discovery and OpenAI Agents SDK runner
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
async def run_agent_response(args: dict) -> dict:
    """Run the OpenAI Agents SDK loop and stream ThreadBot-compatible events."""
    from agents import Agent, Runner, set_tracing_disabled

    messages = args.get("messages", [])
    config = args.get("llm_config", {})
    openai_tools = args.get("openai_tools", [])
    mcp_tools_map = args.get("mcp_tools_map", {})
    thread_id = args.get("thread_id")
    redis_url = config.get("redis_url")
    stream_channel = config.get("stream_channel")
    max_turns = config.get("max_iterations", 25)

    heartbeat({"step": "agent_run", "max_turns": max_turns})
    set_tracing_disabled(True)

    provider, model = _agents_provider_and_model(config)
    agent = Agent(
        name="ThreadBot",
        instructions=(
            "You are a helpful assistant. Use tools as many times as needed to thoroughly "
            "answer the user's question. Gather information, verify it, and refine your "
            "answer before providing a final response."
        ),
        model=model,
        model_settings=_agents_model_settings(config),
        tools=_agents_tools(openai_tools, mcp_tools_map, thread_id, config),
    )

    full_response_content = ""
    reasoning_buffer = ""
    token_count = 0

    try:
        result = Runner.run_streamed(agent, messages, max_turns=max_turns)
        async for event in result.stream_events():
            if event.type == "raw_response_event":
                raw = event.data
                raw_type = getattr(raw, "type", None)
                if raw_type in {"response.output_text.delta", "response.refusal.delta"}:
                    token = getattr(raw, "delta", "")
                    if token:
                        full_response_content += token
                        token_count += 1
                        await _publish(redis_url, stream_channel, {"type": "token", "content": token})
                        if token_count % 50 == 0:
                            heartbeat({"step": "agent_streaming", "tokens": token_count})
                elif raw_type in {"response.reasoning_text.delta", "response.reasoning_summary_text.delta"}:
                    reasoning_buffer += getattr(raw, "delta", "") or ""
                elif raw_type == "response.completed":
                    usage = getattr(raw.response, "usage", None)
                    total_tokens = getattr(usage, "total_tokens", 0) if usage else 0
                    if total_tokens:
                        await _publish(redis_url, stream_channel, {
                            "type": "context",
                            "estimated_tokens": total_tokens,
                            "context_window": config.get("context_window", 8192),
                        })

            elif event.type == "run_item_stream_event" and event.name == "reasoning_item_created":
                data = _dump_agents_item(event.item.raw_item)
                parts = []
                for summary in data.get("summary") or []:
                    text = summary.get("text")
                    if text:
                        parts.append(text)
                for part in data.get("content") or []:
                    text = part.get("text")
                    if text:
                        parts.append(text)
                thinking = "\n".join(parts).strip()
                if thinking:
                    await _save_inline(thread_id, "thinking", thinking)
                    await _publish(redis_url, stream_channel, {"type": "thinking", "content": thinking})

        if result.run_loop_exception:
            raise result.run_loop_exception

        final_output = "" if result.final_output is None else str(result.final_output)
        if reasoning_buffer.strip():
            await _save_inline(thread_id, "thinking", reasoning_buffer.strip())
            await _publish(redis_url, stream_channel, {"type": "thinking", "content": reasoning_buffer.strip()})
        if final_output and not full_response_content:
            await _publish(redis_url, stream_channel, {"type": "text", "content": final_output})
        heartbeat({"step": "agent_done", "tokens": token_count})
        return {"content": final_output or full_response_content}
    except Exception as e:
        await _publish(redis_url, stream_channel, f"[ERROR] Agent run failed: {str(e)}")
        raise
    finally:
        await _close_agents_provider(provider)


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

    try:
        completion = await _agents_chat_completion(
            messages,
            config,
            openai_tools=openai_tools,
        )
    except Exception as e:
        await _publish(redis_url, stream_channel, f"[ERROR] LLM API error: {str(e)}")
        raise

    message = completion["message"]

    # Publish context usage estimate
    context_window = config.get("context_window", 8192)
    response_chars = len(message.get("content", "") or "")
    total_chars = sum(len(m.get("content", "") or "") for m in messages) + response_chars
    estimated_tokens = completion.get("total_tokens") or int(total_chars / 4)
    await _publish(redis_url, stream_channel, {
        "type": "context",
        "estimated_tokens": estimated_tokens,
        "context_window": context_window,
    })

    if message.get("tool_calls"):
        print(f"[agent-loop] LLM requested {len(message['tool_calls'])} tool call(s)", flush=True)
        thinking_content = message.get("content") or message.get("reasoning") or ""

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

        # Publish reasoning here — stream_response re-issues the call
        # but streaming APIs may not return reasoning deltas.
        reasoning = message.get("reasoning") or ""
        if reasoning:
            await _save_inline(thread_id, "thinking", reasoning)
            await _publish(redis_url, stream_channel, {"type": "thinking", "content": reasoning})

        heartbeat({"step": "llm_call_done", "iteration": iteration, "tool_calls": 0})

        return {
            "has_tool_calls": False,
            "llm_message": message,
            "tool_calls": None,
            "thinking_content": reasoning or None,
            "text_content": message.get("content", ""),
        }


# ═══════════════════════════════════════════════════════════════════════
#  Built-in tool execution (no MCP containers)
# ═══════════════════════════════════════════════════════════════════════

async def _execute_builtin(
    tool_name: str,
    tool_args: dict,
    thread_id: str,
    redis_url: str | None,
    stream_channel: str | None,
) -> str:
    """Execute a built-in tool and return the result as a string."""

    if tool_name == "continue_thinking":
        reasoning_text = tool_args.get("reasoning", "")
        if reasoning_text:
            await _save_inline(thread_id, "thinking", reasoning_text)
            await _publish(redis_url, stream_channel, {"type": "thinking", "content": reasoning_text})
        return "Acknowledged. Continue your analysis."

    if tool_name == "web_fetch":
        import aiohttp
        url = tool_args.get("url", "")
        start_index = int(tool_args.get("start_index", 0))
        max_chars = int(tool_args.get("max_chars", 5000))
        query = str(tool_args.get("query") or "")
        use_regex = bool(tool_args.get("use_regex", False))
        context_chars = int(tool_args.get("context_chars", 800))
        max_matches = int(tool_args.get("max_matches", 5))
        case_sensitive = bool(tool_args.get("case_sensitive", False))
        if not url.startswith(("http://", "https://")):
            return "Error: URL must start with http:// or https://"
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=timeout, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return f"Error: HTTP {resp.status}"
                    content_type = resp.headers.get("Content-Type", "")
                    if "text" in content_type or "json" in content_type or "xml" in content_type:
                        text = await resp.text()
                        total_len = len(text)
                        if query:
                            matches = []
                            if use_regex:
                                import re

                                try:
                                    flags = 0 if case_sensitive else re.IGNORECASE
                                    pattern = re.compile(query, flags)
                                except re.error as e:
                                    return f"Error: invalid regex query {query!r}: {e}"

                                for match in pattern.finditer(text):
                                    matches.append((match.start(), match.end()))
                                    if len(matches) >= max(1, max_matches):
                                        break
                            else:
                                haystack = text if case_sensitive else text.lower()
                                needle = query if case_sensitive else query.lower()
                                pos = haystack.find(needle)
                                while pos != -1 and len(matches) < max(1, max_matches):
                                    matches.append((pos, pos + len(query)))
                                    pos = haystack.find(needle, pos + max(1, len(needle)))

                            if not matches:
                                return (
                                    f"[Page content: {total_len:,} chars total. No matches found for "
                                    f"{'regex' if use_regex else 'query'} {query!r}. Try a different query "
                                    "or use pagination with start_index "
                                    "and max_chars to inspect the page manually.]"
                                )

                            snippets = []
                            context_chars = max(0, min(context_chars, 5000))
                            for idx, (match_start, match_end) in enumerate(matches, start=1):
                                snippet_start = max(0, match_start - context_chars)
                                snippet_end = min(total_len, match_end + context_chars)
                                snippet = text[snippet_start:snippet_end]
                                snippets.append(
                                    f"[Match {idx} at chars {match_start:,}-{match_end:,}; "
                                    f"showing chars {snippet_start:,}-{snippet_end:,}]\n{snippet}"
                                )

                            header = (
                                f"[Page content: {total_len:,} chars total. Found {len(matches)} "
                                f"match(es) for {'regex' if use_regex else 'query'} {query!r}.]"
                            )
                            return header + "\n\n" + "\n\n---\n\n".join(snippets)

                        # Clamp start_index
                        start_index = max(0, min(start_index, total_len))
                        end_index = min(start_index + max_chars, total_len)
                        chunk = text[start_index:end_index]
                        header = f"[Page content: {total_len:,} chars total. Showing chars {start_index:,}-{end_index:,}.]"
                        if end_index < total_len:
                            remaining = total_len - end_index
                            header += f"\n[{remaining:,} chars remaining. Use start_index={end_index} to continue reading.]"
                        return header + "\n\n" + chunk
                    else:
                        return f"Binary content ({content_type}), {resp.content_length or 'unknown'} bytes — cannot display as text."
        except Exception as e:
            return f"Error fetching URL: {str(e)}"

    if tool_name == "current_datetime":
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        local = datetime.now().astimezone()
        return (
            f"UTC:   {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"Local: {local.strftime('%Y-%m-%d %H:%M:%S %Z (%z)')}\n"
            f"Day:   {local.strftime('%A')}\n"
            f"Unix:  {int(now.timestamp())}"
        )

    if tool_name == "calculator":
        import math
        expression = tool_args.get("expression", "")
        # Whitelist of safe names for eval
        safe_names = {
            "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
            "tan": math.tan, "log": math.log, "log10": math.log10,
            "abs": abs, "round": round, "ceil": math.ceil,
            "floor": math.floor, "pi": math.pi, "e": math.e,
            "pow": pow, "min": min, "max": max,
        }
        try:
            result = eval(expression, {"__builtins__": {}}, safe_names)  # noqa: S307
            return str(result)
        except Exception as e:
            return f"Error evaluating expression: {str(e)}"

    if tool_name == "json_parse":
        import json as _json
        json_string = tool_args.get("json_string", "")
        key_path = tool_args.get("key_path", "")
        try:
            data = _json.loads(json_string)
            if key_path:
                for key in key_path.split("."):
                    if isinstance(data, list):
                        data = data[int(key)]
                    elif isinstance(data, dict):
                        data = data[key]
                    else:
                        return f"Error: cannot traverse into {type(data).__name__} with key '{key}'"
            return _json.dumps(data, indent=2) if isinstance(data, (dict, list)) else str(data)
        except _json.JSONDecodeError as e:
            return f"Error parsing JSON: {str(e)}"
        except (KeyError, IndexError, ValueError) as e:
            return f"Error accessing path '{key_path}': {str(e)}"

    if tool_name == "text_count":
        import re
        text = tool_args.get("text", "")
        unit = tool_args.get("unit", "words")
        if unit == "words":
            count = len(text.split())
        elif unit == "characters":
            count = len(text)
        elif unit == "lines":
            count = len(text.splitlines()) if text else 0
        elif unit == "sentences":
            count = len(re.split(r'[.!?]+\s*', text.strip())) if text.strip() else 0
        else:
            return f"Error: unknown unit '{unit}'. Use words, characters, lines, or sentences."
        return f"{count} {unit}"

    if tool_name == "base64_decode":
        import base64
        encoded = tool_args.get("encoded", "")
        try:
            decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
            return decoded
        except Exception as e:
            return f"Error decoding base64: {str(e)}"

    if tool_name == "base64_encode":
        import base64
        text = tool_args.get("text", "")
        try:
            encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
            return encoded
        except Exception as e:
            return f"Error encoding base64: {str(e)}"

    return f"Error: unknown built-in tool '{tool_name}'"


@defn
async def execute_tools(args: dict) -> dict:
    """Execute MCP tool calls and publish results.

    Launches ephemeral containers for each tool call, publishes tool_call
    and tool_result events to the workflow stream, and saves intermediate messages to DB.

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

    # Names of built-in tools that don't require MCP containers
    BUILTIN_TOOLS = {
        "continue_thinking", "web_fetch", "current_datetime", "calculator",
        "json_parse", "text_count", "base64_decode", "base64_encode",
    }

    # Build human-readable description and publish tool_call event
    call_descriptions = []
    tool_list_for_event = []
    for tc in tool_calls:
        fn_name = tc["function"]["name"]
        if fn_name in BUILTIN_TOOLS:
            # Built-in tools get a clean display name
            desc = f"built-in:{fn_name}"
            # Only add non-silent built-ins to the tool_call event
            if fn_name != "continue_thinking":
                call_descriptions.append(desc)
                tool_list_for_event.append(desc)
            continue
        info = mcp_tools_map.get(fn_name, {})
        desc = f"{info.get('server_name', '?')}:{info.get('original_name', fn_name)}"
        call_descriptions.append(desc)
        tool_list_for_event.append(desc)

    if call_descriptions:
        tool_call_content = "Calling " + ", ".join(call_descriptions)
        mcp_tool_calls = [tc for tc in tool_calls if tc["function"]["name"] not in BUILTIN_TOOLS]
        tool_call_metadata = {"tool_calls": mcp_tool_calls or tool_calls}

        await _save_inline(thread_id, "tool_call", tool_call_content, metadata=tool_call_metadata)
        await _publish(redis_url, stream_channel, {
            "type": "tool_call",
            "content": tool_call_content,
            "tools": tool_list_for_event,
            "tool_calls": mcp_tool_calls or tool_calls,
        })

    # Execute each tool call
    tool_messages = []
    for i, tool_call in enumerate(tool_calls):
        tool_name = tool_call["function"]["name"]
        tool_args = json.loads(tool_call["function"]["arguments"])

        # ── Built-in tool handlers ────────────────────────────────────
        if tool_name in BUILTIN_TOOLS:
            result_text = await _execute_builtin(
                tool_name, tool_args, thread_id, redis_url, stream_channel,
            )
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": tool_name,
                "content": result_text,
            })
            # Publish result for non-silent built-ins
            if tool_name != "continue_thinking":
                result_meta = {"tool_call_id": tool_call["id"], "tool_name": tool_name}
                await _save_inline(thread_id, "tool_result", result_text, metadata=result_meta)
                await _publish(redis_url, stream_channel, {
                    "type": "tool_result",
                    "tool": f"built-in:{tool_name}",
                    "content": result_text,
                    "success": True,
                })
            continue

        # ── MCP tool execution ────────────────────────────────────────
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

    Publishes each token to the workflow stream. Falls back to the non-streaming text
    if the streaming call fails.

    Returns:
        content: str  — the full response text
    """
    from agents.models.interface import ModelTracing

    messages = args.get("messages", [])
    config = args.get("llm_config", {})
    fallback_content = args.get("fallback_content", "")
    thread_id = args.get("thread_id")
    redis_url = config.get("redis_url")
    stream_channel = config.get("stream_channel")

    heartbeat({"step": "streaming", "tokens": 0})

    full_response_content = ""
    token_count = 0

    try:
        provider, model = _agents_provider_and_model(config)
        try:
            async for event in model.stream_response(
                system_instructions=None,
                input=messages,
                model_settings=_agents_model_settings(config),
                tools=[],
                output_schema=None,
                handoffs=[],
                tracing=ModelTracing.DISABLED,
                previous_response_id=None,
                conversation_id=None,
                prompt=None,
            ):
                event_type = getattr(event, "type", None)
                if event_type in {"response.output_text.delta", "response.refusal.delta"}:
                    token = getattr(event, "delta", "")
                    if token:
                        full_response_content += token
                        token_count += 1
                        await _publish(redis_url, stream_channel, {"type": "token", "content": token})
                        if token_count % 50 == 0:
                            heartbeat({"step": "streaming", "tokens": token_count})
                elif event_type == "response.completed" and not full_response_content:
                    extracted = _extract_agents_response(event.response)
                    full_response_content = extracted.get("content") or ""
        finally:
            await _close_agents_provider(provider)
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
    that don't need MCP tools, workflow streaming, or the agent loop.

    Returns:
        content: str  — the LLM response text
    """
    messages = args.get("messages", [])
    config = args.get("llm_config", {})
    completion = await _agents_chat_completion(messages, config)
    return {"content": completion.get("content", "")}


# ═══════════════════════════════════════════════════════════════════════
#  EXISTING ACTIVITIES — unchanged
# ═══════════════════════════════════════════════════════════════════════

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
    discord_config = args.get("discord")
    async with AsyncSessionLocal() as db:
        await add_message(db, UUID(thread_id), role, content, metadata=metadata)
        await db.commit()
    from app.discord_integration import sync_message_to_discord
    await sync_message_to_discord(UUID(thread_id), role, content, metadata=metadata, discord_config=discord_config)


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
async def sync_discord_title(args: dict) -> None:
    """Update linked Discord thread name after ThreadBot auto-title generation."""
    from uuid import UUID

    thread_id = args["thread_id"]
    title = args["title"]
    discord_config = args.get("discord")
    from app.discord_integration import sync_title_to_discord
    await sync_title_to_discord(UUID(thread_id), title, discord_config=discord_config)


@defn
async def compact_history(args: dict) -> dict:
    """Compact old messages in a thread into a summary.

    Returns:
        compacted: bool
        summary: str | None
        messages: list[dict]  — new message list to send to the LLM
        compacted_count: int
    """
    messages = args["messages"]
    config = args["llm_config"]
    context_window = args.get("context_window", 8192)
    threshold = args.get("compaction_threshold", 0.75)
    preserve_recent = args.get("preserve_recent", 10)
    redis_url = config.get("redis_url")
    stream_channel = config.get("stream_channel")

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
        # Publish context usage even when no compaction
        await _publish(redis_url, stream_channel, {
            "type": "context",
            "estimated_tokens": int(estimated_tokens),
            "context_window": context_window,
        })
        return {"compacted": False, "summary": None, "messages": messages, "compacted_count": 0}

    if len(messages) <= preserve_recent:
        print("Compaction skipped: not enough messages to compact", flush=True)
        await _publish(redis_url, stream_channel, {
            "type": "context",
            "estimated_tokens": int(estimated_tokens),
            "context_window": context_window,
        })
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

    try:
        completion = await _agents_chat_completion(
            summary_prompt,
            config,
            temperature=0.3,
            max_tokens=1024,
        )
        summary = completion.get("content", "")
    except Exception as e:
        print(f"Compaction failed with exception: {e}", flush=True)
        return {"compacted": False, "summary": None, "messages": messages, "compacted_count": 0}

    if not summary:
        print("Compaction failed: summarizer returned empty content", flush=True)
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

    # Publish compaction event so the frontend shows it in the timeline
    await _publish(redis_url, stream_channel, {
        "type": "compaction",
        "content": f"Compacted {len(to_compact)} messages into a summary",
        "compacted_count": len(to_compact),
    })

    # Publish updated context usage after compaction
    post_chars = sum(len(m.get("content", "") or "") for m in new_messages)
    await _publish(redis_url, stream_channel, {
        "type": "context",
        "estimated_tokens": int(post_chars / 4),
        "context_window": context_window,
    })

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
