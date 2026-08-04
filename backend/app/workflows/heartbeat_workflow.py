"""Durable adaptive heartbeat supervisor for an agent.

One workflow per agent (`agent-heartbeat:{agent_id}`).  Loads desired state
from PostgreSQL, waits until next_wake (interruptible by signals),
materializes a heartbeat run without a synthetic user message, enqueues it
through the existing ThreadTurnCoordinatorWorkflow, waits for completion, then
reconciles and continues.  The workflow itself never performs model calls,
DB access, or external effects; it only schedules activities.
"""
from datetime import timedelta, datetime
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.activities.heartbeat_activities import (
        load_heartbeat_state,
        materialize_heartbeat_run,
        complete_heartbeat_run,
    )
    from app.activities.agent_activities import recover_thread_queue


@workflow.defn
class AgentHeartbeatWorkflow:
    """Per-agent adaptive wake supervisor."""

    def __init__(self):
        self._config_changed = False
        self._wake_now = False
        self._run_completed_id: str | None = None

    @workflow.signal
    async def configuration_changed(self):
        self._config_changed = True

    @workflow.signal
    async def wake_now(self):
        self._wake_now = True

    @workflow.signal
    async def run_completed(self, run_id: str):
        self._run_completed_id = run_id

    @workflow.run
    async def run(self, args: dict) -> dict:
        agent_id = str(args["agent_id"])
        processed = 0
        while True:
            state = await workflow.execute_activity(
                load_heartbeat_state, {"agent_id": agent_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if not state or not state.get("enabled"):
                # Disabled; wait for a configuration change signal indefinitely.
                self._config_changed = False
                await workflow.wait_condition(lambda: self._config_changed)
                continue

            status = state.get("operational_status")
            if status in {"blocked_global", "blocked_archived", "blocked_mode", "paused"}:
                # Park until a configuration/lifecycle signal arrives.
                self._config_changed = False
                await workflow.wait_condition(lambda: self._config_changed or self._wake_now)
                self._wake_now = False
                continue

            next_wake_raw = state.get("next_wake_at")
            if next_wake_raw:
                try:
                    next_wake = datetime.fromisoformat(next_wake_raw)
                except ValueError:
                    next_wake = workflow.now()
            else:
                next_wake = workflow.now()

            # Wait until next_wake, interruptible by signals.
            self._config_changed = False
            self._wake_now = False
            sleep_seconds = max(0, (next_wake - workflow.now()).total_seconds())
            if sleep_seconds > 0:
                timeout = timedelta(seconds=min(sleep_seconds, 86400))
                try:
                    await workflow.wait_condition(
                        lambda: self._config_changed or self._wake_now or workflow.now() >= next_wake,
                        timeout=timeout,
                    )
                except TimeoutError:
                    pass  # Sleep elapsed; proceed to materialize
            if self._config_changed:
                continue
            self._wake_now = False

            # Materialize the heartbeat run.
            materialized = await workflow.execute_activity(
                materialize_heartbeat_run, {"agent_id": agent_id},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            if not materialized.get("created"):
                # Agent unavailable or blocked; park and retry later.
                self._config_changed = False
                await workflow.wait_condition(lambda: self._config_changed or self._wake_now)
                self._wake_now = False
                continue

            run_id = materialized["run_id"]
            thread_id = materialized["thread_id"]
            workspace_id = materialized["workspace_id"]

            # Enqueue through the existing thread coordinator.
            from app.workflows.agent_workflows import ThreadTurnCoordinatorWorkflow
            coordinator_id = f"thread-coordinator:{thread_id}"
            handle = workflow.get_external_workflow_handle(coordinator_id)
            try:
                await workflow.start_child_workflow(
                    ThreadTurnCoordinatorWorkflow.run,
                    {"thread_id": thread_id, "workspace_id": workspace_id, "task_queue": "threadbot-agent"},
                    id=coordinator_id,
                    task_queue="threadbot-agent",
                )
            except Exception:
                pass
            try:
                await handle.signal(ThreadTurnCoordinatorWorkflow.enqueue, run_id)
            except Exception:
                await workflow.sleep(1)
                try:
                    await handle.signal(ThreadTurnCoordinatorWorkflow.enqueue, run_id)
                except Exception:
                    pass

            # Wait for run completion signal with a durable DB reconciliation
            # fallback so a missed signal doesn't park us forever.
            self._run_completed_id = None
            deadline = workflow.now() + timedelta(minutes=30)
            while self._run_completed_id != run_id and workflow.now() < deadline:
                try:
                    await workflow.wait_condition(
                        lambda: self._run_completed_id == run_id,
                        timeout=timedelta(seconds=60),
                    )
                except TimeoutError:
                    pass  # Reconcile via DB below
                if self._run_completed_id == run_id:
                    break
                # Periodic DB reconciliation: check if the run is terminal.
                check = await workflow.execute_activity(
                    load_heartbeat_state, {"agent_id": agent_id},
                    start_to_close_timeout=timedelta(seconds=30),
                )
                if check and check.get("last_run_id") != run_id:
                    # A different run has replaced this one; treat as completed.
                    break

            # Reconcile run state and schedule next wake.
            from app.activities.autonomy_activities import finalize_turn
            # Completion data is sourced from DB by complete_heartbeat_run.
            completed = await workflow.execute_activity(
                complete_heartbeat_run,
                {
                    "agent_id": agent_id,
                    "run_id": run_id,
                    "decision": None,
                    "requested_next_wake": None,
                    "status": None,
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            processed += 1
            if processed >= 100:
                await workflow.continue_as_new(args)
        return {"agent_id": agent_id}
