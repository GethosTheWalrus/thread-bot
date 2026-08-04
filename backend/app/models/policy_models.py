import uuid
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.models.models import Base
def _id(): return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
class ToolRiskProfile(Base):
    __tablename__="tool_risk_profiles"; __table_args__=(UniqueConstraint("workspace_id","tool_identity"), CheckConstraint("risk_level IN ('low','medium','high','critical','unknown')"),)
    id=_id(); workspace_id=Column(UUID(as_uuid=True),ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False); tool_identity=Column(String(512),nullable=False); category=Column(String(32),nullable=False); risk_level=Column(String(32),nullable=False,server_default="unknown"); dry_run_supported=Column(Integer,nullable=False,server_default="0"); state_diff_supported=Column(Integer,nullable=False,server_default="0"); idempotency_supported=Column(Integer,nullable=False,server_default="0"); timeout_seconds=Column(Integer); credential_scope=Column(JSONB,nullable=False,server_default=text("'{}'::jsonb")); created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
class PolicySet(Base):
    __tablename__="policy_sets"; __table_args__=(UniqueConstraint("workspace_id","name"),)
    id=_id(); workspace_id=Column(UUID(as_uuid=True),ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False); name=Column(String(255),nullable=False); active_version_id=Column(UUID(as_uuid=True),ForeignKey("policy_versions.id",name="fk_policy_sets_active_version_id_policy_versions",ondelete="SET NULL",use_alter=True)); created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
class PolicyVersion(Base):
    __tablename__="policy_versions"; __table_args__=(UniqueConstraint("policy_set_id","version"),UniqueConstraint("policy_set_id","config_hash"))
    id=_id(); policy_set_id=Column(UUID(as_uuid=True),ForeignKey("policy_sets.id",ondelete="CASCADE"),nullable=False); version=Column(Integer,nullable=False); config_hash=Column(String(64),nullable=False); created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
class PolicyRule(Base):
    __tablename__="policy_rules"; __table_args__=(UniqueConstraint("policy_version_id","ordinal"), CheckConstraint("effect IN ('deny','require_approval','allow')"),)
    id=_id(); policy_version_id=Column(UUID(as_uuid=True),ForeignKey("policy_versions.id",ondelete="CASCADE"),nullable=False); ordinal=Column(Integer,nullable=False); scope=Column(String(255),nullable=False); priority=Column(Integer,nullable=False); effect=Column(String(32),nullable=False); conditions=Column(JSONB,nullable=False,server_default=text("'{}'::jsonb")); created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
