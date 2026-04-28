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
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
