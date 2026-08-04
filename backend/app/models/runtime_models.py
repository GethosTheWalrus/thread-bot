import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.models.models import Base


class RuntimeConfigSnapshot(Base):
    __tablename__ = "runtime_config_snapshots"
    __table_args__ = (UniqueConstraint("workspace_id", "config_hash", name="uq_runtime_snapshots_workspace_hash"),)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    schema_version = Column(Integer, nullable=False)
    config = Column(JSONB, nullable=False)
    model_credential_binding_id = Column(UUID(as_uuid=True), ForeignKey("credential_bindings.id", ondelete="RESTRICT"))
    config_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
