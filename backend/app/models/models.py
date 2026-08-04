from sqlalchemy import Column, String, DateTime, Text, ForeignKey, func, Boolean, LargeBinary, UniqueConstraint, Integer, Index, text, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
import uuid


class Base(DeclarativeBase):
    pass


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (
        Index("idx_threads_parent_id", "parent_id"),
        Index("idx_threads_created_at", text("created_at DESC")),
        Index("idx_threads_workspace_updated", "workspace_id", text("updated_at DESC")),
        CheckConstraint("mode IN ('chat', 'agent')", name="ck_threads_mode"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False, default="New Thread")
    parent_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    llm_overrides = Column(JSONB, nullable=True, default=None)
    is_pinned = Column(Boolean, nullable=False, default=False, server_default="false")
    completed_turns = Column(Integer, nullable=False, default=0, server_default="0")
    conversation_summary = Column(Text, nullable=True)
    conversation_summary_updated_at = Column(DateTime(timezone=True), nullable=True)
    conversation_summary_turn_count = Column(Integer, nullable=False, default=0, server_default="0")
    mode = Column(String(16), nullable=False, default="chat", server_default="chat")
    archived_at = Column(DateTime(timezone=True), nullable=True)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True)
    agent_turn_limit = Column(Integer, nullable=False, default=4, server_default="4")

    messages = relationship("Message", back_populates="thread", cascade="all, delete-orphan", order_by="Message.created_at")
    parent = relationship("Thread", remote_side=[id], foreign_keys=[parent_id])


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_thread_id", "thread_id"),
        Index("idx_messages_created_at", "created_at"),
        Index("idx_messages_agent_handle", "thread_id", "agent_handle"),
        Index("idx_messages_agent_run", "agent_run_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    metadata_ = Column("metadata", JSONB, nullable=True, default={}, server_default=text("'{}'::jsonb"))
    agent_id = Column(UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    agent_version_id = Column(UUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL"), nullable=True)
    agent_run_id = Column(UUID(as_uuid=True), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    agent_handle = Column(String(255), nullable=True)

    thread = relationship("Thread", back_populates="messages")


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(255), primary_key=True)
    value = Column(Text, nullable=False)


class GeneratedImage(Base):
    __tablename__ = "generated_images"

    filename = Column(String(255), primary_key=True)
    content = Column(LargeBinary, nullable=False)
    content_type = Column(String(100), nullable=False, default="image/png")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GeneratedMedia(Base):
    __tablename__ = "generated_media"

    filename = Column(String(255), primary_key=True)
    content = Column(LargeBinary, nullable=False)
    content_type = Column(String(100), nullable=False, default="video/mp4")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    image = Column(String(255), nullable=False)
    env_vars = Column(JSONB, nullable=True, default={})
    args = Column(JSONB, nullable=True, default={})
    registry_credentials = Column(JSONB, nullable=True, default={})
    is_active = Column(Boolean, default=True)
    cached_tools = Column(JSONB, nullable=True, default=None)  # [{name, description}] from last test
    cached_tools_at = Column(DateTime(timezone=True), nullable=True, default=None)  # last time the cache was refreshed
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Skill(Base):
    __tablename__ = "skills"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True, default="")
    content = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class DiscordThreadLink(Base):
    __tablename__ = "discord_thread_links"
    __table_args__ = (
        Index("idx_discord_thread_links_thread_id", "thread_id"),
        Index("idx_discord_thread_links_discord_thread_id", "discord_thread_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False, unique=True)
    guild_id = Column(String(255), nullable=False)
    channel_id = Column(String(255), nullable=False)
    discord_thread_id = Column(String(255), nullable=False, unique=True)
    discord_thread_name = Column(String(255), nullable=False)
    last_discord_message_id = Column(String(255), nullable=True)
    indexed_discord_message_id = Column(String(255), nullable=True)
    indexed_at = Column(DateTime(timezone=True), nullable=True)
    indexing_status = Column(String(50), nullable=True)
    indexing_error = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    thread = relationship("Thread", foreign_keys=[thread_id])


class DiscordServer(Base):
    __tablename__ = "discord_servers"
    __table_args__ = (Index("idx_discord_servers_guild_id", "guild_id"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id = Column(String(255), nullable=False, unique=True)
    guild_name = Column(String(255), nullable=False)
    default_channel_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class DiscordServerToolOverride(Base):
    __tablename__ = "discord_server_tool_overrides"
    __table_args__ = (
        Index("idx_discord_server_tool_overrides_guild_id", "guild_id"),
        UniqueConstraint("guild_id", "server_id", "tool_name", name="uq_discord_server_tool_overrides_scope"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id = Column(String(255), ForeignKey("discord_servers.guild_id", ondelete="CASCADE"), nullable=False)
    server_id = Column(UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(255), nullable=True)  # null = server-level override
    enabled = Column(Boolean, nullable=False, default=False)

    guild = relationship("DiscordServer", foreign_keys=[guild_id])
    server = relationship("MCPServer", foreign_keys=[server_id])


class ThreadToolOverride(Base):
    __tablename__ = "thread_tool_overrides"
    __table_args__ = (
        UniqueConstraint("thread_id", "server_id", "tool_name"),
        Index("idx_thread_tool_overrides_thread_id", "thread_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    server_id = Column(UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(255), nullable=True)  # null = server-level override
    enabled = Column(Boolean, nullable=False, default=True)

    thread = relationship("Thread", foreign_keys=[thread_id])
    server = relationship("MCPServer", foreign_keys=[server_id])


class ThreadSkillOverride(Base):
    __tablename__ = "thread_skill_overrides"
    __table_args__ = (
        UniqueConstraint("thread_id", "skill_id"),
        Index("idx_thread_skill_overrides_thread_id", "thread_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid())
    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    skill_id = Column(UUID(as_uuid=True), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)

    thread = relationship("Thread", foreign_keys=[thread_id])
    skill = relationship("Skill", foreign_keys=[skill_id])
