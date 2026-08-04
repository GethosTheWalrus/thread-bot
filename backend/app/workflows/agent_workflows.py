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
    from app.workflows.notification_workflow import NotificationDeliveryWorkflow
    from app.workflows.heartbeat_workflow import AgentHeartbeatWorkflow
    from app.activities.state_activities import capture_connector_snapshot, persist_state_diff

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
        binding = (loaded.get("credential_bindings") or [None])[0]
        binding_id = binding.get("binding_id") if isinstance(binding, dict) else binding
        snapshot=await workflow.execute_activity(persist_runtime_snapshot,{"workspace_id":loaded["workspace_id"],"version_id":loaded["version_id"],"model_config":loaded["version_config"],"credential_binding_id":binding_id},start_to_close_timeout=timedelta(seconds=30))
        from uuid import UUID
        mode=loaded.get("mode") if loaded.get("mode") in {"dry_run", "replay", "canary_shadow"} else "autonomous"
        # Autonomous workflow provenance reflects the deployment, not a human
        # login.  In local mode the actor is local/system; in admin_token mode
        # it remains admin_token so policy rules keyed on provenance still work.
        auth_method = AuthenticationMethod(loaded.get("authentication_method", "local"))
        budget=loaded.get("budget_snapshot") or {}; config=loaded.get("version_config") or {}; limits={"max_cycles":max(1,int(budget.get("max_cycles",config.get("max_cycles",1)))),"max_model_calls":max(1,int(budget.get("max_model_calls",config.get("max_model_calls",1)))),"max_tool_calls":max(0,int(budget.get("tool_calls",budget.get("max_tool_calls",config.get("max_tool_calls",0)))))}
        deadline=datetime.fromisoformat(loaded["deadline_at"]) if loaded.get("deadline_at") else None
        turn=ThreadTurnInputV2(schema_version=2,workspace_id=UUID(loaded["workspace_id"]),thread_id=UUID(loaded["thread_id"]),actor=ActorContext(workspace_id=UUID(loaded["workspace_id"]),actor_type=ActorType.agent,actor_id=loaded["agent_id"],authentication_method=auth_method,correlation_id=UUID(loaded["run_id"])),run_id=UUID(run_id),runtime_snapshot_id=UUID(snapshot["runtime_snapshot_id"]),input_message_ref=loaded.get("input_message_id") or "background",run_context={"mode":mode,"response_mode":loaded.get("response_mode", "both"),"source_trust":"untrusted_content","deadline_at":deadline,"budget_profile_id":UUID(loaded["budget_profile_id"]) if loaded.get("budget_profile_id") else None,"credential_binding_ids":tuple(UUID(str(item.get("binding_id"))) for item in (loaded.get("credential_bindings") or []) if isinstance(item, dict) and item.get("binding_id")),"stream_context":{"agent_version":loaded.get("version_id", "unknown"),"policy_version":loaded.get("policy_version", "default"),"route":loaded.get("route", ""),"input_message_id":loaded.get("input_message_id")},**limits})
        before_state = {}
        if loaded.get("connector_id"):
            captured = await workflow.execute_activity(capture_connector_snapshot, {"connector_id": loaded["connector_id"], "agent_id": loaded["agent_id"], "run_id": run_id, "subject": loaded.get("subject", {})}, start_to_close_timeout=timedelta(seconds=60))
            if captured.get("supported"): before_state = captured.get("state", {})
        try:
            result=await workflow.execute_child_workflow(PolicyAwareThreadTurnWorkflow.run,turn,id=f"agent-turn:{run_id}",task_queue="threadbot-agent",search_attributes=loaded.get("search_attributes"))
            status=result.get("status","failed"); summary=result.get("output_summary")
        except asyncio.CancelledError:
            status="cancelled"; summary="runtime cancelled"
            await workflow.execute_activity(project_run_terminal,{"run_id":run_id,"status":status,"output_summary":summary},start_to_close_timeout=timedelta(seconds=30),cancellation_type=workflow.ActivityCancellationType.ABANDON)
            raise
        except Exception as exc:
            status="failed"; summary=str(exc)
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
