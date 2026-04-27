from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional


class MessageCreate(BaseModel):
    role: str = Field(..., description="Role: user or assistant")
    content: str = Field(..., description="Message content")


class ThreadCreateRequest(BaseModel):
    title: str = Field(default="New Thread", description="Thread title")
    parent_id: Optional[UUID] = Field(None, description="Parent thread ID for branching")


class ChatRequest(BaseModel):
    content: str = Field(..., description="User message content")
    thread_id: Optional[str] = Field(None, description="Existing thread ID to continue conversation")
    parent_id: Optional[UUID] = Field(None, description="Parent thread ID for branching")
    llm_api_url: Optional[str] = Field(None, description="Override LLM API URL")
    llm_api_key: Optional[str] = Field(None, description="Override LLM API Key")
    llm_model: Optional[str] = Field(None, description="Override LLM model")


class MessageResponse(BaseModel):
    id: UUID
    thread_id: UUID
    role: str
    content: str
    created_at: datetime
    metadata: Optional[dict] = None

    model_config = {"from_attributes": True}


class ThreadResponse(BaseModel):
    id: UUID
    title: str
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = []

    model_config = {"from_attributes": True}


class ThreadListItem(BaseModel):
    id: UUID
    title: str
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ThreadListResponse(BaseModel):
    threads: list[ThreadListItem]


class SettingsResponse(BaseModel):
    llm_model: str
    llm_api_url: str
    llm_temperature: float
    llm_max_tokens: int
    has_api_key: bool


class RenameRequest(BaseModel):
    title: str
