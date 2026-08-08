"""Opt-in worker for the policy-aware runtime; it never starts with chat."""
import asyncio
import contextlib
from app.config import get_settings
from app.temporal_client import connect_temporal_client
from app.workflows.policy_aware_thread_workflow import PolicyAwareThreadTurnWorkflow
from app.workflows.agent_workflows import AgentCoordinatorWorkflow, ThreadTurnCoordinatorWorkflow, AgentRunWorkflow, TriggerDispatchWorkflow
from app.workflows.heartbeat_workflow import AgentHeartbeatWorkflow
from app.activities.agent_activities import load_agent_run, persist_runtime_snapshot, project_run_terminal, recover_coordinator_queue, recover_thread_queue, route_agent_output, materialize_trigger_event, claim_event_run, mark_run_workflow, fail_run, suppress_event
from app.activities.autonomy_activities import (
    prepare_runtime, plan_model_step, persist_planned_action,
    evaluate_policy_and_reserve_budget, load_verified_approval, load_approval_state, create_approval_request,
    expire_approval_request,
    recheck_authorization, execute_authorized_action, persist_action_result,
    finalize_turn, start_runtime, transition_action_status, transition_run_status, settle_budget,
    reconcile_expired_runtimes, renew_thread_lease, release_runtime, append_progress_event,
)
from app.activities.heartbeat_activities import (
    load_heartbeat_state, materialize_heartbeat_run, complete_heartbeat_run,
    reconcile_heartbeats, evaluate_heartbeat_step,
)
from app.activities.connector_activities import reconcile_phase2_dead_letters, poll_connector
from app.workflows.phase3_workflows import HandoffSLAWorkflow
from app.activities.phase3_activities import fire_handoff_escalation, complete_handoff, acknowledge_handoff, handoff_to_agent, list_orphan_handoff_slas
import logging
logger = logging.getLogger(__name__)
from app.workflows.retention_workflow import ArtifactRetentionWorkflow
from app.activities.retention_activities import retain_expired_artifacts
from app.activities.state_activities import capture_connector_snapshot, persist_state_diff
from app.agents.temporal_schedule_service import reconcile_schedules


async def run_agent_worker():
    from temporalio.worker import UnsandboxedWorkflowRunner, Worker
    from app.database import ensure_database_schema
    settings = get_settings()
    if not getattr(settings, "AUTONOMY_ENABLED", False):
        raise RuntimeError("autonomy worker is disabled; set AUTONOMY_ENABLED=true")
    await ensure_database_schema()
    await reconcile_expired_runtimes({"limit": 100})
    client = await connect_temporal_client()
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent_models import AgentTrigger
    async with AsyncSessionLocal() as db:
        triggers=list((await db.execute(select(AgentTrigger))).scalars().all())
    await reconcile_schedules(client,triggers)
    worker = Worker(client, task_queue=getattr(settings, "AGENT_TASK_QUEUE", "threadbot-agent"), workflows=[PolicyAwareThreadTurnWorkflow, AgentCoordinatorWorkflow, ThreadTurnCoordinatorWorkflow, AgentRunWorkflow, TriggerDispatchWorkflow, HandoffSLAWorkflow, ArtifactRetentionWorkflow, AgentHeartbeatWorkflow], activities=[prepare_runtime, plan_model_step, persist_planned_action, evaluate_policy_and_reserve_budget, load_verified_approval, load_approval_state, create_approval_request, expire_approval_request, recheck_authorization, execute_authorized_action, persist_action_result, finalize_turn, start_runtime, transition_action_status, transition_run_status, settle_budget, reconcile_expired_runtimes, renew_thread_lease, release_runtime, append_progress_event, load_agent_run, persist_runtime_snapshot, project_run_terminal, recover_coordinator_queue, recover_thread_queue, route_agent_output, materialize_trigger_event, claim_event_run, mark_run_workflow, fail_run, suppress_event, reconcile_phase2_dead_letters, poll_connector, capture_connector_snapshot, persist_state_diff, fire_handoff_escalation, complete_handoff, acknowledge_handoff, handoff_to_agent, list_orphan_handoff_slas, retain_expired_artifacts, load_heartbeat_state, materialize_heartbeat_run, complete_heartbeat_run, reconcile_heartbeats, evaluate_heartbeat_step], workflow_runner=UnsandboxedWorkflowRunner())

    async def reconcile_loop():
        while True:
            await asyncio.sleep(60)
            try:
                await reconcile_expired_runtimes({"limit": 100})
            except Exception as exc:
                print(f"Autonomy reconciliation failed: {exc}")

    async def schedule_loop():
        while True:
            await asyncio.sleep(300)
            try:
                await client.start_workflow(ArtifactRetentionWorkflow.run, {"limit": 500}, id="artifact-retention:periodic", task_queue=getattr(settings, "AGENT_TASK_QUEUE", "threadbot-agent"))
            except Exception as exc:
                logger.debug("retention workflow already running or unavailable: %s", exc)
            try:
                orphaned = await list_orphan_handoff_slas({"limit": 100})
                for item in orphaned:
                    await client.start_workflow(HandoffSLAWorkflow.run, item, id=f"handoff-sla:{item['handoff_id']}", task_queue=getattr(settings, "AGENT_TASK_QUEUE", "threadbot-agent"))
            except Exception as exc:
                logger.warning("handoff SLA reconciliation failed: %s", exc)
            try:
                async with AsyncSessionLocal() as db:
                    triggers=list((await db.execute(select(AgentTrigger))).scalars().all())
                await reconcile_schedules(client,triggers)
            except Exception as exc:
                logger.warning("schedule reconciliation failed: %s", exc)
            try:
                await reconcile_heartbeats({"limit": 100})
            except Exception as exc:
                logger.warning("heartbeat reconciliation failed: %s", exc)

    reconciliation = asyncio.create_task(reconcile_loop())
    schedules = asyncio.create_task(schedule_loop())
    try:
        await worker.run()
    finally:
        reconciliation.cancel()
        schedules.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await reconciliation
        with contextlib.suppress(asyncio.CancelledError):
            await schedules


if __name__ == "__main__":
    asyncio.run(run_agent_worker())
