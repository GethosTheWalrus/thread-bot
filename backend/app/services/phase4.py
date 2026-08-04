from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.phase4_models import ReplaySession, RecoveryOperation, CanaryComparison, SLOAlert, SLOMetric
from app.models.run_models import AgentRun, AgentRunEvent, AgentAction
from app.models.approval_models import ApprovalRequest
from app.models.run_models import Artifact
from app.models.phase2_models import NotificationDelivery


def replay_safe_mode(mode: str, requested_dry_run: bool = True) -> tuple[str, bool]:
    if mode == "recorded":
        return "recorded", True
    return "reexecution", True


async def recorded_replay(db: AsyncSession, run: AgentRun) -> ReplaySession:
    events = (await db.execute(select(AgentRunEvent).where(AgentRunEvent.run_id == run.id).order_by(AgentRunEvent.sequence))).scalars().all()
    actions = (await db.execute(select(AgentAction).where(AgentAction.run_id == run.id).order_by(AgentAction.created_at))).scalars().all()
    approvals = (await db.execute(select(ApprovalRequest).where(ApprovalRequest.run_id == run.id).order_by(ApprovalRequest.created_at))).scalars().all()
    artifacts = (await db.execute(select(Artifact).where(Artifact.run_id == run.id).order_by(Artifact.created_at))).scalars().all()
    notifications = (await db.execute(select(NotificationDelivery).where(NotificationDelivery.workspace_id == run.workspace_id, NotificationDelivery.business_key.like(f"run:{run.id}:%")).order_by(NotificationDelivery.created_at))).scalars().all()
    timeline = [{"sequence": e.sequence, "type": e.event_type, "payload": redact_replay(e.payload), "created_at": e.created_at.isoformat() if e.created_at else None} for e in events]
    timeline.extend({"type": "action", "action_id": a.action_id, "status": a.status, "tool_identity": a.tool_identity, "request_hash": a.request_hash} for a in actions)
    timeline.extend({"type": "approval", "id": str(a.id), "status": a.status, "request_hash": a.request_hash} for a in approvals)
    timeline.extend({"type": "artifact", "id": str(a.id), "content_type": a.content_type, "size_bytes": a.size_bytes, "sha256": a.sha256, "classification": a.classification} for a in artifacts)
    timeline.extend({"type": "notification", "id": str(n.id), "event_type": n.event_type, "status": n.status, "business_key": n.business_key} for n in notifications)
    timeline.sort(key=lambda item: (item.get("sequence", 10**9), item.get("type", "")))
    session = ReplaySession(workspace_id=run.workspace_id, source_run_id=run.id, agent_version_id=run.agent_version_id, mode="recorded", effect_free=True, timeline=timeline)
    db.add(session)
    return session


async def reexecute_replay(db: AsyncSession, run: AgentRun) -> ReplaySession:
    # The immutable version is copied, not resolved from the agent's current version.
    replay = AgentRun(workspace_id=run.workspace_id, agent_id=run.agent_id, agent_version_id=run.agent_version_id,
        thread_id=run.thread_id, trigger_event_id=run.trigger_event_id, source_run_id=run.id,
        source_trigger_event_id=run.source_trigger_event_id, correlation_id=uuid4(), causation_id=run.id,
        mode="replay", status="queued", budget_snapshot=run.budget_snapshot or {},
        usage_summary={"replay_of": str(run.id), "dry_run": True, "fresh_approvals": True, "model_calls_effect_free": True})
    db.add(replay)
    await db.flush()
    session = ReplaySession(workspace_id=run.workspace_id, source_run_id=run.id, replay_run_id=replay.id,
        agent_version_id=run.agent_version_id, mode="reexecution", effect_free=True,
        comparison={"model_calls": "executed", "external_effects": "suppressed"})
    db.add(session)
    return session


def forecast_from_runs(runs: list[AgentRun], horizon_hours: int) -> dict:
    dimensions = ("tokens", "cost", "tool_calls", "connector_calls", "approvals", "notifications",
                  "artifacts", "sla_breaches", "concurrency", "queue_demand")
    values = defaultdict(list)
    for run in runs:
        usage = run.usage_summary or {}
        for key in dimensions:
            if usage.get(key) is not None:
                values[key].append(float(usage[key]))
        values["concurrency"].append(1.0 if run.status == "running" else 0.0)
        values["queue_demand"].append(1.0 if run.status == "queued" else 0.0)
    metrics = {}
    for key in dimensions:
        samples = sorted(values[key])
        if not samples:
            metrics[key] = {"p50": 0, "p90": 0, "sample_size": 0}
        else:
            metrics[key] = {"p50": samples[(len(samples) - 1) // 2], "p90": samples[min(len(samples) - 1, max(0, int(len(samples) * .9) - 1))], "sample_size": len(samples)}
    days = horizon_hours / 24
    for value in metrics.values():
        value["projected_p50"] = value["p50"] * days
        value["projected_p90"] = value["p90"] * days
    return {"horizon_hours": horizon_hours, "metrics": metrics,
            "assumptions": ["observed completed runs are representative", "missing usage dimensions are zero", "P50/P90 are empirical quantiles", "forecast does not change budgets", "cohort traffic is not extrapolated without observations"],
            "confidence": "high" if len(runs) >= 30 else "medium" if len(runs) >= 5 else "low"}


async def write_canary_comparison(db: AsyncSession, workspace_id: UUID, deployment_id: UUID, candidate_run_id: UUID, stable_run_id: UUID | None, metrics: dict) -> CanaryComparison:
    """Persist a tenant-scoped comparison; repeated observations are idempotent."""
    row = await db.scalar(select(CanaryComparison).where(
        CanaryComparison.workspace_id == workspace_id,
        CanaryComparison.deployment_id == deployment_id,
        CanaryComparison.candidate_run_id == candidate_run_id,
        CanaryComparison.stable_run_id == stable_run_id,
    ))
    if row:
        row.metrics = redact_replay(metrics)
        return row
    row = CanaryComparison(workspace_id=workspace_id, deployment_id=deployment_id, candidate_run_id=candidate_run_id, stable_run_id=stable_run_id, metrics=redact_replay(metrics))
    db.add(row)
    await db.flush()
    return row


async def upsert_slo_alert(db: AsyncSession, workspace_id: UUID, alert_key: str, metric: str, threshold: int, status: str, details: dict | None = None) -> SLOAlert:
    row = await db.scalar(select(SLOAlert).where(SLOAlert.workspace_id == workspace_id, SLOAlert.alert_key == alert_key).with_for_update())
    if not row:
        row = SLOAlert(workspace_id=workspace_id, alert_key=alert_key, metric=metric, threshold=threshold, status=status, details=redact_replay(details or {}))
        db.add(row)
    else:
        row.metric, row.threshold, row.status, row.details = metric, threshold, status, redact_replay(details or {})
    return row


async def record_slo_metric(db: AsyncSession, workspace_id: UUID, metric: str, value: int, details: dict | None = None) -> SLOMetric:
    row = SLOMetric(workspace_id=workspace_id, metric=metric, value=max(0, int(value)), details=redact_replay(details or {}))
    db.add(row)
    return row


async def audit_recovery(db: AsyncSession, workspace_id: UUID, actor_id: str, operation: str, resource_id: str, details: dict | None = None):
    resource_type = {"retry_dead_letter": "dead_letter", "reconcile_action": "agent_action", "expire_approval": "approval", "pause_queue": "queue", "drain_queue": "queue", "resume_queue": "queue", "rollback_version": "agent_version", "recorded_replay": "agent_run", "reexecution_replay": "agent_run", "canary_promoted": "canary_deployment", "canary_rolled_back": "canary_deployment"}.get(operation)
    if not resource_type:
        raise ValueError("unsupported recovery operation")
    row = RecoveryOperation(workspace_id=workspace_id, actor_id=actor_id, operation=operation,
        resource_type=resource_type, resource_id=resource_id, details=redact_replay(details or {}))
    db.add(row)
    return row


def redact_replay(value):
    if isinstance(value, dict):
        sensitive = ("secret", "token", "password", "ciphertext", "credential", "api_key", "authorization", "cookie", "idempotency", "recovery")
        hidden_reasoning = ("reasoning", "thoughts", "chain_of_thought", "hidden_reasoning")
        safe_summary = ("summary", "safe_summary", "reasoning_summary")
        def redact_key(key):
            normalized = str(key).lower().replace("-", "_")
            if any(part in normalized for part in sensitive):
                return True
            return any(part in normalized for part in hidden_reasoning) and not any(part in normalized for part in safe_summary)
        return {k: "[REDACTED]" if redact_key(k) else redact_replay(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_replay(v) for v in value]
    if isinstance(value, str) and re.search(r"(?i)(bearer\s+\S+|https?://[^\s/@]+:[^\s/@]+@|(?:token|secret|password|api[_-]?key)\s*[:=]\s*\S+)", value):
        return "[REDACTED]"
    return value


def shadow_effects_blocked(mode: str) -> dict[str, bool]:
    blocked = mode in {"dry_run", "replay", "canary_shadow"}
    return {"notifications": blocked, "handoffs": blocked, "reachy": blocked, "mutations": blocked, "unsafe_credentials": blocked}


def cohort_matches(cohort: dict | None, event) -> bool:
    """Return a stable assignment decision without using process randomness."""
    import hashlib
    import json

    cohort = cohort or {}
    for key in ("source", "event_type"):
        expected = cohort.get(key)
        if expected is not None and getattr(event, key, None) != expected:
            return False
    for key, values in (("subject", event.subject or {}), ("payload", event.payload or {})):
        for field, expected in (cohort.get(key) or {}).items():
            if values.get(field) != expected:
                return False
    percent = cohort.get("percentage", cohort.get("percent", 100))
    try:
        percent = max(0.0, min(100.0, float(percent)))
    except (TypeError, ValueError):
        return False
    if percent >= 100:
        return True
    if percent <= 0:
        return False
    seed = json.dumps({"deployment": str(cohort.get("deployment_id", "")), "event": str(event.id)}, sort_keys=True)
    digits = 8
    bucket = int(hashlib.sha256(seed.encode()).hexdigest()[:digits], 16) / float(16 ** digits) * 100
    return bucket < percent
