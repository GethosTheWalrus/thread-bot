"""Temporal activities for adaptive agent heartbeats.

These are intentionally small and idempotent.  They never perform model calls or
external effects directly; the heartbeat decision is evaluated through the
existing policy-aware thread turn runtime.
"""
from temporalio.activity import defn


@defn
async def load_heartbeat_state(args: dict) -> dict | None:
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.agents.heartbeat_service import load_heartbeat_state as _load
    async with AsyncSessionLocal() as db:
        return await _load(db, UUID(str(args["agent_id"])))


@defn
async def materialize_heartbeat_run(args: dict) -> dict:
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.agents.heartbeat_service import materialize_heartbeat_run as _mat
    async with AsyncSessionLocal() as db:
        result = await _mat(db, UUID(str(args["agent_id"])))
        await db.commit()
        return result


@defn
async def complete_heartbeat_run(args: dict) -> dict:
    from uuid import UUID
    from app.database import AsyncSessionLocal
    from app.agents.heartbeat_service import complete_heartbeat_run as _complete
    async with AsyncSessionLocal() as db:
        result = await _complete(
            db,
            UUID(str(args["agent_id"])),
            UUID(str(args["run_id"])),
            decision=args.get("decision"),
            requested_next_wake=args.get("requested_next_wake"),
            status=args.get("status", "succeeded"),
            error=args.get("error"),
        )
        await db.commit()
        return result


@defn
async def reconcile_heartbeats(args: dict | None = None) -> dict:
    """Best-effort reconciliation: ensure enabled heartbeats have workflows.

    Called periodically by the worker.  PostgreSQL remains the desired-state
    authority; a missed Temporal signal here is recovered on the next tick.
    """
    from app.database import AsyncSessionLocal
    from app.agents.heartbeat_service import list_enabled_heartbeats, heartbeat_workflow_id
    from app.workflows.heartbeat_workflow import AgentHeartbeatWorkflow
    from app.temporal_client import connect_temporal_client
    enqueued = 0
    client = await connect_temporal_client()
    if client is None:
        return {"enqueued": 0, "reason": "temporal unavailable"}
    async with AsyncSessionLocal() as db:
        rows = await list_enabled_heartbeats(db)
    for row in rows:
        workflow_id = heartbeat_workflow_id(row.agent_id)
        handle = client.get_workflow_handle(workflow_id)
        try:
            # Signal is safe if the workflow is running; if it isn't, we start it.
            await handle.signal(AgentHeartbeatWorkflow.configuration_changed)
            enqueued += 1
        except Exception:
            try:
                await client.start_workflow(
                    AgentHeartbeatWorkflow.run,
                    {"agent_id": str(row.agent_id), "workspace_id": str(row.workspace_id)},
                    id=workflow_id,
                    task_queue="threadbot-agent",
                )
                enqueued += 1
            except Exception:
                pass
    return {"enqueued": enqueued}


@defn
async def evaluate_heartbeat_step(args: dict) -> dict:
    """Run the heartbeat decision model call and return a normalized plan.

    This is a thin wrapper that reuses the policy-aware runtime's model call
    but forces the heartbeat evaluation contract.  The actual side effects
    (response, action, delegation) are applied by the existing
    PolicyAwareThreadTurnWorkflow; this activity only produces the decision.
    """
    from app.activities.autonomy_activities import plan_model_step
    # Inject the heartbeat decision instruction into the messages.
    messages = list(args.get("messages") or [])
    messages.append({
        "role": "system",
        "content": (
            "Evaluate whether to act now based on your immutable instructions and "
            "the thread evidence and heartbeat temporal context above. Respect every "
            "cadence as a minimum interval and do not repeat a prior report when its "
            "interval has not elapsed. Never infer external state from another agent's "
            "prior output; use fresh tool evidence from this run or choose no_op. "
            "Respond with a JSON object having keys: "
            "decision (one of response|action|delegate|no_op), next_wake_seconds "
            "(integer between 1 and 604800), response (string), delegate_handle "
            "(string or null), safe_reasoning_summary (string).  Do not include "
            "credentials.  Choose no_op when there is no material change to act on."
        ),
    })
    result = await plan_model_step({
        "snapshot": args["snapshot"],
        "messages": messages,
        "tool_descriptors": args.get("tool_descriptors") or [],
        "mode": args.get("mode", "live"),
    })
    # Parse the JSON decision from the model text.  Be defensive.
    import json
    decision = "no_op"
    next_wake = None
    text = result.get("text", "") or ""
    try:
        # The model may wrap JSON in code fences or prose; extract the first
        # JSON object from the text.
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end + 1])
            decision = str(parsed.get("decision") or "no_op")
            next_wake = parsed.get("next_wake_seconds")
    except (ValueError, TypeError):
        pass
    if decision not in {"response", "action", "delegate", "no_op"}:
        decision = "no_op"
    # If the planner returned tool proposals, force decision to "action".
    if result.get("proposals"):
        decision = "action"
    return {
        "decision": decision,
        "next_wake_seconds": next_wake,
        "text": result.get("text", ""),
        "proposals": result.get("proposals", []),
        "model_call_id": result.get("model_call_id"),
    }
