from temporalio.workflow import defn, execute_activity, run
from datetime import timedelta


@defn
class RunThreadWorkflow:
    """Main workflow for handling a chat interaction."""

    @run
    async def run(self, input: dict) -> dict:
        from temporalio import workflow
        with workflow.unsafe.imports_passed_through():
            from app.activities.llm_activities import (
                call_llm, save_message, get_messages, update_title,
                compact_history, delete_messages_before, publish_done,
                publish_title
            )
        thread_id = input["thread_id"]
        message = input["message"]
        llm_config = input.get("llm_config", {})

        # Get chat history (includes user message already saved by the route)
        chat_history = await execute_activity(
            get_messages,
            thread_id,
            start_to_close_timeout=timedelta(seconds=10),
        )

        from temporalio.common import RetryPolicy

        # ── Compaction Check ──────────────────────────────────────────
        # Build a config for the compaction LLM call that doesn't stream
        compaction_config = {k: v for k, v in llm_config.items() if k not in ("stream_url", "redis_url", "stream_channel")}

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
            from temporalio import workflow
            # Save the compaction summary as a system message in the DB
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
            # Delete the now-compacted messages from the DB
            await execute_activity(
                delete_messages_before,
                {
                    "thread_id": thread_id,
                    "keep_recent": llm_config.get("preserve_recent", 10),
                },
                start_to_close_timeout=timedelta(seconds=15),
            )
            # Use the compacted (summarised + recent) message list
            chat_history = compact_result["messages"]

        # ── Call LLM ─────────────────────────────────────────────────
        llm_result = await execute_activity(
            call_llm,
            {"messages": chat_history, "llm_config": llm_config, "thread_id": thread_id},
            start_to_close_timeout=timedelta(seconds=600),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        llm_response = llm_result["content"]

        # ── Save final assistant response ────────────────────────────
        # (intermediate tool_call/tool_result/thinking already saved inline by call_llm)
        await execute_activity(
            save_message,
            {"thread_id": thread_id, "role": "assistant", "content": llm_response},
            start_to_close_timeout=timedelta(seconds=10),
        )

        # ── Auto-title (runs before [DONE] so the frontend gets the title in the stream) ──
        if len(chat_history) <= 5 or len(chat_history) % 5 == 1:
            # Build context from recent human-readable messages only
            readable = [m for m in chat_history[-5:] if m.get("content") and m.get("role") in ("user", "assistant")]
            context = "\n".join([f"{m['role']}: {m['content']}" for m in readable])
            title_prompt = (
                "Generate a very short, catchy title for this conversation (max 4 words). "
                "Reply with ONLY the title, no quotes, no labels. Context:\n" + context
            )

            title_config = compaction_config.copy()

            title = await execute_activity(
                call_llm,
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
            # Publish title event to Redis so frontend sidebar updates immediately
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
            },
            start_to_close_timeout=timedelta(seconds=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        return {
            "thread_id": thread_id,
            "response": llm_response,
        }
