from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class ReplayRequest(BaseModel):
    mode: Literal["recorded", "reexecution"] = "recorded"
    dry_run: bool = True


class ReplayResponse(BaseModel):
    id: UUID
    mode: str
    effect_free: bool
    source_run_id: UUID
    replay_run_id: UUID | None = None
    timeline: list[dict[str, Any]] = []
    comparison: dict[str, Any] = {}


class CanaryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_version_id: UUID
    cohort: dict[str, Any] = Field(default_factory=dict)

    @property
    def normalized_cohort(self) -> dict[str, Any]:
        return {str(k): v for k, v in sorted(self.cohort.items())}


class CanaryDecision(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    expected_version: int = Field(ge=1)


class ForecastResponse(BaseModel):
    horizon_hours: int
    metrics: dict[str, dict[str, float | int | None]]
    assumptions: list[str]
    confidence: str


class RecoveryRequest(BaseModel):
    operation: Literal["retry_dead_letter", "reconcile_action", "expire_approval", "pause_queue", "drain_queue", "rollback_version"]
    resource_id: str
    details: dict[str, Any] = Field(default_factory=dict)
