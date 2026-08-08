from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select

from app.models.approval_models import ApprovalDecision, ApprovalRequest
from app.models.foundation_models import AuditEvent, DomainEvent
from app.models.run_models import AgentAction


class ApprovalDecisionError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


async def record_approval_decision(
    db,
    *,
    approval_id: UUID,
    workspace_id: UUID,
    decision: str,
    actor_id: str,
    actor_type: str,
    channel: str,
    provider_interaction_id: str,
    reason: str | None = None,
    correlation_id: UUID | None = None,
) -> dict:
    if decision not in {"approved", "denied"}:
        raise ApprovalDecisionError(422, "decision must be approved or denied")

    row = await db.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if not row:
        raise ApprovalDecisionError(404, "approval not found")

    existing = await db.scalar(
        select(ApprovalDecision).where(ApprovalDecision.request_id == row.id)
    )
    if existing:
        if existing.provider_interaction_id == provider_interaction_id:
            return {
                "approval_id": row.id,
                "run_id": row.run_id,
                "status": row.status,
                "request_hash": row.request_hash,
            }
        raise ApprovalDecisionError(409, "approval already has a decision")

    if row.status != "pending" or row.expires_at <= datetime.now(timezone.utc):
        raise ApprovalDecisionError(409, "approval is no longer active")

    action = await db.scalar(
        select(AgentAction).where(
            AgentAction.run_id == row.run_id,
            AgentAction.action_id == row.action_id,
        )
    )
    if not action or action.request_hash != row.request_hash:
        raise ApprovalDecisionError(409, "approval hash no longer matches action")

    db.add(
        ApprovalDecision(
            request_id=row.id,
            decision=decision,
            actor_id=actor_id,
            actor_type=actor_type,
            channel=channel,
            reason=reason,
            provider_interaction_id=provider_interaction_id,
        )
    )
    row.status = decision
    if decision == "denied":
        action.status = "denied"

    correlation_id = correlation_id or uuid4()
    payload = {"decision": decision, "request_hash": row.request_hash, "channel": channel}
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="approval.decided",
            resource_type="approval_request",
            resource_id=str(row.id),
            metadata_=payload,
            correlation_id=correlation_id,
        )
    )
    db.add(
        DomainEvent(
            workspace_id=workspace_id,
            event_type="approval.decided",
            payload=payload,
            dedupe_key=f"approval.decided:{row.id}:{provider_interaction_id}",
            correlation_id=correlation_id,
        )
    )
    await db.commit()
    return {
        "approval_id": row.id,
        "run_id": row.run_id,
        "status": row.status,
        "request_hash": row.request_hash,
    }


async def signal_approval_decision(run_id: UUID, approval_id: UUID) -> None:
    from app.api.routes import get_temporal_client

    client = get_temporal_client()
    if not client:
        return
    try:
        from app.contracts.approval import ApprovalWakeSignal

        handle = client.get_workflow_handle(f"agent-turn:{run_id}")
        await handle.signal(
            "approval_decision",
            ApprovalWakeSignal(request_id=str(approval_id)),
        )
    except Exception:
        # The durable decision remains authoritative. Workflow reconciliation
        # and retry paths can observe it even when the best-effort signal fails.
        pass
