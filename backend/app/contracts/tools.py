from typing import Any
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field
class ToolStatus(StrEnum):
    succeeded="succeeded"; failed="failed"; outcome_unknown="outcome_unknown"
class ToolExecutionRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: int=Field(1, ge=1, le=1); action_id: str; action_revision: int=Field(1, ge=1); tool_identity: str; arguments: dict[str,Any]; idempotency_key: str; authorization_ref: str|None=None; authorization_hash: str|None=None; credential_binding_id: str|None=None
class ToolExecutionResult(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: int=Field(1, ge=1, le=1); action_id: str; action_revision: int=Field(1, ge=1); status: ToolStatus; display_content: str=""; model_content: str=""; outcome: Any=None; artifacts: tuple[str,...]=(); provider_receipt: dict[str,Any]|None=None; retry_safe: bool=False; error_code: str|None=None
