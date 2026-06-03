from sqlalchemy import Column, String, DateTime, Text, ForeignKey, func, Boolean
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
import uuid


class Base(DeclarativeBase):
    pass


class Thread(Base):
    __tablename__ = "threads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False, default="New Thread")
    parent_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    messages = relationship("Message", back_populates="thread", cascade="all, delete-orphan", order_by="Message.created_at")
    parent = relationship("Thread", remote_side=[id], foreign_keys=[parent_id])


class Message(Base):
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id"), nullable=False)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    metadata_ = Column("metadata", JSONB, nullable=True, default={})

    thread = relationship("Thread", back_populates="messages")


class Setting(Base):
    __tablename__ = "settings"

    key = Column(String(255), primary_key=True)
    value = Column(Text, nullable=False)


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
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DiscordThreadLink(Base):
    __tablename__ = "discord_thread_links"

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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    thread = relationship("Thread", foreign_keys=[thread_id])


class DiscordServer(Base):
    __tablename__ = "discord_servers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id = Column(String(255), nullable=False, unique=True)
    guild_name = Column(String(255), nullable=False)
    default_channel_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DiscordServerToolOverride(Base):
    __tablename__ = "discord_server_tool_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    guild_id = Column(String(255), ForeignKey("discord_servers.guild_id", ondelete="CASCADE"), nullable=False)
    server_id = Column(UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(255), nullable=True)  # null = server-level override
    enabled = Column(Boolean, nullable=False, default=False)

    guild = relationship("DiscordServer", foreign_keys=[guild_id])
    server = relationship("MCPServer", foreign_keys=[server_id])


class ThreadToolOverride(Base):
    __tablename__ = "thread_tool_overrides"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id = Column(UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    server_id = Column(UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), nullable=False)
    tool_name = Column(String(255), nullable=True)  # null = server-level override
    enabled = Column(Boolean, nullable=False, default=True)

    thread = relationship("Thread", foreign_keys=[thread_id])
    server = relationship("MCPServer", foreign_keys=[server_id])
