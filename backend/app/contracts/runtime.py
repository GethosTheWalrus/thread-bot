from datetime import datetime
from uuid import UUID
from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .common import SecretReference, ActorContext
from .planning import ActionProposal

class RunMode(StrEnum):
    interactive="interactive"; autonomous="autonomous"; dry_run="dry_run"; replay="replay"; canary_shadow="canary_shadow"
class SourceTrust(StrEnum):
    trusted_metadata="trusted_metadata"; untrusted_content="untrusted_content"
class RunContext(BaseModel):
    model_config=ConfigDict(extra="forbid")
    mode: RunMode; response_mode: str = "both"; agent_run_id: UUID|None=None; policy_set_id: UUID|None=None; budget_profile_id: UUID|None=None; credential_binding_ids: tuple[UUID,...]=(); deadline_at: datetime|None=None; max_handoff_depth: int=Field(0,ge=0); source_trust: SourceTrust
    max_cycles: int=Field(1, ge=1); max_model_calls: int=Field(1, ge=1); max_tool_calls: int=Field(0, ge=0); stream_context: dict = Field(default_factory=dict)
class AgentCoordinatorInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: int=Field(1, ge=1, le=1); agent_id: UUID; trigger_event_ids: tuple[UUID,...]=()
class ThreadTurnInputV2(BaseModel):
    model_config=ConfigDict(extra="forbid", frozen=True)
    schema_version: int=Field(2, ge=2, le=2); workspace_id: UUID; thread_id: UUID; actor: ActorContext
    run_id: UUID; runtime_snapshot_id: UUID; input_message_ref: UUID|str; run_context: RunContext


class HeartbeatEvaluation(BaseModel):
    """Forced JSON-schema output from the heartbeat model call.

    The agent cannot emit credentials, arbitrary provider config, or unbounded
    proposals.  Exactly one decision must be chosen; the server clamps the
    requested next interval.
    """
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: Literal["response", "action", "delegate", "no_op"]
    next_wake_seconds: int = Field(ge=1, le=604800)
    response: str = ""
    delegate_handle: str | None = None
    proposals: tuple[ActionProposal, ...] = ()
    safe_reasoning_summary: str = ""
