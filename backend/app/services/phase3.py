"""Deterministic Phase 3 boundaries.  This module never executes external effects."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.models.phase3_models import HandoffContract, AgentHandoff, HandoffEscalation, PolicyRecommendation, ArtifactTombstone
from app.models.agent_models import Agent
from app.models.budget_models import BudgetBucket, BudgetReservation

def validate_json_schema(schema: dict, value: dict) -> None:
    try:
        from jsonschema import Draft202012Validator
        errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    except ImportError as exc: raise RuntimeError("jsonschema dependency is required") from exc
    if errors: raise ValueError("handoff payload does not match contract schema: " + "; ".join(error.message for error in errors[:3]))

def validate_handoff(contract, target_id: UUID, payload: dict, origin_chain: list[str]) -> None:
    if contract.target_allowlist and target_id not in {UUID(str(item)) for item in contract.target_allowlist}: raise ValueError("target agent is not allowlisted")
    validate_json_schema(contract.input_schema, payload)
    if len(origin_chain) + 1 > contract.max_depth: raise ValueError("handoff depth limit exceeded")
    target_marker = f"agent:{target_id}"
    if target_marker in origin_chain: raise ValueError("handoff cycle detected")

async def create_handoff(db, workspace_id, source_run_id, body):
    contract = await db.scalar(select(HandoffContract).where(HandoffContract.id == body.contract_id, HandoffContract.workspace_id == workspace_id, HandoffContract.is_active.is_(True)))
    target = await db.scalar(select(Agent).where(Agent.id == body.target_agent_id, Agent.workspace_id == workspace_id, Agent.status == "active"))
    if not contract or not target: raise ValueError("contract or target agent not found")
    validate_handoff(contract, target.id, body.input_payload, body.origin_chain)
    now = datetime.now(timezone.utc)
    row = AgentHandoff(workspace_id=workspace_id, contract_id=contract.id, source_run_id=source_run_id, target_agent_id=target.id, input_payload=body.input_payload, origin_chain=body.origin_chain + [f"agent:{target.id}"], hop_count=len(body.origin_chain)+1, idempotency_key=body.idempotency_key, response_mode=body.response_mode.value, acknowledgement_deadline=now + timedelta(seconds=min(contract.timeout_seconds, 300)), completion_deadline=now + timedelta(seconds=contract.timeout_seconds))
    try:
        async with db.begin_nested(): db.add(row); await db.flush()
    except IntegrityError:
        row = await db.scalar(select(AgentHandoff).where(AgentHandoff.workspace_id == workspace_id, AgentHandoff.idempotency_key == body.idempotency_key))
    return row

async def record_handoff_rejection(db, workspace_id, source_run_id, reason):
    from app.database.autonomy import append_run_event
    from app.models.foundation_models import AuditEvent, DomainEvent
    run = await db.get(__import__("app.models.run_models", fromlist=["AgentRun"]).AgentRun, source_run_id)
    correlation_id = run.correlation_id if run else UUID(int=0)
    if run:
        await append_run_event(db, source_run_id, "handoff_suppressed", {"reason": reason})
    db.add(AuditEvent(workspace_id=workspace_id, actor_type="system", actor_id="policy", action="handoff.suppressed", resource_type="agent_run", resource_id=str(source_run_id), metadata_={"reason": reason}, correlation_id=correlation_id))
    db.add(DomainEvent(workspace_id=workspace_id, event_type="handoff.suppressed", payload={"run_id": str(source_run_id), "reason": reason}, dedupe_key=f"handoff.suppressed:{source_run_id}:{reason}", correlation_id=correlation_id))

async def fire_escalation_once(db, workspace_id, handoff_id, stage, target_type, target_id):
    row = HandoffEscalation(workspace_id=workspace_id, handoff_id=handoff_id, stage=stage, target_type=target_type, target_id=target_id, status="fired", fired_at=datetime.now(timezone.utc))
    try:
        async with db.begin_nested(): db.add(row); await db.flush()
        return True
    except IntegrityError: return False

async def tombstone_artifact(db, artifact, reason="retention_expired"):
    row = ArtifactTombstone(workspace_id=artifact.workspace_id, artifact_id=artifact.id, sha256=artifact.sha256, reason=reason)
    db.add(row); artifact.storage_key = "tombstoned:" + str(artifact.id); return row

async def reserve_budget(db, workspace_id, bucket_id, run_id, amount: int, reservation_key: str, ttl_seconds: int = 900):
    """Reserve capacity separately from execution; retries are idempotent."""
    existing = await db.scalar(select(BudgetReservation).where(BudgetReservation.workspace_id == workspace_id, BudgetReservation.reservation_key == reservation_key))
    if existing: return existing
    bucket = await db.scalar(select(BudgetBucket).where(BudgetBucket.id == bucket_id).with_for_update())
    if not bucket or bucket.used + bucket.reserved + amount > bucket.hard_limit: raise ValueError("budget reservation denied")
    bucket.reserved += amount
    row = BudgetReservation(workspace_id=workspace_id, bucket_id=bucket_id, run_id=run_id, amount=amount, reservation_key=reservation_key, expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds))
    db.add(row); await db.flush(); return row

async def settle_budget(db, reservation_id, actual: int, release: bool = False):
    reservation = await db.scalar(select(BudgetReservation).where(BudgetReservation.id == reservation_id).with_for_update())
    if not reservation or reservation.status != "reserved": return reservation
    bucket = await db.scalar(select(BudgetBucket).where(BudgetBucket.id == reservation.bucket_id).with_for_update())
    consumed = min(max(actual, 0), reservation.amount)
    bucket.reserved -= reservation.amount; bucket.used += consumed
    reservation.status = "released" if release else "committed"; reservation.amount = consumed
    return reservation
