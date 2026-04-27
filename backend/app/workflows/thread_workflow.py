from temporalio.workflow import defn, execute_activity, run
from datetime import timedelta


@defn
class RunThreadWorkflow:
    """Main workflow for handling a chat interaction."""

    @run
    async def run(self, input: dict) -> dict:
        from app.activities.llm_activities import call_llm, save_message, get_messages, update_title

        thread_id = input["thread_id"]
        message = input["message"]
        llm_config = input.get("llm_config", {})

        # Get chat history (includes user message already saved by the route)
        chat_history = await execute_activity(
            get_messages,
            thread_id,
            start_to_close_timeout=timedelta(seconds=10),
        )

        # Call LLM with config overrides
        llm_response = await execute_activity(
            call_llm,
            {"messages": chat_history, "llm_config": llm_config},
            start_to_close_timeout=timedelta(seconds=120),
        )

        # Auto-title on first message
        if len(chat_history) == 1:
            await execute_activity(
                update_title,
                {"thread_id": thread_id, "title": message[:50]},
                start_to_close_timeout=timedelta(seconds=10),
            )

        # Save assistant response
        await execute_activity(
            save_message,
            {"thread_id": thread_id, "role": "assistant", "content": llm_response},
            start_to_close_timeout=timedelta(seconds=10),
        )

        return {
            "thread_id": thread_id,
            "response": llm_response,
        }
