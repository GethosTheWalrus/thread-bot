from temporalio.workflow import defn, execute_activity, init, run
from temporalio.common import RetryPolicy
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.contrib.workflow_streams import WorkflowStream

with workflow.unsafe.imports_passed_through():
    import annotated_types  # noqa: F401
    import pydantic_core  # noqa: F401
    import pydantic_core.core_schema  # noqa: F401
    from agents import Agent, FunctionTool, ModelSettings, Runner


@defn
class RunThreadWorkflow:
    """Main workflow for handling a chat interaction.

    Orchestrates a chat interaction as Temporal activities:
      get_messages → compact_history → discover_tools →
      OpenAI Agents SDK streamed run → save_message → auto-title → done event

    Each step is visible as a separate activity in the Temporal UI,
    with independent timeouts, retry policies, and heartbeat details.
    """

    @init
    def __init__(self, input: dict) -> None:
        self._stream = WorkflowStream()
        self._events = self._stream.topic("events", type=dict)

    def _agents_tools(
        self,
        openai_tools: list[dict],
        mcp_tools_map: dict,
        thread_id: str,
        llm_config: dict,
    ) -> list:
        tools = []
        for tool_def in openai_tools:
            fn = tool_def.get("function", {})
            tool_name = fn.get("name", "")

            async def invoke_tool(ctx, args: str, *, name=tool_name) -> str:
                return await execute_activity(
                    "execute_agent_tool_activity",
                    {
                        "tool_name": name,
                        "arguments": args or "{}",
                        "tool_call_id": ctx.tool_call_id,
                        "mcp_tools_map": mcp_tools_map,
                        "thread_id": thread_id,
                        "llm_config": llm_config,
                    },
                    start_to_close_timeout=timedelta(seconds=300),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                    heartbeat_timeout=timedelta(seconds=120),
                    summary=f"Run tool {name}",
                )

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

    def _agents_input(self, messages: list[dict]) -> list[dict]:
        """Convert OpenAI chat history into Agents SDK input items."""
        result = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role in {"system", "user"} and content:
                result.append({"role": role, "content": content})
            elif role == "assistant":
                if content:
                    result.append({"role": "assistant", "content": content})
                elif msg.get("tool_calls"):
                    names = [
                        tc.get("function", {}).get("name", "unknown")
                        for tc in msg.get("tool_calls", [])
                    ]
                    result.append({
                        "role": "assistant",
                        "content": "Called tools: " + ", ".join(names),
                    })
            elif role == "tool" and content:
                name = msg.get("name") or msg.get("tool_call_id") or "tool"
                result.append({
                    "role": "user",
                    "content": f"Tool result from {name}:\n{content}",
                })

        return result

    async def _publish_event(self, llm_config: dict, event: Any) -> None:
        if isinstance(event, dict):
            self._events.publish(event)

    async def _publish_final_response(self, llm_config: dict, content: str) -> None:
        chunk_size = int(llm_config.get("stream_batch_chars", 32) or 32)
        for start in range(0, len(content), chunk_size):
            await self._publish_event(
                llm_config,
                {"type": "token", "content": content[start:start + chunk_size]},
            )

    def _estimate_context_tokens(self, messages: list[dict]) -> int:
        total_chars = 0
        for message in messages:
            if message.get("role") == "thinking":
                continue
            total_chars += len(message.get("content") or "")
        return int(total_chars / 4)

    @run
    async def run(self, input: dict) -> dict:
        with workflow.unsafe.imports_passed_through():
            from app.activities.llm_activities import (
                generate_title, save_message, get_messages, update_title,
                compact_history, delete_messages_before, discover_tools,
                sync_discord_title,
            )
        thread_id = input["thread_id"]
        message = input["message"]
        llm_config = input.get("llm_config", {})

        try:
            # ── Get chat history ─────────────────────────────────────────
            chat_history = await execute_activity(
                get_messages,
                thread_id,
                start_to_close_timeout=timedelta(seconds=10),
            )

            # ── Compaction Check ─────────────────────────────────────────
            compact_result = await execute_activity(
                compact_history,
                {
                    "thread_id": thread_id,
                    "llm_config": llm_config,
                    "messages": chat_history,
                    "context_window": llm_config.get("context_window", 8192),
                    "compaction_threshold": llm_config.get("compaction_threshold", 0.75),
                    "preserve_recent": llm_config.get("preserve_recent", 10),
                },
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

            if compact_result["compacted"]:
                import datetime
                compacted_at = datetime.datetime.utcnow().isoformat()
                await execute_activity(
                    save_message,
                    {
                        "thread_id": thread_id,
                        "role": "system",
                        "content": compact_result["summary"],
                        "metadata": {
                            "type": "compaction_summary",
                            "compacted_at": compacted_at,
                            "original_message_count": compact_result["compacted_count"],
                        },
                    },
                    start_to_close_timeout=timedelta(seconds=10),
                )
                await execute_activity(
                    delete_messages_before,
                    {
                        "thread_id": thread_id,
                        "keep_recent": llm_config.get("preserve_recent", 10),
                    },
                    start_to_close_timeout=timedelta(seconds=15),
                )
                chat_history = compact_result["messages"]

            # ── Discover MCP Tools ───────────────────────────────────────
            tool_overrides = llm_config.get("tool_overrides", [])
            tools_result = await execute_activity(
                discover_tools,
                {
                    "thread_id": thread_id,
                    "tool_overrides": tool_overrides,
                },
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=2),
                heartbeat_timeout=timedelta(seconds=60),
            )

            mcp_tools_map = tools_result["mcp_tools_map"]
            openai_tools = tools_result["openai_tools"]

            # ── Built-in tools (no MCP container required) ───────────────
            builtin_tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "continue_thinking",
                        "description": (
                            "Use this tool when you need more time to reason, reflect on tool results, "
                            "or plan your next steps before giving a final answer. Call this tool with "
                            "your current reasoning and the loop will continue, allowing you to make "
                            "additional tool calls or think further."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "reasoning": {
                                    "type": "string",
                                    "description": "Your current reasoning, reflections, or plan for next steps.",
                                },
                            },
                            "required": ["reasoning"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "web_fetch",
                        "description": (
                            "Fetch the content of a web page or API endpoint and return it as text. "
                            "Use this to read documentation, articles, API responses, or any public URL. "
                            "By default, returns a paginated window of the page content. Use start_index "
                            "and max_chars to paginate through large pages. To find specific information, "
                            "pass query to search the whole fetched page and return matched snippets. "
                            "The query is a literal substring search by default, not a search-engine query: "
                            "do not use OR, AND, quotes, or multiple alternatives unless use_regex is true. "
                            "Set use_regex=true when you need regex alternation, optional text, or flexible "
                            "matching such as enhanced.*seed|1/400."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "url": {
                                    "type": "string",
                                    "description": "The full URL to fetch (must start with http:// or https://).",
                                },
                                "start_index": {
                                    "type": "integer",
                                    "description": "Character offset to start reading from. Defaults to 0.",
                                },
                                "max_chars": {
                                    "type": "integer",
                                    "description": "Maximum number of characters to return. Defaults to 5000.",
                                },
                                "query": {
                                    "type": "string",
                                    "description": "Optional search query for the full fetched page. By default this is a literal substring or exact phrase, not a search-engine query. Set use_regex=true to interpret it as a Python regular expression for alternation or flexible matching. If provided, returns snippets around matches instead of a paginated window.",
                                },
                                "use_regex": {
                                    "type": "boolean",
                                    "description": "When true, interpret query as a Python regular expression. Use this for alternatives like enhanced crystal weapon seed|1/400, optional whitespace, or flexible text between words. Defaults to false.",
                                },
                                "context_chars": {
                                    "type": "integer",
                                    "description": "Characters of surrounding context to include before and after each query match. Defaults to 800.",
                                },
                                "max_matches": {
                                    "type": "integer",
                                    "description": "Maximum number of query matches to return. Defaults to 5.",
                                },
                                "case_sensitive": {
                                    "type": "boolean",
                                    "description": "Whether query matching is case-sensitive. Defaults to false.",
                                },
                            },
                            "required": ["url"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "current_datetime",
                        "description": (
                            "Returns the current date, time, and timezone. Use this whenever you need "
                            "to know the current time, today's date, or the day of the week."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {},
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "description": (
                            "Evaluate a mathematical expression and return the result. Supports "
                            "arithmetic (+, -, *, /, **), parentheses, and common math functions "
                            "(sqrt, sin, cos, tan, log, log10, abs, round, ceil, floor, pi, e). "
                            "Use this instead of doing mental math."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "expression": {
                                    "type": "string",
                                    "description": "The math expression to evaluate, e.g. '(3.14 * 5**2) / 2'.",
                                },
                            },
                            "required": ["expression"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "json_parse",
                        "description": (
                            "Parse a JSON string and extract a value at a specific key path. "
                            "Use this to drill into large JSON responses from other tools instead of "
                            "pasting the entire JSON into your context. "
                            "The key path uses dot notation (e.g. 'data.items.0.name')."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "json_string": {
                                    "type": "string",
                                    "description": "The JSON string to parse.",
                                },
                                "key_path": {
                                    "type": "string",
                                    "description": "Dot-separated path to extract, e.g. 'results.0.title'. Omit or use empty string to return the full parsed structure.",
                                },
                            },
                            "required": ["json_string"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "text_count",
                        "description": (
                            "Count words, characters, lines, or sentences in a given text. "
                            "Use this when you need precise counts instead of estimating."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "text": {
                                    "type": "string",
                                    "description": "The text to analyze.",
                                },
                                "unit": {
                                    "type": "string",
                                    "enum": ["words", "characters", "lines", "sentences"],
                                    "description": "What to count. Defaults to 'words'.",
                                },
                            },
                            "required": ["text"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "base64_decode",
                        "description": (
                            "Decode a base64-encoded string to plain text. "
                            "Use this for encoded API responses, JWT payloads, or other base64 data."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "encoded": {
                                    "type": "string",
                                    "description": "The base64-encoded string to decode.",
                                },
                            },
                            "required": ["encoded"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "base64_encode",
                        "description": (
                            "Encode a plain text string to base64. "
                            "Use this when you need to encode data for APIs, headers, or other purposes."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "text": {
                                    "type": "string",
                                    "description": "The plain text string to encode.",
                                },
                            },
                            "required": ["text"],
                        },
                    },
                },
            ]
            openai_tools.extend(builtin_tools)

            # ── Build initial message list ───────────────────────────────
            current_messages = list(chat_history)

            # Inject system message when tools are available
            if openai_tools and (not current_messages or current_messages[0].get("role") != "system"):
                current_messages.insert(0, {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant with access to tools. "
                        "Use tools as many times as needed to thoroughly answer the user's question. "
                        "Gather information, verify it, and refine your answer "
                        "before providing a final response. You may call multiple tools in sequence."
                    ),
                })

            # ── Agent Run ────────────────────────────────────────────────
            # The OpenAI Agents SDK owns the loop. Its model calls are routed
            # through Temporal's OpenAIAgentsPlugin as InvokeModel activities,
            # and each ThreadBot tool invocation is a Temporal activity.
            agent = Agent(
                name="ThreadBot",
                instructions=(
                    "You are a helpful assistant. Use tools as many times as needed to thoroughly "
                    "answer the user's question. Gather information and verify it before providing "
                    "a concise final response."
                ),
                model=llm_config.get("model"),
                model_settings=ModelSettings(
                    temperature=llm_config.get("temperature", 0.7),
                    max_tokens=llm_config.get("max_tokens", 2048),
                    include_usage=True,
                ),
                tools=self._agents_tools(openai_tools, mcp_tools_map, thread_id, llm_config),
            )

            result = Runner.run_streamed(
                agent,
                input=self._agents_input(current_messages),
                max_turns=llm_config.get("max_iterations", 25),
            )
            streamed_content = ""
            async for event in result.stream_events():
                if event.type == "raw_response_event":
                    raw = event.data
                    raw_type = getattr(raw, "type", None)
                    if raw_type in {"response.output_text.delta", "response.refusal.delta"}:
                        token = getattr(raw, "delta", "")
                        if token:
                            streamed_content += token
                    elif raw_type == "response.completed":
                        pass

            llm_response = str(result.final_output or streamed_content or "(Agent completed without a response.)")
            if llm_response and not streamed_content:
                await self._publish_final_response(llm_config, llm_response)

            # ── Save final assistant response ────────────────────────────
            await execute_activity(
                save_message,
                {
                    "thread_id": thread_id,
                    "role": "assistant",
                    "content": llm_response,
                    "discord": llm_config.get("discord"),
                },
                start_to_close_timeout=timedelta(seconds=10),
            )

            retained_messages = await execute_activity(
                get_messages,
                thread_id,
                start_to_close_timeout=timedelta(seconds=10),
            )
            await self._publish_event(llm_config, {
                "type": "context",
                "estimated_tokens": self._estimate_context_tokens(retained_messages),
                "context_window": llm_config.get("context_window", 8192),
            })
            if len(chat_history) <= 5 or len(chat_history) % 5 == 1:
                # Auto-title runs in the background so the user-visible
                # `done` event is not delayed by it. The title event
                # arrives later when the background task finishes.
                self._kick_off_title(
                    thread_id=thread_id,
                    chat_history=chat_history,
                    llm_config=llm_config,
                )

            await self._publish_event(llm_config, {"type": "done"})

            return {
                "thread_id": thread_id,
                "response": llm_response,
            }

        except Exception as e:
            await self._publish_event(llm_config, {"type": "error", "content": str(e)})

    def _kick_off_title(self, thread_id: str, chat_history: list, llm_config: dict) -> None:
        """Schedule auto-title generation in the background.

        Runs the LLM call, persists the title, syncs it to Discord, and
        publishes the `title` event. Failures are logged but do not
        affect the workflow result.
        """
        import asyncio

        async def _run():
            with workflow.unsafe.imports_passed_through():
                from app.activities.llm_activities import (
                    generate_title, update_title, sync_discord_title,
                )

            readable = [
                m for m in chat_history[-5:]
                if m.get("content") and m.get("role") in ("user", "assistant")
            ]
            context = "\n".join([f"{m['role']}: {m['content']}" for m in readable])
            title_prompt = (
                "Generate a very short, catchy title for this conversation (max 4 words). "
                "Reply with ONLY the title, no quotes, no labels. Context:\n" + context
            )
            title_config = llm_config.copy()
            try:
                title = await execute_activity(
                    generate_title,
                    {"messages": [{"role": "user", "content": title_prompt}], "llm_config": title_config},
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except Exception as exc:
                print(f"[title] generate_title failed: {exc}", flush=True)
                return
            title_text = title["content"] if isinstance(title, dict) else title
            title_text = (title_text or "").strip("\"'").strip()[:50]
            if not title_text:
                return
            try:
                await execute_activity(
                    update_title,
                    {"thread_id": thread_id, "title": title_text},
                    start_to_close_timeout=timedelta(seconds=10),
                )
            except Exception as exc:
                print(f"[title] update_title failed: {exc}", flush=True)
            try:
                await execute_activity(
                    sync_discord_title,
                    {
                        "thread_id": thread_id,
                        "title": title_text,
                        "discord": llm_config.get("discord"),
                    },
                    start_to_close_timeout=timedelta(seconds=20),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
            except Exception as exc:
                print(f"[title] sync_discord_title failed: {exc}", flush=True)
            try:
                await self._publish_event(llm_config, {"type": "title", "content": title_text})
            except Exception as exc:
                print(f"[title] publish title failed: {exc}", flush=True)

        asyncio.create_task(_run())
