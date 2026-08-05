from datetime import datetime, timezone, timedelta
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy import select, desc
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.security import require_autonomy, require_owner_or_admin, autonomy_flags
from app.contracts.common import ActorContext
from app.credentials.contracts import CredentialCreate, CredentialResponse
from app.models.phase2_models import Connector, NotificationProfile, NotificationDelivery, DeadLetter, WebhookNonce, NotificationRoute
from app.models.foundation_models import Credential, CredentialVersion, CredentialBinding
from app.models.approval_models import ApprovalRequest, ApprovalDecision
from app.models.run_models import AgentAction, AgentRun
from app.models.foundation_models import AuditEvent, DomainEvent
from app.models.foundation_models import IdempotencyRecord
from app.policy.engine import evaluate_policy, explain_risk
from app.notifications.service import enqueue_delivery
from app.connectors.webhook import verify_signed_webhook, normalize_webhook
from app.services.phase2 import ingest_connector_event
from app.contracts.phase2 import ConnectorPage, ApprovalResponse
from app.contracts import redact_secret

router = APIRouter(prefix="/api", tags=["autonomy-phase2"], dependencies=[Depends(require_autonomy("autonomy_enabled"))])
public_router = APIRouter(prefix="/api", tags=["autonomy-webhooks"])


async def actor_dep(actor: ActorContext = Depends(require_owner_or_admin)): return actor


async def audit_phase2(db, actor, action: str, resource_type: str, resource_id, payload: dict | None = None):
    value = payload or {}
    db.add(AuditEvent(workspace_id=actor.workspace_id, actor_type=actor.actor_type.value, actor_id=actor.actor_id, action=action, resource_type=resource_type, resource_id=str(resource_id), metadata_=value, correlation_id=actor.correlation_id))
    db.add(DomainEvent(workspace_id=actor.workspace_id, event_type=action, payload=value, dedupe_key=f"{action}:{resource_id}:{actor.correlation_id}", correlation_id=actor.correlation_id))


async def claim_mutation_key(db, actor, key: str | None, operation: str):
    if not key: raise HTTPException(422, "Idempotency-Key header is required")
    existing = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.workspace_id == actor.workspace_id, IdempotencyRecord.key == key).with_for_update())
    if existing:
        if existing.operation != operation:
            raise HTTPException(409, "Idempotency-Key was used for a different operation")
        if existing.status == "completed" and existing.response is not None:
            return existing.response
        raise HTTPException(409, "Idempotency-Key is already in progress")
    db.add(IdempotencyRecord(workspace_id=actor.workspace_id, key=key, operation=operation, status="in_progress")); await db.flush()
    return None


async def complete_mutation_key(db, actor, key: str, response):
    row = await db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.workspace_id == actor.workspace_id, IdempotencyRecord.key == key).with_for_update())
    if row:
        from fastapi.encoders import jsonable_encoder
        row.status = "completed"; row.response = jsonable_encoder(response)


def safe_config(value):
    return redact_secret(value or {})


@router.get("/connectors", response_model=ConnectorPage)
async def connectors(db=Depends(get_db), actor=Depends(actor_dep), limit: int = 50, after: str | None = None):
    query = select(Connector).where(Connector.workspace_id == actor.workspace_id)
    if after:
        try: query = query.where(Connector.id < UUID(after))
        except ValueError: raise HTTPException(400, "invalid cursor")
    rows = list((await db.execute(query.order_by(Connector.created_at.desc(), Connector.id.desc()).limit(min(max(limit, 1), 200)))).scalars())
    return {"items": [{"id": row.id, "workspace_id": row.workspace_id, "name": row.name, "connector_type": row.connector_type, "config": safe_config(row.config), "is_active": row.is_active} for row in rows], "next_cursor": str(rows[-1].id) if len(rows) == min(max(limit, 1), 200) else None}


@router.post("/connectors")
async def create_connector(body: dict, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    replay = await claim_mutation_key(db, actor, idempotency_key, "connector.create")
    if replay is not None: return replay
    allowed = {"webhook", "http_json", "rss", "discord", "temporal", "mcp", "reachy"}
    if body.get("connector_type") not in allowed: raise HTTPException(422, "unsupported connector type")
    row = Connector(workspace_id=actor.workspace_id, name=body["name"], connector_type=body["connector_type"], config=body.get("config") or {}, credential_binding_id=body.get("credential_binding_id"))
    db.add(row); await db.flush(); await audit_phase2(db, actor, "connector.created", "connector", row.id, {"connector_type": row.connector_type}); response = {"id": row.id, "workspace_id": row.workspace_id, "name": row.name, "connector_type": row.connector_type, "config": safe_config(row.config), "is_active": row.is_active}; await complete_mutation_key(db, actor, idempotency_key, response); return response


@router.delete("/connectors/{connector_id}", status_code=204)
async def delete_connector(connector_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(Connector).where(Connector.id == connector_id, Connector.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "connector not found")
    row.is_active = False; await audit_phase2(db, actor, "connector.deactivated", "connector", row.id)


@router.patch("/connectors/{connector_id}")
async def patch_connector(connector_id: UUID, body: dict, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    replay = await claim_mutation_key(db, actor, idempotency_key, "connector.update")
    if replay is not None: return replay
    row = await db.scalar(select(Connector).where(Connector.id == connector_id, Connector.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "connector not found")
    if "config" in body: row.config = body["config"]
    if "is_active" in body: row.is_active = bool(body["is_active"])
    if "name" in body: row.name = body["name"]
    await audit_phase2(db, actor, "connector.updated", "connector", row.id); response = {"id": row.id, "workspace_id": row.workspace_id, "name": row.name, "connector_type": row.connector_type, "config": safe_config(row.config), "is_active": row.is_active}; await complete_mutation_key(db, actor, idempotency_key, response); return response


@public_router.post("/agent-webhooks/{public_trigger_id}")
async def receive_webhook(public_trigger_id: str, request: Request, db=Depends(get_db), signature: str | None = Header(None, alias="X-ThreadBot-Signature"), timestamp: str | None = Header(None, alias="X-ThreadBot-Timestamp"), nonce: str | None = Header(None, alias="X-ThreadBot-Nonce")):
    if not autonomy_flags().get("autonomy_webhooks_enabled", False): raise HTTPException(404, "webhooks are disabled")
    connector = await db.scalar(select(Connector).where(Connector.connector_type == "webhook", Connector.is_active.is_(True), Connector.config["public_trigger_id"].as_string() == public_trigger_id))
    if not connector: raise HTTPException(404, "webhook not found")
    body = await request.body()
    from app.credentials.service import resolve_credential_binding
    if not connector.credential_binding_id: raise HTTPException(503, "webhook credential is not configured")
    credential = await resolve_credential_binding(connector.credential_binding_id)
    if not verify_signed_webhook(body, signature or "", credential["secret"], timestamp or "", nonce or ""):
        raise HTTPException(401, "invalid webhook signature")
    try:
        stamp = datetime.fromtimestamp(int(timestamp), timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(401, "invalid webhook timestamp")
    try:
        async with db.begin_nested():
            db.add(WebhookNonce(workspace_id=connector.workspace_id, connector_id=connector.id, nonce=nonce, timestamp=stamp, expires_at=stamp + timedelta(seconds=300)))
            await db.flush()
    except IntegrityError:
        raise HTTPException(409, "webhook replay rejected")
    import json
    try: payload = json.loads(body)
    except ValueError: raise HTTPException(400, "webhook body must be JSON")
    envelope = await normalize_webhook(payload, nonce or signature or "webhook")
    event, created, reason = await ingest_connector_event(db, connector, envelope, agent_id=connector.config.get("agent_id"), trigger_id=connector.config.get("trigger_id"))
    if reason: return {"accepted": False, "reason": reason}
    return {"accepted": True, "duplicate": not created, "event_id": str(event.id)}


@router.post("/credentials", response_model=CredentialResponse)
async def create_credential(body: CredentialCreate, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    replay = await claim_mutation_key(db, actor, idempotency_key, "credential.create")
    if replay is not None: return replay
    from app.encryption import encrypt_scalar
    row = Credential(workspace_id=actor.workspace_id, name=body.name, provider=body.provider)
    db.add(row); await db.flush()
    version = CredentialVersion(credential_id=row.id, version=1, ciphertext=await encrypt_scalar(body.secret), has_secret=True)
    db.add(version); await db.flush(); row.active_version_id = version.id
    await audit_phase2(db, actor, "credential.created", "credential", row.id, {"provider": row.provider}); await complete_mutation_key(db, actor, idempotency_key, row); return row


@router.get("/credentials", response_model=list[CredentialResponse])
async def credentials(db=Depends(get_db), actor=Depends(actor_dep)):
    rows = (await db.execute(select(Credential).where(Credential.workspace_id == actor.workspace_id).order_by(Credential.name))).scalars().all()
    return rows


@router.delete("/credentials/{credential_id}", status_code=204)
async def delete_credential(credential_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(Credential).where(Credential.id == credential_id, Credential.workspace_id == actor.workspace_id))
    if not row: raise HTTPException(404, "credential not found")
    row.active_version_id = None; await audit_phase2(db, actor, "credential.deactivated", "credential", row.id)


@router.post("/credentials/{credential_id}/rotate", response_model=CredentialResponse)
async def rotate_credential(credential_id: UUID, body: CredentialCreate, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    replay = await claim_mutation_key(db, actor, idempotency_key, "credential.rotate")
    if replay is not None: return replay
    from app.encryption import encrypt_scalar
    row = await db.scalar(select(Credential).where(Credential.id == credential_id, Credential.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "credential not found")
    latest = await db.scalar(select(CredentialVersion).where(CredentialVersion.credential_id == row.id).order_by(CredentialVersion.version.desc()))
    version = CredentialVersion(credential_id=row.id, version=(latest.version + 1 if latest else 1), ciphertext=await encrypt_scalar(body.secret), has_secret=True)
    db.add(version); await db.flush(); row.provider = body.provider; row.name = body.name; row.active_version_id = version.id
    await audit_phase2(db, actor, "credential.rotated", "credential", row.id, {"version": version.version}); await complete_mutation_key(db, actor, idempotency_key, row); return row


@router.post("/credentials/{credential_id}/deactivate", response_model=CredentialResponse)
async def deactivate_credential(credential_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    row = await db.scalar(select(Credential).where(Credential.id == credential_id, Credential.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "credential not found")
    row.active_version_id = None; await audit_phase2(db, actor, "credential.deactivated", "credential", row.id)
    return row


@router.get("/credentials/{credential_id}/versions")
async def credential_versions(credential_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    credential = await db.scalar(select(Credential).where(Credential.id == credential_id, Credential.workspace_id == actor.workspace_id))
    if not credential: raise HTTPException(404, "credential not found")
    rows = (await db.execute(select(CredentialVersion).where(CredentialVersion.credential_id == credential.id).order_by(CredentialVersion.version.desc()))).scalars().all()
    return [{"id": row.id, "version": row.version, "algorithm": row.algorithm, "key_id": row.key_id, "has_secret": row.has_secret, "created_at": row.created_at} for row in rows]


@router.post("/credential-bindings")
async def create_binding(body: dict, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    replay = await claim_mutation_key(db, actor, idempotency_key, "credential_binding.create")
    if replay is not None: return replay
    credential = await db.scalar(select(Credential).where(Credential.id == body.get("credential_id"), Credential.workspace_id == actor.workspace_id))
    if not credential: raise HTTPException(404, "credential not found")
    row = CredentialBinding(workspace_id=actor.workspace_id, credential_id=credential.id, binding_key=body["binding_key"], constraints=body.get("constraints") or {})
    db.add(row); await db.flush(); await audit_phase2(db, actor, "credential_binding.created", "credential_binding", row.id)
    response = {"id": row.id, "credential_id": row.credential_id, "binding_key": row.binding_key, "constraints": row.constraints, "has_secret": True}; await complete_mutation_key(db, actor, idempotency_key, response); return response


@router.get("/credential-bindings")
async def bindings(db=Depends(get_db), actor=Depends(actor_dep)):
    rows = (await db.execute(select(CredentialBinding).where(CredentialBinding.workspace_id == actor.workspace_id, CredentialBinding.is_active.is_(True)))).scalars().all()
    return [{"id": row.id, "credential_id": row.credential_id, "binding_key": row.binding_key, "constraints": row.constraints, "has_secret": True} for row in rows]


@router.post("/policies/explain")
async def policy_explain(body: dict, actor=Depends(actor_dep)):
    return evaluate_policy(body, body.get("rules"), str(body.get("policy_version", "default")))


@router.get("/approvals", response_model=list[ApprovalResponse])
async def approvals(db=Depends(get_db), actor=Depends(actor_dep)):
    return (await db.execute(select(ApprovalRequest).where(
        ApprovalRequest.workspace_id == actor.workspace_id,
        ApprovalRequest.status == "pending",
        ApprovalRequest.expires_at > datetime.now(timezone.utc),
    ).order_by(ApprovalRequest.expires_at))).scalars().all()


@router.post("/approvals/{approval_id}/decision")
async def approval_decision(approval_id: UUID, body: dict, request: Request, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    if body.get("decision") not in {"approved", "denied"}: raise HTTPException(422, "decision must be approved or denied")
    if idempotency_key is None: raise HTTPException(422, "Idempotency-Key header is required")
    row = await db.scalar(select(ApprovalRequest).where(ApprovalRequest.id == approval_id, ApprovalRequest.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "approval not found")
    existing = await db.scalar(select(ApprovalDecision).where(ApprovalDecision.request_id == row.id))
    if existing and existing.provider_interaction_id == idempotency_key:
        return {"approval_id": row.id, "status": row.status, "request_hash": row.request_hash}
    if row.status != "pending" or row.expires_at <= datetime.now(timezone.utc): raise HTTPException(409, "approval is no longer active")
    action = await db.scalar(select(AgentAction).where(AgentAction.run_id == row.run_id, AgentAction.action_id == row.action_id))
    if not action or action.request_hash != row.request_hash: raise HTTPException(409, "approval hash no longer matches action")
    db.add(ApprovalDecision(request_id=row.id, decision=body["decision"], actor_id=actor.actor_id, actor_type=actor.actor_type.value, channel="web", reason=body.get("reason"), provider_interaction_id=idempotency_key))
    row.status = "approved" if body["decision"] == "approved" else "denied"
    await audit_phase2(db, actor, "approval.decided", "approval_request", row.id, {"decision": body["decision"], "request_hash": row.request_hash})
    if body["decision"] == "denied": action.status = "denied"
    from app.api.routes import get_temporal_client
    client = get_temporal_client()
    if client:
        handle = client.get_workflow_handle(f"agent-turn:{row.run_id}")
        try:
            from app.contracts.approval import ApprovalWakeSignal
            await handle.signal("approval_decision", ApprovalWakeSignal(request_id=str(row.id)))
        except Exception: pass
    return {"approval_id": row.id, "status": row.status, "request_hash": row.request_hash}


@router.get("/notifications/profiles")
async def notification_profiles(db=Depends(get_db), actor=Depends(actor_dep)):
    return (await db.execute(select(NotificationProfile).where(NotificationProfile.workspace_id == actor.workspace_id))).scalars().all()


@router.post("/notifications/profiles")
async def create_notification_profile(body: dict, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    replay = await claim_mutation_key(db, actor, idempotency_key, "notification_profile.create")
    if replay is not None: return replay
    row = NotificationProfile(workspace_id=actor.workspace_id, name=body["name"], routes=body.get("routes") or [])
    db.add(row); await db.flush(); await audit_phase2(db, actor, "notification_profile.created", "notification_profile", row.id); await complete_mutation_key(db, actor, idempotency_key, row); return row


@router.post("/notifications/profiles/{profile_id}/routes")
async def create_notification_route(profile_id: UUID, body: dict, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    replay = await claim_mutation_key(db, actor, idempotency_key, "notification_route.create")
    if replay is not None: return replay
    profile = await db.scalar(select(NotificationProfile).where(NotificationProfile.id == profile_id, NotificationProfile.workspace_id == actor.workspace_id))
    if not profile: raise HTTPException(404, "notification profile not found")
    if body.get("channel") not in {"in_app", "thread", "discord", "webhook"}: raise HTTPException(422, "unsupported notification channel")
    row = NotificationRoute(workspace_id=actor.workspace_id, profile_id=profile.id, name=body["name"], channel=body["channel"], config=body.get("config") or {}, filters=body.get("filters") or {}, credential_binding_id=body.get("credential_binding_id"))
    db.add(row); await db.flush(); await audit_phase2(db, actor, "notification_route.created", "notification_route", row.id, {"channel": row.channel}); response = {"id": row.id, "workspace_id": row.workspace_id, "profile_id": row.profile_id, "name": row.name, "channel": row.channel, "config": safe_config(row.config), "filters": row.filters, "is_active": row.is_active}; await complete_mutation_key(db, actor, idempotency_key, response); return response


@router.get("/notifications/profiles/{profile_id}/routes")
async def notification_routes(profile_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    rows = (await db.execute(select(NotificationRoute).where(NotificationRoute.profile_id == profile_id, NotificationRoute.workspace_id == actor.workspace_id))).scalars().all()
    return [{"id": row.id, "workspace_id": row.workspace_id, "profile_id": row.profile_id, "name": row.name, "channel": row.channel, "config": safe_config(row.config), "filters": row.filters, "is_active": row.is_active} for row in rows]


@router.get("/dead-letters")
async def dead_letters(db=Depends(get_db), actor=Depends(actor_dep)):
    return (await db.execute(select(DeadLetter).where(DeadLetter.workspace_id == actor.workspace_id).order_by(desc(DeadLetter.created_at)))).scalars().all()


@router.get("/runs/{run_id}/state-diff")
async def run_state_diff(run_id: UUID, db=Depends(get_db), actor=Depends(actor_dep)):
    from app.models.phase2_models import StateDiff
    run = await db.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.workspace_id == actor.workspace_id))
    if not run: raise HTTPException(404, "run not found")
    row = await db.scalar(select(StateDiff).where(StateDiff.run_id == run_id).order_by(StateDiff.created_at.desc()))
    return row or {"run_id": run_id, "diff": {}, "supported": False}


@router.post("/dead-letters/{dead_letter_id}/retry")
async def retry_dead_letter(dead_letter_id: UUID, db=Depends(get_db), actor=Depends(actor_dep), idempotency_key: str | None = Header(None, alias="Idempotency-Key")):
    replay = await claim_mutation_key(db, actor, idempotency_key, f"dead_letter.retry:{dead_letter_id}")
    if replay is not None: return replay
    row = await db.scalar(select(DeadLetter).where(DeadLetter.id == dead_letter_id, DeadLetter.workspace_id == actor.workspace_id).with_for_update())
    if not row: raise HTTPException(404, "dead letter not found")
    if row.status != "open": raise HTTPException(409, "dead letter is not open")
    if row.stage in {"action", "external_action"} or (row.payload or {}).get("outcome_unknown"):
        raise HTTPException(409, "uncertain actions require reconciliation, not retry")
    row.status = "retry_requested"; row.resolution = f"retry requested by {actor.actor_id}"; row.resolved_at = datetime.now(timezone.utc); await audit_phase2(db, actor, "dead_letter.retry_requested", "dead_letter", row.id, {"idempotency_key": idempotency_key})
    client = None
    try:
        from app.api.routes import get_temporal_client
        client = get_temporal_client()
        payload = row.payload or {}
        if client is None:
            row.status = "open"; row.resolution = "retry dispatch unavailable"
        if client and row.stage == "notification" and payload.get("delivery_id"):
            delivery = await db.scalar(select(NotificationDelivery).where(NotificationDelivery.id == UUID(str(payload["delivery_id"]))).with_for_update())
            if not delivery: raise HTTPException(409, "notification delivery is missing")
            delivery.status = "retry"
            from app.workflows.notification_workflow import NotificationDeliveryWorkflow
            from app.config import get_setting
            await client.start_workflow(NotificationDeliveryWorkflow.run, {"delivery_id": str(payload["delivery_id"]), "mode": payload.get("mode", "autonomous")}, id=f"notification:{payload['delivery_id']}:retry:{row.attempts + 1}", task_queue=get_setting("NOTIFICATION_TASK_QUEUE") or "threadbot-notifications")
            row.status = "redispatched"
        elif client and row.stage == "connector" and payload.get("connector_id"):
            from app.activities.connector_activities import poll_connector
            from app.config import get_setting
            connector_payload = {
                "connector_id": str(payload["connector_id"]),
                "subject_key": payload.get("subject_key", "default"),
                "max_events": min(int(payload.get("max_events", 100)), 100),
                "mode": payload.get("mode", "autonomous"),
            }
            await client.execute_activity(
                poll_connector,
                connector_payload,
                id=f"dead-letter:{dead_letter_id}:connector-retry",
                task_queue=get_setting("CONNECTOR_TASK_QUEUE") or "threadbot-connectors",
                start_to_close_timeout=timedelta(seconds=60),
            )
            row.status = "redispatched"
    except HTTPException:
        raise
    except Exception as exc:
        row.status = "open"; row.resolution = f"retry dispatch failed: {str(exc)[:300]}"
    response = row
    await complete_mutation_key(db, actor, idempotency_key, response)
    return response
