"""Local Temporal worker for Reachy Mini hardware activities and speech."""

from __future__ import annotations

import asyncio
import argparse

from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from app.activities.reachy_activities import (
    execute_reachy_tool_activity,
    play_reachy_animation,
    play_reachy_mood,
    speak_reachy_text,
)
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
        activities=[execute_reachy_tool_activity, play_reachy_animation, play_reachy_mood, speak_reachy_text],
        workflow_runner=UnsandboxedWorkflowRunner(),
        **worker_kwargs,
    )
    print(f"Starting Reachy worker on task queue: {task_queue} (namespace {settings.TEMPORAL_NAMESPACE})")
    await worker.run()


async def test_camera() -> None:
    for attempt in range(1, 11):
        try:
            await load_settings_from_db()
            break
        except Exception:
            if attempt == 10:
                raise
            await asyncio.sleep(2)

    from app.reachy_client import camera_diagnostics, capture_image_base64

    reachy_config = get_reachy_config()
    print(f"[reachy-camera-test] diagnostics before capture: {camera_diagnostics(reachy_config)}", flush=True)
    image_base64, content_type = await asyncio.to_thread(capture_image_base64, reachy_config)
    print(
        f"[reachy-camera-test] captured {content_type}; base64 chars={len(image_base64)}",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the local Reachy Temporal worker.")
    parser.add_argument("--camera-test", action="store_true", help="Test local Reachy camera capture and exit.")
    args = parser.parse_args()
    asyncio.run(test_camera() if args.camera_test else run_worker())
