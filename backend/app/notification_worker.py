"""Dedicated notification queue entrypoint, isolated from chat and connectors."""
import asyncio
from datetime import timedelta
from temporalio.worker import Worker, UnsandboxedWorkflowRunner
from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleIntervalSpec, ScheduleOverlapPolicy, SchedulePolicy, ScheduleSpec
from app.config import get_settings
from app.temporal_client import connect_temporal_client
from app.workflows.notification_workflow import NotificationDeliveryWorkflow, ReconcileNotificationDeliveriesWorkflow
from app.activities.notification_activities import dispatch_notification_delivery, reconcile_notification_deliveries

async def run_notification_worker():
    client = await connect_temporal_client()
    task_queue = getattr(get_settings(), "NOTIFICATION_TASK_QUEUE", "threadbot-notifications")
    try:
        await client.create_schedule(
            "notification-reconcile:periodic",
            Schedule(
                action=ScheduleActionStartWorkflow(
                    ReconcileNotificationDeliveriesWorkflow.run,
                    {"limit": 100, "task_queue": task_queue},
                    id="notification-reconcile:periodic",
                    task_queue=task_queue,
                ),
                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(minutes=1))]),
                policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
            ),
        )
    except Exception:
        pass
    worker = Worker(client, task_queue=task_queue, workflows=[NotificationDeliveryWorkflow, ReconcileNotificationDeliveriesWorkflow], activities=[dispatch_notification_delivery, reconcile_notification_deliveries], workflow_runner=UnsandboxedWorkflowRunner())
    await worker.run()
if __name__ == "__main__": asyncio.run(run_notification_worker())
