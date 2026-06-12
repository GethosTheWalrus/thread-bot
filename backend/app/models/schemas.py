from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional


class ToolOverrideItem(BaseModel):
    server_id: str
    tool_name: Optional[str] = None  # null = server-level override
    enabled: bool


class MessageCreate(BaseModel):
    role: str = Field(..., description="Role: user or assistant")
    content: str = Field(..., description="Message content")


class ThreadCreateRequest(BaseModel):
    title: str = Field(default="New Thread", description="Thread title")
    parent_id: Optional[UUID] = Field(None, description="Parent thread ID for branching")
    tool_overrides: Optional[list[ToolOverrideItem]] = Field(None, description="Initial tool overrides")


class ChatRequest(BaseModel):
    content: str = Field(..., description="User message content")
    thread_id: Optional[str] = Field(None, description="Existing thread ID to continue conversation")
    parent_id: Optional[UUID] = Field(None, description="Parent thread ID for branching")
    tool_overrides: Optional[list[ToolOverrideItem]] = Field(None, description="Initial tool overrides for new threads")
    image_urls: Optional[list[str]] = Field(None, description="Optional image URLs to include in the user message")


class ContinueWorkflowRequest(BaseModel):
    should_continue: bool = Field(..., description="Whether the active workflow should continue iterating")


class MessageResponse(BaseModel):
    id: UUID
    thread_id: UUID
    role: str
    content: str
    created_at: datetime
    metadata: Optional[dict] = None

    model_config = {"from_attributes": True}


class DiscordThreadLinkResponse(BaseModel):
    thread_id: UUID
    guild_id: str
    channel_id: str
    discord_thread_id: str
    discord_thread_name: str
    is_active: bool

    model_config = {"from_attributes": True}


class ThreadResponse(BaseModel):
    id: UUID
    title: str
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = []
    is_generating: bool = False
    discord_link: Optional[DiscordThreadLinkResponse] = None
    reachy_connected: bool = False
    estimated_tokens: int = 0
    context_window: int = 8192
    has_llm_overrides: bool = False

    model_config = {"from_attributes": True}


class ThreadListItem(BaseModel):
    id: UUID
    title: str
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    is_discord_thread: bool = False
    discord_server_name: Optional[str] = None
    is_reachy_thread: bool = False
    has_llm_overrides: bool = False

    model_config = {"from_attributes": True}


class ThreadLlmOverridesResponse(BaseModel):
    thread_id: UUID
    overrides: dict = Field(default_factory=dict)
    defaults: dict = Field(default_factory=dict)
    schema: dict = Field(default_factory=dict)


class ThreadLlmOverridesRequest(BaseModel):
    overrides: dict = Field(default_factory=dict, description="Per-thread LLM override dict. Empty clears all overrides.")


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


class MCPServerCreate(BaseModel):
    name: str
    image: str
    env_vars: Optional[dict] = {}
    args: Optional[dict] = {}
    registry_credentials: Optional[dict] = {}


class MCPServerResponse(BaseModel):
    id: UUID
    name: str
    image: str
    env_vars: dict
    args: dict
    registry_credentials: dict = {}
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MCPTestResponse(BaseModel):
    success: bool
    tools: list[str] = []
    error: Optional[str] = None


class ToolOverrideRequest(BaseModel):
    overrides: list[ToolOverrideItem]


class AvailableTool(BaseModel):
    name: str
    description: str


class AvailableServer(BaseModel):
    id: str
    name: str
    tools: list[AvailableTool] = []


class ToolOverridesResponse(BaseModel):
    servers: list[AvailableServer] = []
    overrides: list[ToolOverrideItem] = []


class DiscordSettingsResponse(BaseModel):
    enabled: bool = False
    has_bot_token: bool = False
    guild_id: str = ""
    channel_id: str = ""
    poll_interval_seconds: int = 10


class DiscordSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    bot_token: Optional[str] = None
    guild_id: Optional[str] = None
    channel_id: Optional[str] = None
    poll_interval_seconds: Optional[int] = None


class DiscordShareRequest(BaseModel):
    guild_id: Optional[str] = None
    channel_id: Optional[str] = None
    name: Optional[str] = None


class ReachyBindingResponse(BaseModel):
    enabled: bool = False
    thread_id: Optional[UUID] = None
    thread_title: Optional[str] = None
    wake_word: str = "Reachy"
    task_queue: str = "reachy-local"


class DiscordServerResponse(BaseModel):
    guild_id: str
    guild_name: str
    default_channel_id: Optional[str] = None
    thread_count: int = 0


class DiscordServerListResponse(BaseModel):
    servers: list[DiscordServerResponse] = []


class DiscordServerMcpOverridesResponse(BaseModel):
    guild_id: str
    guild_name: str
    servers: list[AvailableServer] = []
    overrides: list[ToolOverrideItem] = []


class DiscordServerMcpOverridesRequest(BaseModel):
    overrides: list[ToolOverrideItem] = []


class UploadedImageResponse(BaseModel):
    filename: str
    url: str
    content_type: str


class ImageUploadResponse(BaseModel):
    images: list[UploadedImageResponse] = []
