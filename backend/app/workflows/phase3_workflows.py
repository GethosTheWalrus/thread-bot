from datetime import timedelta
import asyncio
from temporalio import workflow
with workflow.unsafe.imports_passed_through():
    from app.activities.phase3_activities import fire_handoff_escalation, complete_handoff, acknowledge_handoff

@workflow.defn
class HandoffSLAWorkflow:
    def __init__(self): self.acknowledged = False; self.completed = False
    @workflow.signal
    async def acknowledge(self): self.acknowledged = True
    @workflow.signal
    async def complete(self, payload=None): self.completed = True
    @workflow.run
    async def run(self, args):
        from datetime import datetime, timezone
        ack_deadline = datetime.fromisoformat(args["acknowledgement_deadline"]); complete_deadline = datetime.fromisoformat(args["completion_deadline"])
        ack_seconds = max(0, int((ack_deadline - workflow.now()).total_seconds()))
        try:
            acked = await workflow.wait_condition(lambda: self.acknowledged, timeout=timedelta(seconds=ack_seconds))
        except asyncio.TimeoutError:
            acked = False
        if not acked:
            await workflow.execute_activity(fire_handoff_escalation, {**args, "stage": "acknowledgement", "target_type": args.get("ack_target_type", "human"), "target_id": args.get("ack_target_id", "owner")}, start_to_close_timeout=timedelta(seconds=30))
        else:
            await workflow.execute_activity(acknowledge_handoff, args, start_to_close_timeout=timedelta(seconds=30))
        remaining = max(0, int((complete_deadline - workflow.now()).total_seconds()))
        try:
            done = await workflow.wait_condition(lambda: self.completed, timeout=timedelta(seconds=remaining))
        except asyncio.TimeoutError:
            done = False
        if not done:
            await workflow.execute_activity(fire_handoff_escalation, {**args, "stage": "completion", "target_type": args.get("completion_target_type", "human"), "target_id": args.get("completion_target_id", "owner")}, start_to_close_timeout=timedelta(seconds=30))
            return await workflow.execute_activity(complete_handoff, {**args, "status": "timed_out"}, start_to_close_timeout=timedelta(seconds=30))
        return await workflow.execute_activity(complete_handoff, {**args, "status": "completed"}, start_to_close_timeout=timedelta(seconds=30))
