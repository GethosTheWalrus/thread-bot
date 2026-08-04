from typing import Any
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
class FinishReason(StrEnum):
    stop="stop"; tool_calls="tool_calls"; length="length"; error="error"
class ActionProposal(BaseModel):
    model_config=ConfigDict(extra="forbid")
    model_call_id: str; tool_call_id: str; tool_identity: str; arguments: dict[str,Any]; target: dict[str,Any]={}; rationale: str=""; safe_reasoning_summary: str=""
class PlannedAction(ActionProposal):
    action_id: str; idempotency_key: str; request_hash: str; revision: int=1
class PlanningResult(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: int=Field(1, ge=1, le=1); model_call_id: str; text: str=""; proposals: tuple[ActionProposal,...]=(); finish_reason: FinishReason=FinishReason.stop; usage: dict[str,int]=Field(default_factory=dict); safe_reasoning_summary: str=""
