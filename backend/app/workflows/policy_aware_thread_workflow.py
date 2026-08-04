import asyncio
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.contracts.runtime import ThreadTurnInputV2
    from app.contracts.approval import ApprovalWakeSignal
    from app.tools.catalog import classify_tool_for_agent
    from app.activities.autonomy_activities import (
        prepare_runtime, plan_model_step, persist_planned_action,
        evaluate_policy_and_reserve_budget, load_verified_approval, create_approval_request,
        recheck_authorization, execute_authorized_action, persist_action_result,
        finalize_turn, start_runtime, transition_action_status,
        transition_run_status, settle_budget, renew_thread_lease,
        is_retryable_pause_reason, gate_heartbeat_output,
    )


@workflow.defn
class PolicyAwareThreadTurnWorkflow:
    def __init__(self):
        self._approval_request_id = None
        self._approval_decision = None

    @workflow.signal
    async def approval_decision(self, signal: ApprovalWakeSignal):
        # The signal intentionally carries only the durable request identity.
        request_id = str(signal.request_id)
        if self._approval_request_id is not None and request_id == self._approval_request_id:
            self._approval_decision = True

    @workflow.run
    async def run(self, raw_input: ThreadTurnInputV2) -> dict:
        try:
            return await self._run_impl(raw_input)
        except asyncio.CancelledError:
            request = raw_input if isinstance(raw_input, ThreadTurnInputV2) else ThreadTurnInputV2.model_validate(raw_input)
            await asyncio.shield(self._finalize(request, "cancelled", "runtime cancelled"))
            raise
        except Exception:
            request = raw_input if isinstance(raw_input, ThreadTurnInputV2) else ThreadTurnInputV2.model_validate(raw_input)
            return await self._finalize(request, "failed", "runtime failed")

    async def _run_impl(self, raw_input: ThreadTurnInputV2) -> dict:
        request = raw_input if isinstance(raw_input, ThreadTurnInputV2) else ThreadTurnInputV2.model_validate(raw_input)
        context = request.run_context
        deadline = context.deadline_at
        if deadline and workflow.now() >= deadline:
            return await self._finalize(request, "timed_out", "deadline exceeded")
        started = None
        for _ in range(30):
            started = await workflow.execute_activity(start_runtime, {"run_id": str(request.run_id), "thread_id": str(request.thread_id), "workspace_id": str(request.workspace_id)}, start_to_close_timeout=timedelta(seconds=60), retry_policy=RetryPolicy(maximum_attempts=3))
            if started["started"] or started.get("reason") != "thread lease is held":
                break
            await workflow.sleep(timedelta(seconds=2))
        if started and not started["started"] and is_retryable_pause_reason(started.get("reason", "")):
            return {"status": "queued", "output_summary": "waiting for thread coordinator lease"}
        if not started["started"]:
            return await self._finalize(request, "suppressed", started.get("reason", "not started"))
        prepared = await workflow.execute_activity(prepare_runtime, {"runtime_snapshot_id": str(request.runtime_snapshot_id), "thread_id": str(request.thread_id), "agent_id": str(request.actor.actor_id), "route": context.stream_context.get("route", ""), "input_message_id": context.stream_context.get("input_message_id")}, start_to_close_timeout=timedelta(seconds=60), retry_policy=RetryPolicy(maximum_attempts=3))
        messages = list(prepared["messages"])
        tool_descriptors = prepared.get("tool_descriptors", [])
        model_calls = 0
        tool_calls = 0
        last_text = ""
        route = str(context.stream_context.get("route") or "")
        heartbeat_has_evidence = False
        allow_heartbeat_without_tools = bool(
            prepared.get("allow_heartbeat_response_without_tools", False)
        )
        for _cycle in range(context.max_cycles):
            await workflow.execute_activity(renew_thread_lease, {"run_id": str(request.run_id), "thread_id": str(request.thread_id)}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
            if deadline and workflow.now() >= deadline:
                return await self._finalize(request, "timed_out", "deadline exceeded")
            if model_calls >= context.max_model_calls:
                return await self._finalize(request, "exhausted", last_text)
            result = await workflow.execute_activity(plan_model_step, {"snapshot": prepared["snapshot"], "messages": messages, "tool_descriptors": tool_descriptors, "mode": context.mode.value}, start_to_close_timeout=timedelta(seconds=120), retry_policy=RetryPolicy(maximum_attempts=3))
            model_calls += 1
            last_text = result.get("text", "") if context.response_mode in {"response", "both"} else ""
            proposals = result.get("proposals", []) if context.response_mode in {"actions", "both"} else []
            if not proposals:
                output = gate_heartbeat_output(
                    route,
                    last_text,
                    has_successful_tool_evidence=heartbeat_has_evidence,
                    allow_without_tools=allow_heartbeat_without_tools,
                )
                return await self._finalize(request, "succeeded", output)
            for proposal in proposals:
                if tool_calls >= context.max_tool_calls:
                    return await self._finalize(request, "exhausted", last_text)
                proposal = dict(proposal)
                proposal["retry_safe"] = classify_tool_for_agent(proposal["tool_identity"]).get("retry_safe", False)
                proposal["agent_version"] = context.stream_context.get("agent_version", "unknown")
                proposal["policy_version"] = context.stream_context.get("policy_version", str(context.policy_set_id or "default"))
                proposal["credential_binding_id"] = context.credential_binding_ids[0] if context.credential_binding_ids else None
                proposal["approval_expires_at"] = (deadline or workflow.now() + timedelta(seconds=300)).isoformat()
                planned = await workflow.execute_activity(persist_planned_action, {"run_id": str(request.run_id), "proposal": proposal}, start_to_close_timeout=timedelta(seconds=60), retry_policy=RetryPolicy(maximum_attempts=3))
                policy = await workflow.execute_activity(evaluate_policy_and_reserve_budget, {"run_id": str(request.run_id), "action_id": planned["action_id"], "tool_identity": proposal["tool_identity"], "request_hash": planned["request_hash"], "budget_profile_id": context.budget_profile_id, "workspace_id": str(request.workspace_id), "policy_version": proposal.get("policy_version", "default")}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                needs_approval = policy["effect"] == "require_approval" or bool(policy.get("requires_approval", False))
                if policy["effect"] == "deny":
                    await workflow.execute_activity(transition_action_status, {"action_db_id": planned["action_db_id"], "run_id": str(request.run_id), "action_id": planned["action_id"], "expected": "planned", "target": "policy_denied", "event_type": "policy_decision"}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                    if policy.get("reservation_id"):
                        await workflow.execute_activity(settle_budget, {"reservation_key": f"{request.run_id}:{planned['action_id']}:tool_calls", "commit": False}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                    messages.append({"role": "tool", "tool_call_id": proposal["tool_call_id"], "content": "Denied: " + policy["reason"]})
                    continue
                if context.mode.value in {"dry_run", "replay", "canary_shadow"}:
                    await workflow.execute_activity(transition_action_status, {"action_db_id": planned["action_db_id"], "run_id": str(request.run_id), "action_id": planned["action_id"], "expected": "planned", "target": "simulated", "event_type": "action_simulated"}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                    if policy.get("reservation_id"):
                        await workflow.execute_activity(settle_budget, {"reservation_key": f"{request.run_id}:{planned['action_id']}:tool_calls", "commit": False}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                    messages.append({"role": "tool", "tool_call_id": proposal["tool_call_id"], "content": "dry-run: execution suppressed"})
                    continue
                if needs_approval:
                    approval_request = await workflow.execute_activity(create_approval_request, {"workspace_id": str(request.workspace_id), "run_id": str(request.run_id), "action_id": planned["action_id"], "action_revision": planned["revision"], "request_hash": planned["request_hash"], "credential_ref": str(proposal.get("credential_binding_id")) if proposal.get("credential_binding_id") else None, "expires_at": proposal.get("approval_expires_at")}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                    self._approval_request_id = approval_request["request_id"]
                    await workflow.execute_activity(transition_action_status, {"action_db_id": planned["action_db_id"], "run_id": str(request.run_id), "action_id": planned["action_id"], "expected": "planned", "target": "awaiting_approval", "event_type": "approval_requested"}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                    approval = await workflow.execute_activity(load_verified_approval, {"request_id": self._approval_request_id, "action_id": planned["action_id"], "action_revision": planned["revision"], "request_hash": planned["request_hash"]}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=2)) if self._approval_request_id else None
                    if not approval:
                        self._approval_request_id = approval_request["request_id"]
                        self._approval_decision = None
                        await workflow.execute_activity(transition_run_status, {"run_id": str(request.run_id), "expected": "running", "target": "waiting_approval", "event_type": "approval_requested"}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                        await workflow.execute_activity(renew_thread_lease, {"run_id": str(request.run_id), "thread_id": str(request.thread_id)}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                        expiry = timedelta(seconds=300)
                        if context.deadline_at:
                            expiry = max(timedelta(0), context.deadline_at - workflow.now())
                        received = await workflow.wait_condition(lambda: self._approval_decision is True, timeout=expiry)
                        if not received:
                            if policy.get("reservation_id"):
                                await workflow.execute_activity(settle_budget, {"reservation_key": f"{request.run_id}:{planned['action_id']}:tool_calls", "commit": False}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                            return await self._finalize(request, "timed_out", "approval expired")
                        await workflow.execute_activity(transition_run_status, {"run_id": str(request.run_id), "expected": "waiting_approval", "target": "running", "event_type": "approval_received"}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                        approval = await workflow.execute_activity(load_verified_approval, {"request_id": self._approval_request_id, "action_id": planned["action_id"], "action_revision": planned["revision"], "request_hash": planned["request_hash"]}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=2))
                        if not approval:
                            if policy.get("reservation_id"):
                                await workflow.execute_activity(settle_budget, {"reservation_key": f"{request.run_id}:{planned['action_id']}:tool_calls", "commit": False}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                            return await self._finalize(request, "failed", "approval verification failed")
                await workflow.execute_activity(transition_action_status, {"action_db_id": planned["action_db_id"], "run_id": str(request.run_id), "action_id": planned["action_id"], "expected": "awaiting_approval" if policy.get("requires_approval") else "planned", "target": "authorized", "authorization_ref": policy.get("authorization_ref", "unlimited"), "authorization_hash": policy.get("authorization_hash", planned["request_hash"]), "event_type": "authorization"}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                await workflow.execute_activity(transition_action_status, {"action_db_id": planned["action_db_id"], "run_id": str(request.run_id), "action_id": planned["action_id"], "expected": "authorized", "target": "executing", "event_type": "action_started"}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                authorization = await workflow.execute_activity(recheck_authorization, {"tool_identity": proposal["tool_identity"], "request_id": self._approval_request_id if policy.get("requires_approval") else None, "request_hash": planned["request_hash"]}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                if authorization["effect"] != "allow":
                    denied = {"schema_version": 1, "action_id": planned["action_id"], "action_revision": planned["revision"], "status": "failed", "display_content": "authorization recheck denied", "model_content": "authorization recheck denied", "error_code": "authorization_denied", "retry_safe": True}
                    await workflow.execute_activity(persist_action_result, {"run_id": str(request.run_id), "action_id": planned["action_id"], "result": denied}, start_to_close_timeout=timedelta(seconds=60), retry_policy=RetryPolicy(maximum_attempts=3))
                    if policy.get("reservation_id"):
                        await workflow.execute_activity(settle_budget, {"reservation_key": f"{request.run_id}:{planned['action_id']}:tool_calls", "commit": False}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                    messages.append({"role": "tool", "tool_call_id": proposal["tool_call_id"], "content": "Denied before execution"})
                    continue
                tool_calls += 1
                action_result = await workflow.execute_activity(execute_authorized_action, {"workspace_id": str(request.workspace_id), "run_id": str(request.run_id), "thread_id": str(request.thread_id), "action_id": planned["action_id"], "action_revision": planned["revision"], "request_hash": planned["request_hash"], "authorization_ref": policy.get("authorization_ref", "unlimited"), "authorization_hash": policy.get("authorization_hash", planned["request_hash"]), "tool_identity": proposal["tool_identity"], "arguments": proposal["arguments"], "allowed_tool_identities": prepared.get("authorized_tool_identities", []), "mode": context.mode.value, "dry_run": context.mode.value != "live"}, start_to_close_timeout=timedelta(seconds=120), retry_policy=RetryPolicy(maximum_attempts=3 if proposal.get("retry_safe") else 1))
                await workflow.execute_activity(persist_action_result, {"run_id": str(request.run_id), "action_id": planned["action_id"], "result": action_result}, start_to_close_timeout=timedelta(seconds=60), retry_policy=RetryPolicy(maximum_attempts=3))
                if action_result.get("status") == "succeeded":
                    heartbeat_has_evidence = True
                if policy.get("reservation_id"):
                    await workflow.execute_activity(settle_budget, {"reservation_key": f"{request.run_id}:{planned['action_id']}:tool_calls", "commit": action_result.get("status") == "succeeded"}, start_to_close_timeout=timedelta(seconds=30), retry_policy=RetryPolicy(maximum_attempts=3))
                messages.append({"role": "tool", "tool_call_id": proposal["tool_call_id"], "content": action_result.get("model_content", "")})
        output = gate_heartbeat_output(
            route,
            last_text,
            has_successful_tool_evidence=heartbeat_has_evidence,
            allow_without_tools=allow_heartbeat_without_tools,
        )
        return await self._finalize(request, "exhausted", output)

    async def _finalize(self, request, status: str, text: str) -> dict:
        return await workflow.execute_activity(finalize_turn, {"run_id": str(request.run_id), "thread_id": str(request.thread_id), "status": status, "output_summary": text}, start_to_close_timeout=timedelta(seconds=60), retry_policy=RetryPolicy(maximum_attempts=3), cancellation_type=workflow.ActivityCancellationType.ABANDON)
