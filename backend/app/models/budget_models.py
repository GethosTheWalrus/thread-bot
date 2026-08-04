import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.models.models import Base
def _id(): return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
class BudgetProfile(Base):
    __tablename__="budget_profiles"; __table_args__=(UniqueConstraint("workspace_id","name"),)
    id=_id(); workspace_id=Column(UUID(as_uuid=True),ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False); name=Column(String(255),nullable=False); limits=Column(JSONB,nullable=False,server_default=text("'{}'::jsonb")); created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now())
class BudgetBucket(Base):
    __tablename__="budget_buckets"; __table_args__=(UniqueConstraint("workspace_id","profile_id","period_start","bucket"),)
    id=_id(); workspace_id=Column(UUID(as_uuid=True),ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False); profile_id=Column(UUID(as_uuid=True),ForeignKey("budget_profiles.id",ondelete="CASCADE"),nullable=False); bucket=Column(String(64),nullable=False); period_start=Column(DateTime(timezone=True),nullable=False); hard_limit=Column(Integer,nullable=False); used=Column(Integer,nullable=False,server_default="0"); reserved=Column(Integer,nullable=False,server_default="0")
class BudgetReservation(Base):
    __tablename__="budget_reservations"; __table_args__=(UniqueConstraint("workspace_id","reservation_key"),)
    id=_id(); workspace_id=Column(UUID(as_uuid=True),ForeignKey("workspaces.id",ondelete="CASCADE"),nullable=False); run_id=Column(UUID(as_uuid=True),ForeignKey("agent_runs.id",ondelete="CASCADE")); bucket_id=Column(UUID(as_uuid=True),ForeignKey("budget_buckets.id",ondelete="CASCADE"),nullable=False); reservation_key=Column(String(255),nullable=False); amount=Column(Integer,nullable=False); status=Column(String(32),nullable=False,server_default="reserved"); created_at=Column(DateTime(timezone=True),nullable=False,server_default=func.now()); expires_at=Column(DateTime(timezone=True))
