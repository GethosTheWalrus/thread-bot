"""Durable, bounded autonomy orchestration.  No credentials or content enter workflow state."""
import asyncio
from datetime import timedelta, datetime
from temporalio import workflow
from temporalio.common import RetryPolicy
with workflow.unsafe.imports_passed_through():
    from app.contracts.runtime import ThreadTurnInputV2
    from app.contracts.common import ActorContext,ActorType,AuthenticationMethod
    from app.activities.agent_activities import load_agent_run,persist_runtime_snapshot,project_run_terminal,recover_coordinator_queue,recover_thread_queue,route_agent_output,materialize_trigger_event,claim_event_run,mark_run_workflow,fail_run,suppress_event
    from app.workflows.policy_aware_thread_workflow import PolicyAwareThreadTurnWorkflow
    from app.workflows.thread_workflow import RunThreadWorkflow
    from app.workflows.notification_workflow import NotificationDeliveryWorkflow
    from app.workflows.heartbeat_workflow import AgentHeartbeatWorkflow
    from app.activities.state_activities import capture_connector_snapshot, persist_state_diff
    from app.activities.autonomy_activities import start_runtime, release_runtime, append_progress_event
    from app.activities.llm_activities import generate_and_update_title


def derive_runtime_limits(
    config: dict, budget: dict, tool_selection: list | tuple | None = None
) -> dict:
    """Apply bounded defaults without overriding explicit policy limits."""
    selected_tools = (
        tool_selection if tool_selection is not None else config.get("tool_selection")
    )
    has_tools = bool(selected_tools)

    def configured(name: str, default: int, *aliases: str) -> int:
        for source in (budget, config):
            for key in (name, *aliases):
                if key in source and source[key] is not None:
                    return int(source[key])
        return default

    step_default = 5 if has_tools else 1
    return {
        "max_cycles": max(1, configured("max_cycles", step_default)),
        "max_model_calls": max(1, configured("max_model_calls", step_default)),
        "max_tool_calls": max(
            0,
            configured("max_tool_calls", 4 if has_tools else 0, "tool_calls"),
        ),
    }


@workflow.defn
class ThreadTurnCoordinatorWorkflow:
    """One durable FIFO for every thread, including approval-held turns."""
    def __init__(self):
        self.queue = []
        self.active = None
        self.processed = 0

    @workflow.signal
    async def enqueue(self, run_id: str):
        if run_id not in self.queue and run_id != self.active:
            self.queue.append(run_id)

    @workflow.run
    async def run(self, args):
        recovered = await workflow.execute_activity(
            recover_thread_queue, {"thread_id": args["thread_id"], "workspace_id": args["workspace_id"]},
            start_to_close_timeout=timedelta(seconds=30))
        for run_id in recovered.get("run_ids", []):
            if run_id not in self.queue: self.queue.append(run_id)
        while True:
            await workflow.wait_condition(lambda: bool(self.queue))
            self.active = self.queue.pop(0)
            try:
                result = await workflow.execute_child_workflow(
                    AgentRunWorkflow.run, self.active, id=f"agent-run:{self.active}",
                    task_queue=args.get("task_queue", "threadbot-agent"))
                if result and result.get("status") == "queued":
                    await workflow.sleep(timedelta(seconds=2))
                    self.queue.append(self.active)
            except Exception:
                # The durable AgentRun remains queued/running and is recovered
                # on the next coordinator task; never silently drop it.
                pass
            finally:
                self.active = None
                self.processed += 1
            if self.processed >= 1000:
                await workflow.continue_as_new(args)

@workflow.defn
class AgentCoordinatorWorkflow:
    def __init__(self): self.paused=False; self.draining=False; self.queue=[]; self.overflow=[]; self.active=None; self.processed=0; self.queue_limit=100
    @workflow.signal
    async def enqueue(self,event_id:str):
        if not self.draining and event_id not in self.queue and event_id != self.active:
            if len(self.queue) >= self.queue_limit:
                self.overflow.append(event_id)
                return
            self.queue.append(event_id)
    @workflow.signal
    async def pause(self): self.paused=True
    @workflow.signal
    async def resume(self): self.paused=False; self.draining=False
    @workflow.signal
    async def drain(self): self.draining=True; self.paused=False
    @workflow.run
    async def run(self,args):
        agent_id=str(args["agent_id"]); recovered=await workflow.execute_activity(recover_coordinator_queue,{"agent_id":agent_id,"limit":100},start_to_close_timeout=timedelta(seconds=30))
        self.queue_limit=int(args.get("queue_limit",recovered.get("queue_limit",100)))
        for item in recovered["run_ids"][:self.queue_limit]:
            if item not in self.queue:self.queue.append(item)
        while True:
            while self.overflow:
                await workflow.execute_activity(suppress_event,{"event_id":self.overflow.pop(0)},start_to_close_timeout=timedelta(seconds=30))
            await workflow.wait_condition(lambda:self.queue and not self.paused)
            self.active=self.queue.pop(0)
            claimed=await workflow.execute_activity(claim_event_run,{"event_id":self.active},start_to_close_timeout=timedelta(seconds=30))
            run_ids=claimed.get("run_ids") or ([claimed["run_id"]] if claimed.get("run_id") else [])
            if not run_ids:
                self.active=None; continue
            try:
                for run_id in run_ids:
                    result = await workflow.execute_child_workflow(AgentRunWorkflow.run,run_id,id=f"agent-run:{run_id}",task_queue=args.get("task_queue","threadbot-agent"),search_attributes=args.get("search_attributes"))
                    if result and result.get("status") == "queued":
                        await workflow.sleep(timedelta(seconds=2))
                        self.queue.append(run_id)
            except Exception: pass
            finally:
                self.active=None; self.processed+=1
                if self.processed >= 1000:
                    # Materialize pending event IDs so the next run can recover them
                    # from queued AgentRun rows after continue-as-new.
                    for event_id in self.queue:
                        await workflow.execute_activity(claim_event_run,{"event_id":event_id},start_to_close_timeout=timedelta(seconds=30))
                    await workflow.continue_as_new({"agent_id":agent_id,"task_queue":args.get("task_queue","threadbot-agent")})

@workflow.defn
class AgentRunWorkflow:
    @workflow.run
    async def run(self,run_id:str):
        loaded=await workflow.execute_activity(load_agent_run,{"run_id":run_id},start_to_close_timeout=timedelta(seconds=30),retry_policy=RetryPolicy(maximum_attempts=3))
        if not loaded.get("found"): return {"status":"failed"}
        if loaded["status"] in {"cancelled","succeeded","failed","exhausted","timed_out","suppressed"}: return {"status":loaded["status"]}
        workflow_id=f"agent-run:{run_id}"
        await workflow.execute_activity(mark_run_workflow,{"run_id":run_id,"workflow_id":workflow_id},start_to_close_timeout=timedelta(seconds=30))
        shared_patch = workflow.patched("agent-shared-thread-turn-v1")
        binding = (loaded.get("credential_bindings") or [None])[0]
        binding_id = binding.get("binding_id") if isinstance(binding, dict) else binding
        snapshot=await workflow.execute_activity(persist_runtime_snapshot,{"workspace_id":loaded["workspace_id"],"version_id":loaded["version_id"],"model_config":loaded["version_config"],"credential_binding_id":binding_id},start_to_close_timeout=timedelta(seconds=30))
        from uuid import UUID
        mode=loaded.get("mode") if loaded.get("mode") in {"dry_run", "replay", "canary_shadow"} else "autonomous"
        # Effect-free evaluation modes intentionally retain the policy-aware
        # path. Live interactive and heartbeat runs use the Chat engine.
        shared_route = shared_patch and loaded.get("mode") == "live"
        # Autonomous workflow provenance reflects the deployment, not a human
        # login.  In local mode the actor is local/system; in admin_token mode
        # it remains admin_token so policy rules keyed on provenance still work.
        auth_method = AuthenticationMethod(loaded.get("authentication_method", "local"))
        budget=loaded.get("budget_snapshot") or {}; config=loaded.get("version_config") or {}; limits=derive_runtime_limits(config, budget, loaded.get("tool_selection"))
        deadline=datetime.fromisoformat(loaded["deadline_at"]) if loaded.get("deadline_at") else None
        turn=ThreadTurnInputV2(schema_version=2,workspace_id=UUID(loaded["workspace_id"]),thread_id=UUID(loaded["thread_id"]),actor=ActorContext(workspace_id=UUID(loaded["workspace_id"]),actor_type=ActorType.agent,actor_id=loaded["agent_id"],authentication_method=auth_method,correlation_id=UUID(loaded["run_id"])),run_id=UUID(run_id),runtime_snapshot_id=UUID(snapshot["runtime_snapshot_id"]),input_message_ref=loaded.get("input_message_id") or "background",run_context={"mode":mode,"response_mode":loaded.get("response_mode", "both"),"source_trust":"untrusted_content","deadline_at":deadline,"budget_profile_id":UUID(loaded["budget_profile_id"]) if loaded.get("budget_profile_id") else None,"credential_binding_ids":tuple(UUID(str(item.get("binding_id"))) for item in (loaded.get("credential_bindings") or []) if isinstance(item, dict) and item.get("binding_id")),"stream_context":{"agent_version":loaded.get("version_id", "unknown"),"policy_version":loaded.get("policy_version", "default"),"route":loaded.get("route", ""),"input_message_id":loaded.get("input_message_id")},**limits})
        before_state = {}
        if loaded.get("connector_id"):
            captured = await workflow.execute_activity(capture_connector_snapshot, {"connector_id": loaded["connector_id"], "agent_id": loaded["agent_id"], "run_id": run_id, "subject": loaded.get("subject", {})}, start_to_close_timeout=timedelta(seconds=60))
            if captured.get("supported"): before_state = captured.get("state", {})
        try:
            if shared_route:
                started = await workflow.execute_activity(start_runtime, {"run_id": run_id, "thread_id": loaded["thread_id"], "workspace_id": loaded["workspace_id"], "lease_seconds": 21600}, start_to_close_timeout=timedelta(seconds=60), retry_policy=RetryPolicy(maximum_attempts=3))
                if not started.get("started"):
                    reason = started.get("reason", "not started")
                    if reason in {"thread lease is held", "queue is paused", "queue is draining"}:
                        return {"status": "queued", "output_summary": reason}
                    terminal = await workflow.execute_activity(project_run_terminal, {"run_id": run_id, "status": "suppressed", "output_summary": reason}, start_to_close_timeout=timedelta(seconds=30))
                    if loaded.get("route") == "heartbeat":
                        try:
                            await workflow.get_external_workflow_handle(f"agent-heartbeat:{loaded['agent_id']}").signal(AgentHeartbeatWorkflow.run_completed, str(run_id))
                        except Exception:
                            pass
                    return terminal
                await workflow.execute_activity(append_progress_event, {"run_id": run_id, "event_type": "run_started", "payload": {"workflow": "RunThreadWorkflow"}}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
            # New runs use the chat engine.  The patch marker is deliberately
            # above the child command so old histories retain their command
            # sequence and remain replay compatible.
            if shared_route:
                context = {
                    "agent_id": loaded["agent_id"],
                    "agent_version_id": loaded["version_id"],
                    "agent_run_id": loaded["run_id"],
                    "agent_name": loaded.get("agent_name"),
                    "agent_handle": loaded.get("agent_handle"),
                    "prompt": loaded.get("prompt_template") or "",
                    "instructions": loaded.get("prompt_template") or "",
                    "selected_tools": loaded.get("tool_selection") or [],
                    "selected_skills": loaded.get("skill_selection") or [],
                    "skills": loaded.get("selected_skills") or [],
                    "route": loaded.get("route", ""),
                    "scheduled_at": workflow.now().isoformat() if loaded.get("route") == "heartbeat" else None,
                    "response_mode": loaded.get("response_mode", "both"),
                }
                child_input = {
                    "thread_id": str(loaded["thread_id"]),
                    "message": "",
                    "llm_config": {
                        **(loaded.get("llm_config") or loaded.get("version_config") or {}),
                        "system_prompt": loaded.get("prompt_template") or "",
                        "tool_selection": loaded.get("tool_selection") or [],
                        "skills": loaded.get("selected_skills") or [],
                        "response_mode": loaded.get("response_mode", "both"),
                        "agent_context": context,
                    },
                    "agent_context": context,
                }
                result = await workflow.execute_child_workflow(
                    RunThreadWorkflow.run, child_input, id=f"agent-turn:{run_id}",
                    task_queue=loaded.get("chat_task_queue", "threadbot"), search_attributes=loaded.get("search_attributes"),
                )
                title_args = result.get("title") if isinstance(result, dict) else None
                if title_args:
                    try:
                        await workflow.execute_activity(
                            generate_and_update_title,
                            title_args,
                            task_queue=loaded.get("chat_task_queue", "threadbot"),
                            start_to_close_timeout=timedelta(seconds=60),
                            retry_policy=RetryPolicy(maximum_attempts=2),
                        )
                    except Exception:
                        pass
            else:
                result=await workflow.execute_child_workflow(PolicyAwareThreadTurnWorkflow.run,turn,id=f"agent-turn:{run_id}",task_queue="threadbot-agent",search_attributes=loaded.get("search_attributes"))
            if shared_route:
                await workflow.execute_activity(release_runtime, {"run_id": run_id, "thread_id": loaded["thread_id"]}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
            if shared_route:
                status = "succeeded"
                summary = result.get("response") or ""
            else:
                status=result.get("status","failed"); summary=result.get("output_summary")
        except asyncio.CancelledError:
            status="cancelled"; summary="runtime cancelled"
            if shared_route:
                await workflow.execute_activity(release_runtime, {"run_id": run_id, "thread_id": loaded["thread_id"]}, start_to_close_timeout=timedelta(seconds=30), cancellation_type=workflow.ActivityCancellationType.ABANDON)
            await workflow.execute_activity(project_run_terminal,{"run_id":run_id,"status":status,"output_summary":summary},start_to_close_timeout=timedelta(seconds=30),cancellation_type=workflow.ActivityCancellationType.ABANDON)
            raise
        except Exception as exc:
            status="failed"; summary=str(exc)
            if shared_route:
                try:
                    await workflow.execute_activity(release_runtime, {"run_id": run_id, "thread_id": loaded["thread_id"]}, start_to_close_timeout=timedelta(seconds=30))
                except Exception:
                    pass
        if status == "queued":
            return {"status": "queued", "output_summary": summary}
        terminal = await workflow.execute_activity(project_run_terminal,{"run_id":run_id,"status":status,"output_summary":summary},start_to_close_timeout=timedelta(seconds=30))
        # Notify the heartbeat workflow that this run completed.
        if loaded.get("route") == "heartbeat":
            try:
                hb_handle = workflow.get_external_workflow_handle(f"agent-heartbeat:{loaded['agent_id']}")
                await hb_handle.signal(AgentHeartbeatWorkflow.run_completed, str(run_id))
            except Exception:
                pass
        if status == "succeeded":
            routed = await workflow.execute_activity(route_agent_output, {"run_id": run_id}, start_to_close_timeout=timedelta(seconds=30))
            if routed.get("routed") and routed.get("run_id"):
                handle = workflow.get_external_workflow_handle(f"thread-coordinator:{loaded['thread_id']}")
                try:
                    await handle.signal(ThreadTurnCoordinatorWorkflow.enqueue, routed["run_id"])
                except Exception:
                    pass
        if loaded.get("connector_id") and before_state:
            captured = await workflow.execute_activity(capture_connector_snapshot, {"connector_id": loaded["connector_id"], "agent_id": loaded["agent_id"], "run_id": run_id, "subject": loaded.get("subject", {})}, start_to_close_timeout=timedelta(seconds=60))
            if captured.get("supported"):
                await workflow.execute_activity(persist_state_diff, {"workspace_id": loaded["workspace_id"], "run_id": run_id, "before": before_state, "after": captured.get("state", {})}, start_to_close_timeout=timedelta(seconds=60))
        for delivery_id in terminal.get("delivery_ids", []):
            await workflow.execute_child_workflow(NotificationDeliveryWorkflow.run, {"delivery_id": str(delivery_id), "mode": mode}, id=f"notification:{delivery_id}", task_queue="threadbot-notifications", search_attributes=loaded.get("search_attributes"))
        return terminal

@workflow.defn
class TriggerDispatchWorkflow:
    @workflow.run
    async def run(self,args):
        dispatch_args=dict(args)
        if not dispatch_args.get("scheduled_at"):
            dispatch_args["scheduled_at"]=workflow.now().isoformat()
        materialized=await workflow.execute_activity(materialize_trigger_event,dispatch_args,start_to_close_timeout=timedelta(seconds=30))
        if not materialized.get("created"): return materialized
        agent_id=str(materialized["agent_id"]); event_id=str(materialized["event_id"]); task_queue=args.get("task_queue","threadbot-agent")
        # Thread coordinators are the serialization boundary.  Keep the old
        # agent coordinator workflow above registered for history compatibility.
        thread_id = None
        event_run = await workflow.execute_activity(claim_event_run, {"event_id": event_id}, start_to_close_timeout=timedelta(seconds=30))
        if event_run.get("run_id"):
            loaded_run = await workflow.execute_activity(load_agent_run, {"run_id": event_run["run_id"]}, start_to_close_timeout=timedelta(seconds=30))
            thread_id = loaded_run.get("thread_id")
        if not thread_id:
            return {"event_id": event_id}
        coordinator_id = f"thread-coordinator:{thread_id}"
        handle = workflow.get_external_workflow_handle(coordinator_id)
        try:
            await workflow.start_child_workflow(ThreadTurnCoordinatorWorkflow.run,{"thread_id":thread_id,"workspace_id":loaded_run["workspace_id"],"task_queue":task_queue},id=coordinator_id,task_queue=task_queue)
        except Exception:
            pass
        try: await handle.signal(ThreadTurnCoordinatorWorkflow.enqueue,event_run.get("run_id"))
        except Exception:
            # A start race is resolved by retrying the signal against the stable id.
            await workflow.sleep(1)
            await handle.signal(ThreadTurnCoordinatorWorkflow.enqueue,event_run.get("run_id"))
        return {"event_id":event_id}
