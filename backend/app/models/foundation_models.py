import uuid
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.models.models import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Principal(Base):
    __tablename__ = "principals"
    __table_args__ = (UniqueConstraint("workspace_id", "actor_type", "actor_id"), Index("idx_principals_workspace", "workspace_id"))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    actor_type = Column(String(32), nullable=False)
    actor_id = Column(String(255), nullable=False)
    display_name = Column(String(255))
    roles = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ApiToken(Base):
    __tablename__ = "api_tokens"
    __table_args__ = (Index("idx_api_tokens_workspace", "workspace_id"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(String(255), nullable=False)
    token_hash = Column(Text, nullable=False)
    token_prefix = Column(String(16), nullable=False)
    roles = Column(JSONB, nullable=False, server_default=text("'[\"admin\"]'::jsonb"))
    expires_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("idx_audit_events_workspace_created", "workspace_id", "created_at"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    actor_type = Column(String(32), nullable=False)
    actor_id = Column(String(255), nullable=False)
    action = Column(String(255), nullable=False)
    resource_type = Column(String(255))
    resource_id = Column(String(255))
    metadata_ = Column("metadata", JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    correlation_id = Column(UUID(as_uuid=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DomainEvent(Base):
    __tablename__ = "domain_events"
    __table_args__ = (UniqueConstraint("workspace_id", "dedupe_key"), Index("idx_domain_events_cursor", "workspace_id", "sequence"))
    sequence = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(UUID(as_uuid=True), default=uuid.uuid4, server_default=func.gen_random_uuid(), unique=True, nullable=False)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    event_type = Column(String(255), nullable=False)
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    dedupe_key = Column(String(255))
    correlation_id = Column(UUID(as_uuid=True), nullable=False)
    causation_id = Column(UUID(as_uuid=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class OutboxMessage(Base):
    __tablename__ = "outbox_messages"
    __table_args__ = (Index("idx_outbox_pending", "available_at", "locked_at"), Index("idx_outbox_claimable", "status", "available_at", "locked_at"), UniqueConstraint("workspace_id", "idempotency_key"))
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    event_id = Column(UUID(as_uuid=True), nullable=True)
    topic = Column(String(255), nullable=False)
    payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    idempotency_key = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, server_default="pending")
    attempts = Column(Integer, nullable=False, server_default="0")
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_at = Column(DateTime(timezone=True))
    published_at = Column(DateTime(timezone=True))
    claimed_by = Column(String(255))
    last_error = Column(Text)
    failed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("workspace_id", "key"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    key = Column(String(255), nullable=False)
    operation = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False, server_default="in_progress")
    response = Column(JSONB)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Credential(Base):
    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    provider = Column(String(255), nullable=False)
    active_version_id = Column(UUID(as_uuid=True), ForeignKey("credential_versions.id", name="fk_credentials_active_version_id_credential_versions", ondelete="SET NULL", use_alter=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CredentialVersion(Base):
    __tablename__ = "credential_versions"
    __table_args__ = (UniqueConstraint("credential_id", "version"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    credential_id = Column(UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    ciphertext = Column(Text, nullable=False)
    algorithm = Column(String(64), nullable=False, server_default="fernet-v1")
    key_id = Column(String(255))
    has_secret = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CredentialBinding(Base):
    __tablename__ = "credential_bindings"
    __table_args__ = (UniqueConstraint("workspace_id", "credential_id", "binding_key"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    credential_id = Column(UUID(as_uuid=True), ForeignKey("credentials.id", ondelete="CASCADE"), nullable=False)
    binding_key = Column(String(255), nullable=False)
    constraints = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    is_active = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
