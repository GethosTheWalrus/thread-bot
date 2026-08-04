from .common import ActorContext, ActorType, AuthenticationMethod, SecurityMode
from .events import DurableEventContract, TriggerEventContract
from .runtime import AgentCoordinatorInput, RunContext, ThreadTurnInputV2, RunMode, SourceTrust
from .planning import PlannedAction, PlanningResult, ActionProposal, FinishReason
from .policy import PolicyDecision, PolicyEffect, RiskLevel
from .tools import ToolExecutionRequest, ToolExecutionResult, ToolStatus
from .approval import ApprovalWakeSignal

def redact_secret(value):
    if isinstance(value, dict):
        names = {"secret", "token", "api_key", "password", "authorization", "client_secret"}
        return {key: "[REDACTED]" if key.lower() in names else redact_secret(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_secret(item) for item in value]
    return value

__all__ = ["ActorContext", "ActorType", "AuthenticationMethod", "SecurityMode", "DurableEventContract", "TriggerEventContract", "AgentCoordinatorInput", "RunContext", "RunMode", "SourceTrust", "ThreadTurnInputV2", "PlannedAction", "PlanningResult", "ActionProposal", "FinishReason", "PolicyDecision", "PolicyEffect", "RiskLevel", "ToolExecutionRequest", "ToolExecutionResult", "ToolStatus", "ApprovalWakeSignal"]
from .autonomy import *
from .phase2 import *
