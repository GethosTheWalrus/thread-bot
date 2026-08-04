import uuid
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.models.models import Base


class Connector(Base):
    __tablename__ = "connectors"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_connectors_workspace_name"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    connector_type = Column(String(32), nullable=False)
    config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    credential_binding_id = Column(UUID(as_uuid=True), ForeignKey("credential_bindings.id", ondelete="SET NULL"))
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ConnectorCursor(Base):
    __tablename__ = "connector_cursors"
    __table_args__ = (UniqueConstraint("connector_id", "subject_key", name="uq_connector_cursors_subject"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    connector_id = Column(UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    subject_key = Column(String(512), nullable=False)
    cursor = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    fingerprint = Column(String(64))
    last_event_at = Column(DateTime(timezone=True))
    cooldown_until = Column(DateTime(timezone=True))
    suppressed_count = Column(Integer, nullable=False, server_default="0")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class WebhookNonce(Base):
    __tablename__ = "webhook_nonces"
    __table_args__ = (UniqueConstraint("connector_id", "nonce", name="uq_webhook_nonces_connector_nonce"), Index("idx_webhook_nonces_expires", "expires_at"))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    connector_id = Column(UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False)
    nonce = Column(String(255), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NotificationProfile(Base):
    __tablename__ = "notification_profiles"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_notification_profiles_workspace_name"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    routes = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NotificationRoute(Base):
    __tablename__ = "notification_routes"
    __table_args__ = (UniqueConstraint("profile_id", "name", name="uq_notification_routes_profile_name"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("notification_profiles.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    channel = Column(String(32), nullable=False)
    config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    filters = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    credential_binding_id = Column(UUID(as_uuid=True), ForeignKey("credential_bindings.id", ondelete="SET NULL"))
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("workspace_id", "business_key", name="uq_notification_deliveries_business"),
        Index("idx_notification_deliveries_status", "status", "available_at"),
        Index("idx_notification_deliveries_claim_expiry", "status", "claim_expires_at"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("notification_profiles.id", ondelete="SET NULL"))
    route = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    event_type = Column(String(255), nullable=False)
    business_key = Column(String(512), nullable=False)
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String(32), nullable=False, server_default="pending")
    attempts = Column(Integer, nullable=False, server_default="0")
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    claimed_at = Column(DateTime(timezone=True))
    claim_expires_at = Column(DateTime(timezone=True))
    last_error = Column(Text)
    delivered_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DeadLetter(Base):
    __tablename__ = "dead_letters"
    __table_args__ = (Index("idx_dead_letters_workspace_status", "workspace_id", "status"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(64), nullable=False)
    reason = Column(String(255), nullable=False)
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    attempts = Column(Integer, nullable=False, server_default="0")
    status = Column(String(32), nullable=False, server_default="open")
    resolution = Column(Text)
    resolved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StateDiff(Base):
    __tablename__ = "state_diffs"
    __table_args__ = (Index("idx_state_diffs_run_created", "run_id", "created_at"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False)
    before_hash = Column(String(64), nullable=False)
    after_hash = Column(String(64), nullable=False)
    diff = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
