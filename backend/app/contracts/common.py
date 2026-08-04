from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
class ActorType(StrEnum): human="human"; agent="agent"; system="system"; connector="connector"; device="device"
class AuthenticationMethod(StrEnum): local="local"; admin_token="admin_token"; oidc="oidc"; discord="discord"; device="device"
class SecurityMode(StrEnum): local="local"; admin_token="admin_token"; oidc="oidc"
class ActorContext(BaseModel):
    model_config=ConfigDict(extra="forbid", frozen=True)
    workspace_id: UUID; actor_type: ActorType; actor_id: str=Field(min_length=1,max_length=255); authentication_method: AuthenticationMethod; roles: tuple[str,...]=(); correlation_id: UUID
class SecretReference(BaseModel):
    model_config=ConfigDict(extra="forbid", frozen=True)
    binding_id: UUID
