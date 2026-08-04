from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class CredentialCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=255)
    secret: str = Field(min_length=1)


class CredentialResponse(BaseModel):
    id: UUID
    name: str
    provider: str
    active_version_id: UUID | None = None
    has_secret: bool = True

    model_config = ConfigDict(from_attributes=True)
