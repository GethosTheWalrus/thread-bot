"""Public Phase 1 autonomy contracts.  These models deliberately contain references,
not credentials or provider secrets."""
from datetime import datetime
from enum import StrEnum
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Generic, TypeVar
from .common import ActorContext, SecretReference

class AgentStatus(StrEnum): draft="draft"; active="active"; paused="paused"; archived="archived"
class ExecutionMode(StrEnum): observe="observe"; recommend="recommend"; act="act"
class TriggerType(StrEnum): manual="manual"; schedule="schedule"
class RunMode(StrEnum): live="live"; dry_run="dry_run"
class ResponseMode(StrEnum): response="response"; actions="actions"; both="both"
class RunStatus(StrEnum): queued="queued"; running="running"; waiting_approval="waiting_approval"; waiting_handoff="waiting_handoff"; succeeded="succeeded"; exhausted="exhausted"; timed_out="timed_out"; cancelled="cancelled"; failed="failed"; suppressed="suppressed"; dead_lettered="dead_lettered"; outcome_unknown="outcome_unknown"
class OverlapPolicy(StrEnum): skip="skip"; buffer_one="buffer_one"

def _reject_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if any(x in str(key).lower() for x in ("secret", "password", "token", "api_key", "ciphertext")):
                raise ValueError("secret material is not accepted")
            _reject_secrets(item)
    elif isinstance(value, list):
        for item in value: _reject_secrets(item)

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)
    @model_validator(mode="after")
    def no_secrets(self):
        _reject_secrets(self.model_dump(mode="json")); return self

class Page(BaseModel):
    model_config=ConfigDict(extra="forbid")
    cursor: str|None=None; limit: int=Field(50, ge=1, le=200)

class AgentCreate(StrictModel):
    name: str=Field(min_length=1,max_length=255); handle: str|None=Field(None, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$"); description: str|None=None; execution_mode: ExecutionMode=ExecutionMode.observe; template_id: UUID|None=None; thread_id: UUID|None=None; concurrency_limit:int=Field(1,ge=1,le=32); queue_limit:int=Field(100,ge=0,le=10000)
class AgentPatch(StrictModel):
    name: str|None=Field(None,min_length=1,max_length=255); handle: str|None=Field(None, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,31}$"); description:str|None=None; execution_mode:ExecutionMode|None=None; concurrency_limit:int|None=Field(None,ge=1,le=32); queue_limit:int|None=Field(None,ge=0,le=10000)
class AgentResponse(StrictModel):
    id:UUID; thread_id:UUID; thread_title:str|None=None; name:str; handle:str; is_moderator:bool; description:str|None; status:AgentStatus; execution_mode:ExecutionMode; active_version_id:UUID|None; template_id:UUID|None; concurrency_limit:int; queue_limit:int; created_at:datetime; updated_at:datetime

class DraftUpsert(StrictModel):
    optimistic_lock_version:int=Field(ge=1); schema_version:int=Field(1,ge=1); config:dict={}; prompt_template:str=Field("",max_length=100000); tool_selection:list[str]=[]; skill_selection:list[str]=[]; credential_bindings:list[SecretReference]=[]
class DraftResponse(DraftUpsert):
    id:UUID; agent_id:UUID; optimistic_lock_version:int=Field(validation_alias="version",serialization_alias="optimistic_lock_version"); config_hash:str; created_at:datetime; updated_at:datetime
class VersionResponse(StrictModel):
    id:UUID; agent_id:UUID; version:int; schema_version:int; config:dict; prompt_template:str; tool_selection:list; skill_selection:list; credential_bindings:list; config_hash:str; created_at:datetime

class TemplateCreate(StrictModel):
    name:str=Field(min_length=1,max_length=255); description:str|None=None; schema_version:int=Field(1,ge=1); definition:dict={}
class TemplateResponse(StrictModel):
    id:UUID; workspace_id:UUID; name:str; description:str|None; schema_version:int; definition:dict; status:str
class TriggerCreate(StrictModel):
    trigger_type:TriggerType; config:dict={}; is_active:bool=True
    @model_validator(mode="after")
    def valid_schedule(self):
        if self.trigger_type == TriggerType.schedule:
            if not isinstance(self.config.get("cron"),str) or len(self.config["cron"].split()) != 5: raise ValueError("schedule requires a five-field cron")
            from zoneinfo import ZoneInfo
            try: ZoneInfo(self.config.get("timezone","UTC"))
            except Exception as exc: raise ValueError("invalid timezone") from exc
            if self.config.get("overlap","skip") not in {"skip","buffer_one"}: raise ValueError("invalid overlap policy")
        return self
class TriggerResponse(StrictModel):
    id:UUID; workspace_id:UUID; agent_id:UUID; trigger_type:TriggerType; config:dict; is_active:bool
class TriggerPreview(StrictModel):
    timezone:str; occurrences:list[datetime]; assumptions:list[str]
class RunRequest(StrictModel):
    message:str=Field(min_length=1,max_length=100000); mode:RunMode=RunMode.live; trigger_id:UUID|None=None; response_mode:ResponseMode=ResponseMode.both
class RunResponse(StrictModel):
    id:UUID; agent_id:UUID; agent_version_id:UUID; thread_id:UUID; status:RunStatus; mode:RunMode; route:str=""; input_message_id:UUID|None=None; agent_name:str|None=None; agent_handle:str|None=None; trigger_event_id:UUID|None; output_summary:str|None; queued_at:datetime; started_at:datetime|None; completed_at:datetime|None
class EventResponse(StrictModel):
    sequence:int; event_type:str; payload:dict; created_at:datetime
class ForecastResponse(StrictModel):
    frequency_per_day:float; estimated_runs:float; estimated_model_calls:float; estimated_tool_calls:float; assumptions:list[str]
class SchedulePreviewRequest(StrictModel):
    cron:str; timezone:str="UTC"; count:int=Field(5,ge=1,le=20)

T = TypeVar("T")
class AgentPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AgentResponse]
    next_cursor: str | None = None
class RunPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[RunResponse]
    next_cursor: str | None = None
class EventPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[EventResponse]
    next_cursor: int | None = None
class AuditResponse(StrictModel):
    id: UUID; action: str = Field(validation_alias="event_type", serialization_alias="event_type")
    resource_type: str | None = None; resource_id: str | None = None
    metadata: dict = {}
    created_at: datetime
class AuditPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[AuditResponse]
    next_cursor: str | None = None


class HeartbeatDecision(StrEnum): response="response"; action="action"; delegate="delegate"; no_op="no_op"
class HeartbeatOperationalStatus(StrEnum):
    disabled="disabled"; scheduled="scheduled"; evaluating="evaluating"; paused="paused"
    blocked_mode="blocked_mode"; blocked_archived="blocked_archived"; blocked_global="blocked_global"; error="error"


class HeartbeatConfigUpsert(StrictModel):
    enabled: bool
    min_wake_seconds: int = Field(300, ge=30, le=86400)
    max_wake_seconds: int = Field(3600, ge=30, le=604800)
    idle_backoff_factor: float = Field(2.0, ge=1.0, le=10.0)
    expected_revision: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def _min_le_max(self):
        if self.min_wake_seconds > self.max_wake_seconds:
            raise ValueError("min_wake_seconds must be <= max_wake_seconds")
        return self


class HeartbeatResponse(StrictModel):
    agent_id: UUID
    enabled: bool
    min_wake_seconds: int
    max_wake_seconds: int
    idle_backoff_factor: float
    revision: int
    operational_status: HeartbeatOperationalStatus
    workflow_id: str | None = None
    last_wake_at: datetime | None = None
    last_completed_at: datetime | None = None
    next_wake_at: datetime | None = None
    last_decision: HeartbeatDecision | None = None
    last_run_id: UUID | None = None
    consecutive_noops: int
    last_error: str | None = None
    updated_at: datetime
