import hashlib
import json
from typing import Any
def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
def stable_action_id(run_id: str, tool_call_id: str, arguments: Any, revision: int = 1) -> str:
    return canonical_hash({"run_id": str(run_id), "tool_call_id": str(tool_call_id), "arguments": arguments, "revision": revision})


def approval_request_hash(tool_identity: str, arguments: Any, target: Any, agent_version: str, policy_version: str, expiry: Any, credential_binding: Any = None) -> str:
    return canonical_hash({"tool_identity": tool_identity, "arguments": arguments, "target": target, "agent_version": str(agent_version), "policy_version": str(policy_version), "credential_binding": credential_binding, "expiry": expiry})
