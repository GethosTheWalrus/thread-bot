from temporalio.workflow import defn, execute_activity, run
from temporalio.common import RetryPolicy
from datetime import timedelta


@defn
class RunThreadWorkflow:
    """Main workflow for handling a chat interaction.

    Orchestrates the agent loop as discrete Temporal activities:
      get_messages → compact_history → discover_tools →
      loop { llm_turn → execute_tools } → stream_response →
      save_message → auto-title → publish_done

    Each step is visible as a separate activity in the Temporal UI,
    with independent timeouts, retry policies, and heartbeat details.
    """

    @run
    async def run(self, input: dict) -> dict:
        from temporalio import workflow
        with workflow.unsafe.imports_passed_through():
            from app.activities.llm_activities import (
                generate_title, save_message, get_messages, update_title,
                compact_history, delete_messages_before, publish_done,
                publish_title, discover_tools, llm_turn, execute_tools,
                stream_response,
            )
        thread_id = input["thread_id"]
        message = input["message"]
        llm_config = input.get("llm_config", {})

        # ── Get chat history ─────────────────────────────────────────
        chat_history = await execute_activity(
            get_messages,
            thread_id,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # ── Compaction Check ─────────────────────────────────────────
        compaction_config = {
            k: v for k, v in llm_config.items()
            if k not in ("stream_url", "redis_url", "stream_channel")
        }

        compact_result = await execute_activity(
            compact_history,
            {
                "thread_id": thread_id,
                "llm_config": compaction_config,
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

        # ── Build initial message list ───────────────────────────────
        current_messages = list(chat_history)

        # Inject system message when tools are available
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

        # ── Agent Loop ───────────────────────────────────────────────
        max_iterations = llm_config.get("max_iterations", 25)
        llm_response = ""
        used_tools = False

        for iteration in range(1, max_iterations + 1):
            # Single LLM call
            turn_result = await execute_activity(
                llm_turn,
                {
                    "messages": current_messages,
                    "llm_config": llm_config,
                    "thread_id": thread_id,
                    "openai_tools": openai_tools,
                    "iteration": iteration,
                    "max_iterations": max_iterations,
                },
                start_to_close_timeout=timedelta(seconds=300),
                retry_policy=RetryPolicy(maximum_attempts=1),
                heartbeat_timeout=timedelta(seconds=120),
            )

            if turn_result["has_tool_calls"]:
                used_tools = True

                # Append the assistant message with tool_calls to context
                current_messages.append(turn_result["llm_message"])

                # Execute all tool calls
                exec_result = await execute_activity(
                    execute_tools,
                    {
                        "tool_calls": turn_result["tool_calls"],
                        "mcp_tools_map": mcp_tools_map,
                        "thread_id": thread_id,
                        "llm_config": llm_config,
                        "llm_message": turn_result["llm_message"],
                        "iteration": iteration,
                    },
                    start_to_close_timeout=timedelta(seconds=300),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                    heartbeat_timeout=timedelta(seconds=120),
                )

                # Append tool results to context for next LLM turn
                current_messages.extend(exec_result["tool_messages"])
                continue
            else:
                # Final response — stream it token by token
                stream_result = await execute_activity(
                    stream_response,
                    {
                        "messages": current_messages,
                        "llm_config": llm_config,
                        "fallback_content": turn_result["text_content"] or "",
                    },
                    start_to_close_timeout=timedelta(seconds=600),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                    heartbeat_timeout=timedelta(seconds=120),
                )

                llm_response = stream_result["content"]
                break
        else:
            # Safety exit — max iterations reached
            if not llm_response:
                llm_response = "(Agent reached maximum iteration limit.)"

        # ── Save final assistant response ────────────────────────────
        await execute_activity(
            save_message,
            {"thread_id": thread_id, "role": "assistant", "content": llm_response},
            start_to_close_timeout=timedelta(seconds=10),
        )

        # ── Auto-title ───────────────────────────────────────────────
        if len(chat_history) <= 5 or len(chat_history) % 5 == 1:
            readable = [
                m for m in chat_history[-5:]
                if m.get("content") and m.get("role") in ("user", "assistant")
            ]
            context = "\n".join([f"{m['role']}: {m['content']}" for m in readable])
            title_prompt = (
                "Generate a very short, catchy title for this conversation (max 4 words). "
                "Reply with ONLY the title, no quotes, no labels. Context:\n" + context
            )

            title_config = compaction_config.copy()

            title = await execute_activity(
                generate_title,
                {"messages": [{"role": "user", "content": title_prompt}], "llm_config": title_config},
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            title_text = title["content"] if isinstance(title, dict) else title
            title_text = title_text.strip("\"'").strip()[:50]
            await execute_activity(
                update_title,
                {"thread_id": thread_id, "title": title_text},
                start_to_close_timeout=timedelta(seconds=10),
            )
            await execute_activity(
                publish_title,
                {
                    "redis_url": llm_config.get("redis_url"),
                    "stream_channel": llm_config.get("stream_channel"),
                    "title": title_text,
                },
                start_to_close_timeout=timedelta(seconds=5),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )

        # ── Signal frontend: all messages persisted ──────────────────
        await execute_activity(
            publish_done,
            {
                "redis_url": llm_config.get("redis_url"),
                "stream_channel": llm_config.get("stream_channel"),
                "thread_id": thread_id,
            },
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        return {
            "thread_id": thread_id,
            "response": llm_response,
        }
