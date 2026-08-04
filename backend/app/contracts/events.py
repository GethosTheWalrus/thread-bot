from datetime import datetime
from typing import Any
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
class DurableEventContract(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: int=Field(1, ge=1, le=1); event_id: UUID; workspace_id: UUID; event_type: str=Field(min_length=1,max_length=255); payload: dict[str,Any]={}; correlation_id: UUID; causation_id: UUID|None=None
class TriggerEventContract(DurableEventContract):
    agent_id: UUID|None=None; trigger_id: UUID|None=None; source: str; occurred_at: datetime; received_at: datetime; dedupe_key: str=Field(min_length=1,max_length=512); subject: dict[str,str]={}; trust: str; origin_chain: tuple[str,...]=(); content_refs: tuple[str,...]=()
