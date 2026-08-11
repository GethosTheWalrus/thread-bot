import uuid

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.models.models import Base


class OsrsLoadout(Base):
    __tablename__ = "osrs_loadouts"
    __table_args__ = (
        Index("idx_osrs_loadouts_workspace", "workspace_id"),
        Index("uq_osrs_loadouts_workspace_name", "workspace_id", text("lower(name)"), unique=True),
        Index("uq_osrs_loadouts_workspace_default", "workspace_id", unique=True,
              postgresql_where=text("is_default = true")),
        CheckConstraint("schema_version = 1", name="ck_osrs_loadouts_schema_version"),
        CheckConstraint("source_type IN ('manual', 'wiki', 'clone')", name="ck_osrs_loadouts_source_type"),
        CheckConstraint("revision > 0", name="ck_osrs_loadouts_revision"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String(2000), nullable=True)
    payload = Column(JSONB, nullable=False)
    schema_version = Column(Integer, nullable=False, server_default="1")
    source_type = Column(String(16), nullable=False, server_default="manual")
    source_ref = Column(String(2000), nullable=True)
    engine_revision = Column(String(255), nullable=True)
    created_by_actor_type = Column(String(32), nullable=False)
    created_by_actor_id = Column(String(255), nullable=False)
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    is_default = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class ThreadOsrsLoadout(Base):
    __tablename__ = "thread_osrs_loadouts"
    __table_args__ = (UniqueConstraint("workspace_id", "thread_id", name="uq_thread_osrs_loadout_thread"),
                      Index("idx_thread_osrs_loadouts_thread", "workspace_id", "thread_id"))

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    loadout_id = Column(UUID(as_uuid=True), ForeignKey("osrs_loadouts.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
