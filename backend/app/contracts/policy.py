from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field
class PolicyEffect(StrEnum):
    deny="deny"; require_approval="require_approval"; allow="allow"
class RiskLevel(StrEnum):
    low="low"; medium="medium"; high="high"; critical="critical"; unknown="unknown"
class PolicyDecision(BaseModel):
    model_config=ConfigDict(extra="forbid")
    schema_version: int=Field(1, ge=1, le=1); effect: PolicyEffect; risk_level: RiskLevel; reason: str; policy_version: str; requires_approval: bool=False
