import asyncio

from temporalio.worker import Worker
from datetime import timedelta
from app.agents_provider import build_agents_model_provider
from app.config import get_llm_config, get_settings, load_settings_from_db
from app.workflows.thread_workflow import RunThreadWorkflow
from app.activities.llm_activities import (
    generate_title, save_message, get_messages, update_title,
    compact_history, delete_messages_before, discover_tools,
    execute_agent_tool_activity, sync_discord_title, claim_discord_event,
    generate_and_update_title,
)
from temporalio.contrib.openai_agents import ModelActivityParameters, OpenAIAgentsPlugin
from app.temporal_client import connect_temporal_client


async def run_worker():
    settings = get_settings()
    for attempt in range(1, 11):
        try:
            await load_settings_from_db()
            break
        except Exception:
            if attempt == 10:
                raise
            await asyncio.sleep(2)
    llm_config = get_llm_config()

    plugin = OpenAIAgentsPlugin(
        model_params=ModelActivityParameters(
            start_to_close_timeout=timedelta(seconds=llm_config.get("stream_timeout", 600)),
            heartbeat_timeout=timedelta(seconds=120),
            streaming_topic="threadbot-model-events",
            streaming_batch_interval=timedelta(milliseconds=100),
        ),
        model_provider=build_agents_model_provider(llm_config),
    )

    client = await connect_temporal_client(plugins=[plugin])


    from temporalio.worker import UnsandboxedWorkflowRunner

    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[RunThreadWorkflow],
        activities=[
            generate_title,
            generate_and_update_title,
            save_message,
            get_messages,
            update_title,
            sync_discord_title,
            compact_history,
            delete_messages_before,
            discover_tools,
            execute_agent_tool_activity,
            claim_discord_event,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    )

    print(f"Starting worker on task queue: {settings.TEMPORAL_TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
