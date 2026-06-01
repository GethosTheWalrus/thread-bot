from temporalio.worker import Worker
from app.config import get_settings
from app.workflows.thread_workflow import RunThreadWorkflow
from app.activities.llm_activities import (
    generate_title, save_message, get_messages, update_title,
    compact_history, delete_messages_before, publish_done,
    publish_title, discover_tools, llm_turn, execute_tools,
    stream_response, publish_error, sync_discord_title,
)


async def run_worker():
    settings = get_settings()
    from app.database import ensure_database_schema
    from app.config import load_settings_from_db
    await ensure_database_schema()
    await load_settings_from_db()

    from app.temporal_client import connect_temporal_client
    client = await connect_temporal_client()

    from temporalio.worker import UnsandboxedWorkflowRunner

    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[RunThreadWorkflow],
        activities=[
            generate_title,
            save_message,
            get_messages,
            update_title,
            sync_discord_title,
            compact_history,
            delete_messages_before,
            publish_done,
            publish_title,
            discover_tools,
            llm_turn,
            execute_tools,
            stream_response,
            publish_error,
        ],
        workflow_runner=UnsandboxedWorkflowRunner(),
    )

    print(f"Starting worker on task queue: {settings.TEMPORAL_TASK_QUEUE}")
    await worker.run()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_worker())
