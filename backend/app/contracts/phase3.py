from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

class ResponseMode(StrEnum):
    sync = "sync"
    async_ = "async"

class HandoffContractCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255); version: int = Field(ge=1)
    source_capability: str; target_capability: str; input_schema: dict; output_schema: dict = {}
    target_allowlist: list[UUID] = []; artifact_classifications: list[str] = []; timeout_seconds: int = Field(300, ge=1, le=86400); max_depth: int = Field(3, ge=1, le=32)

class HandoffContractPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_capability: str | None = None; target_capability: str | None = None; input_schema: dict | None = None; output_schema: dict | None = None; target_allowlist: list[UUID] | None = None; artifact_classifications: list[str] | None = None; timeout_seconds: int | None = Field(None, ge=1, le=86400); max_depth: int | None = Field(None, ge=1, le=32); lifecycle_version: int = Field(ge=1)

class HandoffContractResponse(HandoffContractCreate):
    id: UUID; workspace_id: UUID; is_active: bool; status: str; lifecycle_version: int; created_at: datetime; updated_at: datetime

class HandoffContractVersionResponse(HandoffContractResponse): pass

class ArtifactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; run_id: UUID | None; content_type: str; size_bytes: int; sha256: str; classification: str; retention_until: datetime | None; legal_hold: int; created_at: datetime

class ArtifactPage(BaseModel): items: list[ArtifactResponse]; next_cursor: str | None = None

class OperationsSummary(BaseModel): active_runs: int; queued_runs: int; pending_handoffs: int; sla_incidents: int; queue_health: dict

class HandoffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_id: UUID; target_agent_id: UUID; input_payload: dict[str, Any]; origin_chain: list[str] = []; response_mode: ResponseMode = ResponseMode.async_; idempotency_key: str = Field(min_length=1, max_length=255)
    @model_validator(mode="after")
    def bounded_origin(self):
        if len(self.origin_chain) > 32: raise ValueError("origin chain is too long")
        return self

class HandoffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; contract_id: UUID; source_run_id: UUID; target_agent_id: UUID; status: str; response_mode: ResponseMode; acknowledgement_deadline: datetime | None; completion_deadline: datetime | None; output_payload: dict | None = None

class HandoffPage(BaseModel): items: list[HandoffResponse]; next_cursor: str | None = None

class RecommendationDecision(BaseModel):
    accept: bool

class RecommendationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence: dict = {}; proposed_diff: dict; risk: str = Field("unknown", min_length=1, max_length=32)
    @model_validator(mode="after")
    def require_evidence(self):
        if not self.evidence: raise ValueError("recommendation evidence is required")
        return self

class HandoffContractValidation(BaseModel):
    input_payload: dict

class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; evidence: dict; proposed_diff: dict; risk: str; status: str; accepted_draft_id: UUID | None = None; created_at: datetime
