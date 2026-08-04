"""Dedicated connector queue entrypoint; it cannot consume interactive chat work."""
import asyncio
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
from app.config import get_settings
from app.temporal_client import connect_temporal_client
from app.workflows.agent_workflows import TriggerDispatchWorkflow
from app.activities.connector_activities import poll_connector, reconcile_phase2_dead_letters

async def run_connector_worker():
    client = await connect_temporal_client()
    worker = Worker(client, task_queue=getattr(get_settings(), "CONNECTOR_TASK_QUEUE", "threadbot-connectors"), workflows=[TriggerDispatchWorkflow], activities=[poll_connector, reconcile_phase2_dead_letters], workflow_runner=UnsandboxedWorkflowRunner())
    await worker.run()
if __name__ == "__main__": asyncio.run(run_connector_worker())
