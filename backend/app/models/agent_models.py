import uuid
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.models.models import Base


def _id():
    return Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class AgentTemplate(Base):
    __tablename__ = "agent_templates"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)
    id = _id(); workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False); description = Column(Text); status = Column(String(32), nullable=False, server_default="active")
    schema_version = Column(Integer, nullable=False, server_default="1"); definition = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now()); updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AgentTemplateVersion(Base):
    __tablename__ = "agent_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version"), UniqueConstraint("template_id", "config_hash"))
    id = _id(); template_id = Column(UUID(as_uuid=True), ForeignKey("agent_templates.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False); schema_version = Column(Integer, nullable=False); definition = Column(JSONB, nullable=False)
    config_hash = Column(String(64), nullable=False); created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (Index("uq_agents_thread_handle_ci", "thread_id", text("lower(handle)"), unique=True), Index("uq_agents_thread_moderator", "thread_id", unique=True, postgresql_where=text("is_moderator")), CheckConstraint("concurrency_limit > 0"), CheckConstraint("queue_limit >= 0"), CheckConstraint("status IN ('draft','active','paused','archived')"), CheckConstraint("execution_mode IN ('observe','recommend','act')"))
    id = _id(); workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False); thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="RESTRICT"), nullable=False)
    name = Column(String(255), nullable=False); handle = Column(String(255), nullable=False, server_default="moderator"); description = Column(Text); status = Column(String(32), nullable=False, server_default="draft"); execution_mode = Column(String(32), nullable=False, server_default="observe"); is_moderator = Column(Boolean, nullable=False, server_default="false")
    active_version_id = Column(UUID(as_uuid=True), ForeignKey("agent_versions.id", name="fk_agents_active_version_id_agent_versions", ondelete="SET NULL", use_alter=True), nullable=True); template_id = Column(UUID(as_uuid=True), ForeignKey("agent_templates.id", ondelete="SET NULL")); concurrency_limit = Column(Integer, nullable=False, server_default="1"); queue_limit = Column(Integer, nullable=False, server_default="100")
    created_by_type = Column(String(32), nullable=False); created_by_id = Column(String(255), nullable=False); created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now()); updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentVersionDraft(Base):
    __tablename__ = "agent_version_drafts"
    id = _id(); agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False); version = Column(Integer, nullable=False, server_default="1"); schema_version = Column(Integer, nullable=False, server_default="1"); config = Column(JSONB, nullable=False); prompt_template = Column(Text, nullable=False); tool_selection = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")); skill_selection = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")); credential_bindings = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")); config_hash = Column(String(64), nullable=False); created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now()); updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_versions_agent_version"), UniqueConstraint("agent_id", "config_hash", name="uq_agent_versions_config_hash"))
    id = _id(); agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False); version = Column(Integer, nullable=False); schema_version = Column(Integer, nullable=False); config = Column(JSONB, nullable=False); prompt_template = Column(Text, nullable=False); tool_selection = Column(JSONB, nullable=False); skill_selection = Column(JSONB, nullable=False); policy_set_id = Column(UUID(as_uuid=True), ForeignKey("policy_sets.id", name="fk_agent_versions_policy_set_id_policy_sets", ondelete="SET NULL", use_alter=True)); budget_profile_id = Column(UUID(as_uuid=True), ForeignKey("budget_profiles.id", name="fk_agent_versions_budget_profile_id_budget_profiles", ondelete="SET NULL", use_alter=True)); credential_bindings = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")); config_hash = Column(String(64), nullable=False); created_by_type = Column(String(32), nullable=False); created_by_id = Column(String(255), nullable=False); created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AgentTrigger(Base):
    __tablename__ = "agent_triggers"
    __table_args__ = (Index("idx_agent_triggers_agent", "agent_id"), CheckConstraint("trigger_type IN ('manual','schedule','webhook','poller','discord','temporal','reachy','agent_handoff')"))
    id = _id(); workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False); agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False); trigger_type = Column(String(32), nullable=False); config = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")); is_active = Column(Boolean, nullable=False, server_default="true"); created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now()); updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class TriggerEvent(Base):
    __tablename__ = "trigger_events"
    __table_args__ = (UniqueConstraint("workspace_id", "source", "dedupe_key", name="uq_trigger_events_dedupe"), Index("idx_trigger_events_agent_received", "agent_id", "received_at"))
    id = _id(); workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False); agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL")); trigger_id = Column(UUID(as_uuid=True), ForeignKey("agent_triggers.id", ondelete="SET NULL")); schema_version = Column(Integer, nullable=False, server_default="1"); source = Column(String(32), nullable=False); event_type = Column(String(255), nullable=False); subject = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")); occurred_at = Column(DateTime(timezone=True), nullable=False); received_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now()); dedupe_key = Column(String(512), nullable=False); correlation_id = Column(UUID(as_uuid=True), nullable=False); causation_id = Column(UUID(as_uuid=True)); origin_chain = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb")); trust = Column(String(32), nullable=False); payload = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")); content_refs = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))


class AgentHeartbeat(Base):
    __tablename__ = "agent_heartbeats"
    __table_args__ = (
        Index("idx_agent_heartbeats_status_wake", "workspace_id", "operational_status", "next_wake_at"),
        Index("idx_agent_heartbeats_thread_enabled", "thread_id", "enabled"),
        CheckConstraint("min_wake_seconds BETWEEN 30 AND 86400", name="ck_agent_heartbeats_min_wake"),
        CheckConstraint("max_wake_seconds BETWEEN 30 AND 604800", name="ck_agent_heartbeats_max_wake"),
        CheckConstraint("min_wake_seconds <= max_wake_seconds", name="ck_agent_heartbeats_min_le_max"),
        CheckConstraint("idle_backoff_factor BETWEEN 1.0 AND 10.0", name="ck_agent_heartbeats_backoff"),
        CheckConstraint("consecutive_noops >= 0", name="ck_agent_heartbeats_noops"),
        CheckConstraint("operational_status IN ('disabled','scheduled','evaluating','paused','blocked_mode','blocked_archived','blocked_global','error')", name="ck_agent_heartbeats_status"),
        CheckConstraint("last_decision IS NULL OR last_decision IN ('response','action','delegate','no_op')", name="ck_agent_heartbeats_decision"),
    )
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), primary_key=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    enabled = Column(Boolean, nullable=False, server_default="false")
    min_wake_seconds = Column(Integer, nullable=False, server_default="300")
    max_wake_seconds = Column(Integer, nullable=False, server_default="3600")
    idle_backoff_factor = Column(Numeric(5, 2), nullable=False, server_default="2.0")
    revision = Column(Integer, nullable=False, server_default="1")
    operational_status = Column(String(32), nullable=False, server_default="disabled")
    workflow_id = Column(String(255), nullable=True)
    last_wake_at = Column(DateTime(timezone=True), nullable=True)
    last_completed_at = Column(DateTime(timezone=True), nullable=True)
    next_wake_at = Column(DateTime(timezone=True), nullable=True)
    last_decision = Column(String(32), nullable=True)
    last_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    consecutive_noops = Column(Integer, nullable=False, server_default="0")
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
