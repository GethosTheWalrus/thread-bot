from pydantic import BaseModel, ConfigDict, Field
class ApprovalWakeSignal(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: int=Field(1, ge=1, le=1); request_id: str
