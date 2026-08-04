from datetime import datetime
from typing import Generic, TypeVar
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class WorkspaceRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class ConnectorResponse(WorkspaceRecord):
    name: str
    connector_type: str
    config: dict = Field(default_factory=dict)
    is_active: bool


class ConnectorPage(Page[ConnectorResponse]):
    pass


class NotificationRouteResponse(WorkspaceRecord):
    profile_id: UUID
    name: str
    channel: str
    config: dict = Field(default_factory=dict)
    filters: dict = Field(default_factory=dict)
    is_active: bool


class ApprovalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    workspace_id: UUID
    run_id: UUID
    action_id: str
    action_revision: int
    tool_identity: str | None = None
    request_hash: str
    status: str
    risk_level: str
    policy_ref: str | None = None
    credential_ref: str | None = None
    target: dict = Field(default_factory=dict)
    redacted_arguments: dict = Field(default_factory=dict)
    policy_explanation: dict = Field(default_factory=dict)
    expires_at: datetime
