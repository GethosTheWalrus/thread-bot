from datetime import timedelta
from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from app.activities.notification_activities import dispatch_notification_delivery, reconcile_notification_deliveries


@workflow.defn
class NotificationDeliveryWorkflow:
    @workflow.run
    async def run(self, args):
        return await workflow.execute_activity(dispatch_notification_delivery, args, start_to_close_timeout=timedelta(seconds=30))


@workflow.defn
class ReconcileNotificationDeliveriesWorkflow:
    @workflow.run
    async def run(self, args):
        result = await workflow.execute_activity(reconcile_notification_deliveries, args or {}, start_to_close_timeout=timedelta(seconds=60))
        for delivery_id in result.get("delivery_ids", []):
            await workflow.execute_child_workflow(
                NotificationDeliveryWorkflow.run,
                {"delivery_id": delivery_id, "mode": "autonomous"},
                id=f"notification:{delivery_id}:reconcile",
                task_queue=args.get("task_queue", "threadbot-notifications") if isinstance(args, dict) else "threadbot-notifications",
            )
        return result
