from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Literal, Optional


class ToolOverrideItem(BaseModel):
    server_id: str
    tool_name: Optional[str] = None  # null = server-level override
    enabled: bool


class SkillOverrideItem(BaseModel):
    skill_id: str
    enabled: bool


class MessageCreate(BaseModel):
    role: str = Field(..., description="Role: user or assistant")
    content: str = Field(..., description="Message content")


class ThreadCreateRequest(BaseModel):
    title: str = Field(default="New Thread", description="Thread title")
    parent_id: Optional[UUID] = Field(None, description="Parent thread ID for branching")
    tool_overrides: Optional[list[ToolOverrideItem]] = Field(None, description="Initial tool overrides")
    skill_overrides: Optional[list[SkillOverrideItem]] = Field(None, description="Initial skill overrides")
    mode: str = Field(default="chat", pattern="^(chat|agent)$")
    agent_name: Optional[str] = None


class ChatRequest(BaseModel):
    content: str = Field(..., description="User message content")
    thread_id: Optional[str] = Field(None, description="Existing thread ID to continue conversation")
    parent_id: Optional[UUID] = Field(None, description="Parent thread ID for branching")
    tool_overrides: Optional[list[ToolOverrideItem]] = Field(None, description="Initial tool overrides for new threads")
    skill_overrides: Optional[list[SkillOverrideItem]] = Field(None, description="Initial skill overrides for new threads")
    image_urls: Optional[list[str]] = Field(None, description="Optional image URLs to include in the user message")
    response_mode: str = Field(default="both", pattern="^(response|actions|both)$")


class ContinueWorkflowRequest(BaseModel):
    should_continue: bool = Field(..., description="Whether the active workflow should continue iterating")


class SecurityModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(local|admin_token)$")


class SecurityResponse(BaseModel):
    mode: str
    token_auth_enabled: bool
    token: Optional[str] = None


class MessageResponse(BaseModel):
    id: UUID
    thread_id: UUID
    role: str
    content: str
    created_at: datetime
    metadata: Optional[dict] = None
    agent_id: Optional[UUID] = None
    agent_version_id: Optional[UUID] = None
    agent_run_id: Optional[UUID] = None
    agent_handle: Optional[str] = None
    agent_name: Optional[str] = None

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
    updated_at: Optional[datetime] = None
    messages: list[MessageResponse] = []
    is_generating: bool = False
    discord_link: Optional[DiscordThreadLinkResponse] = None
    reachy_connected: bool = False
    estimated_tokens: int = 0
    context_window: int = 8192
    has_llm_overrides: bool = False
    is_pinned: bool = False
    mode: str = "chat"
    archived_at: Optional[datetime] = None
    agent: Optional[dict] = None
    agents: list[dict] = []
    active_runs: list[dict] = []
    agent_turn_limit: int = Field(4, ge=1, le=8)
    moderator: Optional[dict] = None
    latest_active_run: Optional[dict] = None
    pending_approvals: int = 0
    approval_preset: str = "effectful"

    model_config = {"from_attributes": True}


class ContextBudgetResponse(BaseModel):
    context_window: int
    max_output_tokens: int
    input_budget: int
    estimated_tokens: int
    remaining_tokens: int
    usage_ratio: float
    compaction_threshold: float
    compaction_at_tokens: int
    tokens_until_compaction: int
    estimator: str = "chars_div_4_v1"


class ContextCompositionItem(BaseModel):
    key: str
    label: str
    tokens: int
    message_count: int


class ContextSummaryResponse(BaseModel):
    content: str
    updated_at: Optional[datetime] = None
    turn_count: int
    current_turn_count: int
    stale: bool


class ThreadContextResponse(BaseModel):
    thread_id: UUID
    budget: ContextBudgetResponse
    composition: list[ContextCompositionItem]
    summary: Optional[ContextSummaryResponse] = None


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
    is_pinned: bool = False
    mode: str = "chat"
    agent: Optional[dict] = None
    agents: list[dict] = []
    active_runs: list[dict] = []
    agent_turn_limit: int = Field(4, ge=1, le=8)
    moderator: Optional[dict] = None
    latest_active_run: Optional[dict] = None
    pending_approvals: int = 0
    approval_preset: str = "effectful"

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

class ThreadModeRequest(BaseModel):
    mode: str = Field(pattern="^(chat|agent)$")
    agent_name: Optional[str] = None


class ThreadApprovalPresetRequest(BaseModel):
    approval_preset: str = Field(pattern="^(all|effectful|never)$")


class ThreadPinRequest(BaseModel):
    is_pinned: bool


class MCPToolResponse(BaseModel):
    name: str
    description: str = ""


class MCPServerCreate(BaseModel):
    name: str
    image: str
    env_vars: Optional[dict] = {}
    args: Optional[dict] = {}
    registry_credentials: Optional[dict] = {}
    tool_safety_overrides: dict[str, Literal["read_only", "effectful"]] = Field(default_factory=dict)


class MCPServerResponse(BaseModel):
    id: UUID
    name: str
    image: str
    env_vars: dict
    args: dict
    registry_credentials: dict = {}
    tools: list[MCPToolResponse] = Field(default_factory=list)
    tool_safety_overrides: dict[str, Literal["read_only", "effectful"]] = Field(default_factory=dict)
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class MCPTestResponse(BaseModel):
    success: bool
    tools: list[str] = []
    error: Optional[str] = None


class SkillCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    content: str


class SkillResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = ""
    content: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class ToolOverrideRequest(BaseModel):
    overrides: list[ToolOverrideItem]


class SkillOverrideRequest(BaseModel):
    overrides: list[SkillOverrideItem]


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


class SkillOverridesResponse(BaseModel):
    skills: list[SkillResponse] = []
    overrides: list[SkillOverrideItem] = []


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
