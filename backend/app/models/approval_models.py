import uuid
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.models.models import Base

class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (UniqueConstraint("run_id", "action_id", "action_revision", name="uq_approval_requests_action"),)
    id=Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4); workspace_id=Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False); run_id=Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False); action_id=Column(String(128), nullable=False); action_revision=Column(Integer, nullable=False); tool_identity=Column(String(512)); request_hash=Column(String(64), nullable=False); status=Column(String(32), nullable=False, server_default="pending"); policy_ref=Column(String(255)); credential_ref=Column(String(255)); risk_level=Column(String(32), nullable=False, server_default="unknown"); target=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")); redacted_arguments=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")); policy_explanation=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")); expires_at=Column(DateTime(timezone=True), nullable=False); consumed_at=Column(DateTime(timezone=True)); created_at=Column(DateTime(timezone=True), nullable=False, server_default=func.now())

class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"
    __table_args__ = (UniqueConstraint("request_id", name="uq_approval_decisions_request"),)
    id=Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4); request_id=Column(UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False); decision=Column(String(16), nullable=False); actor_id=Column(String(255), nullable=False); actor_type=Column(String(32), nullable=False, server_default="human"); channel=Column(String(32), nullable=False, server_default="web"); reason=Column(Text); provider_interaction_id=Column(String(255)); created_at=Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ApprovalProviderPrompt(Base):
    __tablename__ = "approval_provider_prompts"
    __table_args__ = (
        UniqueConstraint("channel", "provider_channel_id", "provider_message_id", name="uq_approval_provider_prompt_message"),
        Index("idx_approval_provider_prompts_request", "request_id", "created_at"),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False)
    channel = Column(String(32), nullable=False, server_default="discord")
    provider_channel_id = Column(String(255), nullable=False)
    provider_message_id = Column(String(255), nullable=False)
    intended_actor_id = Column(String(255))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
