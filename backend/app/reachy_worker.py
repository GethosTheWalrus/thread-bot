"""Local Temporal worker for Reachy Mini hardware activities and speech."""

from __future__ import annotations

import asyncio

from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from app.activities.reachy_activities import execute_reachy_tool_activity, play_reachy_mood, speak_reachy_text
from app.config import get_reachy_config, get_settings, load_settings_from_db
from app.temporal_client import build_worker_versioning_config, connect_temporal_client
from app.workflows.reachy_speech_workflow import ReachySpeechWorkflow


async def run_worker() -> None:
    for attempt in range(1, 11):
        try:
            await load_settings_from_db()
            break
        except Exception:
            if attempt == 10:
                raise
            await asyncio.sleep(2)

    settings = get_settings()
    reachy_config = get_reachy_config()
    task_queue = reachy_config.get("task_queue") or "reachy-local"
    client = await connect_temporal_client()

    worker_kwargs = {}
    worker_deployment_config = build_worker_versioning_config()
    if worker_deployment_config is not None:
        worker_kwargs["deployment_config"] = worker_deployment_config

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[ReachySpeechWorkflow],
        activities=[execute_reachy_tool_activity, play_reachy_mood, speak_reachy_text],
        workflow_runner=UnsandboxedWorkflowRunner(),
        **worker_kwargs,
    )
    print(f"Starting Reachy worker on task queue: {task_queue} (namespace {settings.TEMPORAL_NAMESPACE})")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
