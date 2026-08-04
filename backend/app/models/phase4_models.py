import uuid
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.models.models import Base


def _id():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class ReplaySession(Base):
    __tablename__ = "replay_sessions"
    __table_args__ = (Index("idx_replay_sessions_source", "workspace_id", "source_run_id"), CheckConstraint("mode IN ('recorded','reexecution')"))
    id = _id()
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    source_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False)
    replay_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"))
    agent_version_id = Column(UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False)
    mode = Column(String(16), nullable=False)
    effect_free = Column(Boolean, nullable=False, server_default="true")
    timeline = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    comparison = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CanaryDeployment(Base):
    __tablename__ = "canary_deployments"
    __table_args__ = (Index("idx_canary_deployments_agent_status", "agent_id", "status"), CheckConstraint("status IN ('draft','active','promoted','rolled_back','paused')"))
    id = _id()
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False)
    stable_version_id = Column(UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False)
    candidate_version_id = Column(UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False)
    cohort = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    status = Column(String(16), nullable=False, server_default="draft")
    version = Column(Integer, nullable=False, server_default="1")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CanaryComparison(Base):
    __tablename__ = "canary_comparisons"
    __table_args__ = (UniqueConstraint("deployment_id", "candidate_run_id", "stable_run_id"),
                      Index("idx_canary_comparisons_deployment", "deployment_id", "created_at"))
    id = _id()
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    deployment_id = Column(UUID(as_uuid=True), ForeignKey("canary_deployments.id", ondelete="CASCADE"), nullable=False)
    candidate_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False)
    stable_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=True)
    metrics = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CanaryAssignment(Base):
    __tablename__ = "canary_assignments"
    __table_args__ = (UniqueConstraint("deployment_id", "run_id"), CheckConstraint("length(trim(bucket)) > 0"), Index("idx_canary_assignments_workspace", "workspace_id", "deployment_id"))
    id = _id()
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    deployment_id = Column(UUID(as_uuid=True), ForeignKey("canary_deployments.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False)
    bucket = Column(String(64), nullable=False)
    assigned_version_id = Column(UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ForecastSnapshot(Base):
    __tablename__ = "forecast_snapshots"
    id = _id()
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    horizon_hours = Column(Integer, nullable=False)
    forecast = Column(JSONB, nullable=False)
    assumptions = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    confidence = Column(String(16), nullable=False, server_default="low")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RecoveryOperation(Base):
    __tablename__ = "recovery_operations"
    __table_args__ = (Index("idx_recovery_operations_workspace", "workspace_id", "created_at"),)
    id = _id()
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    actor_id = Column(String(255), nullable=False)
    operation = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(255), nullable=False)
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SLOAlert(Base):
    __tablename__ = "slo_alerts"
    __table_args__ = (UniqueConstraint("workspace_id", "alert_key"),)
    id = _id()
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    alert_key = Column(String(255), nullable=False)
    metric = Column(String(64), nullable=False)
    threshold = Column(Integer, nullable=False)
    status = Column(String(16), nullable=False, server_default="ok")
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SLOMetric(Base):
    __tablename__ = "slo_metrics"
    __table_args__ = (Index("idx_slo_metrics_workspace_metric", "workspace_id", "metric", "observed_at"),)
    id = _id()
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    metric = Column(String(64), nullable=False)
    value = Column(Integer, nullable=False)
    details = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    observed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class QueueControl(Base):
    __tablename__ = "queue_controls"
    __table_args__ = (UniqueConstraint("workspace_id", "queue_name"),)
    id = _id()
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    queue_name = Column(String(255), nullable=False)
    state = Column(String(16), nullable=False, server_default="running")
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
