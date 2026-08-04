import uuid
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.models.models import Base


def _id():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class HandoffContract(Base):
    __tablename__ = "handoff_contracts"
    __table_args__ = (UniqueConstraint("workspace_id", "name", "version"),)
    id = _id(); workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False); version = Column(Integer, nullable=False)
    source_capability = Column(String(255), nullable=False); target_capability = Column(String(255), nullable=False)
    input_schema = Column(JSONB, nullable=False); output_schema = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    target_allowlist = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")); artifact_classifications = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    timeout_seconds = Column(Integer, nullable=False, server_default="300"); max_depth = Column(Integer, nullable=False, server_default="3")
    is_active = Column(Boolean, nullable=False, server_default="true"); status = Column(String(16), nullable=False, server_default="draft"); lifecycle_version = Column(Integer, nullable=False, server_default="1"); created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now()); updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AgentHandoff(Base):
    __tablename__ = "agent_handoffs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"), Index("idx_handoffs_target_status", "target_agent_id", "status"))
    id = _id(); workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    contract_id = Column(UUID(as_uuid=True), ForeignKey("handoff_contracts.id", ondelete="RESTRICT"), nullable=False)
    source_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False); target_agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    input_payload = Column(JSONB, nullable=False); output_payload = Column(JSONB); origin_chain = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")); hop_count = Column(Integer, nullable=False, server_default="0")
    idempotency_key = Column(String(255), nullable=False); status = Column(String(32), nullable=False, server_default="pending"); response_mode = Column(String(16), nullable=False, server_default="async")
    acknowledgement_deadline = Column(DateTime(timezone=True)); completion_deadline = Column(DateTime(timezone=True)); acknowledged_at = Column(DateTime(timezone=True)); completed_at = Column(DateTime(timezone=True)); created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class HandoffEscalation(Base):
    __tablename__ = "handoff_escalations"
    __table_args__ = (UniqueConstraint("handoff_id", "stage"),)
    id = _id(); workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False); handoff_id = Column(UUID(as_uuid=True), ForeignKey("agent_handoffs.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(64), nullable=False); target_type = Column(String(32), nullable=False); target_id = Column(String(255), nullable=False); status = Column(String(16), nullable=False, server_default="pending"); fired_at = Column(DateTime(timezone=True)); created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class PolicyRecommendation(Base):
    __tablename__ = "policy_recommendations"
    __table_args__ = (CheckConstraint("status IN ('pending','accepted','rejected')"),)
    id = _id(); workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False); evidence = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")); proposed_diff = Column(JSONB, nullable=False); risk = Column(String(32), nullable=False); status = Column(String(16), nullable=False, server_default="pending"); accepted_draft_id = Column(UUID(as_uuid=True)); created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now()); decided_at = Column(DateTime(timezone=True))


class ArtifactTombstone(Base):
    __tablename__ = "artifact_tombstones"
    id = _id(); workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False); artifact_id = Column(UUID(as_uuid=True), nullable=False, unique=True); sha256 = Column(String(64), nullable=False); reason = Column(String(255), nullable=False); deleted_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
