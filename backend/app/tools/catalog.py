SAFE_BUILTIN_TOOLS = frozenset({"calculator", "json_parse", "text_count", "base64_encode", "base64_decode", "web_fetch", "current_datetime", "continue_thinking", "handoff_to_agent"})

_SCHEMAS = {
    "calculator": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
    "json_parse": {"type": "object", "properties": {"json_string": {"type": "string"}, "key_path": {"type": "string"}}, "required": ["json_string"]},
    "text_count": {"type": "object", "properties": {"text": {"type": "string"}, "unit": {"type": "string", "enum": ["words", "characters", "lines", "sentences"]}}, "required": ["text"]},
    "base64_encode": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    "base64_decode": {"type": "object", "properties": {"encoded": {"type": "string"}}, "required": ["encoded"]},
    "web_fetch": {"type": "object", "properties": {"url": {"type": "string"}, "start_index": {"type": "integer"}, "max_chars": {"type": "integer"}}, "required": ["url"]},
    "current_datetime": {"type": "object", "properties": {}},
    "continue_thinking": {"type": "object", "properties": {"thought": {"type": "string"}}, "required": ["thought"]},
    "handoff_to_agent": {"type": "object", "properties": {"contract_id": {"type": "string"}, "target_agent_id": {"type": "string"}, "input_payload": {"type": "object"}, "origin_chain": {"type": "array", "items": {"type": "string"}}, "idempotency_key": {"type": "string"}, "response_mode": {"type": "string", "enum": ["sync", "async"]}}, "required": ["contract_id", "target_agent_id", "input_payload", "idempotency_key"]},
}

def builtin_descriptors(selection=None) -> list[dict]:
    if selection is None:
        selected = set(SAFE_BUILTIN_TOOLS)
    else:
        selected = set(selection) & SAFE_BUILTIN_TOOLS
    return [{"type": "function", "function": {"name": name, "description": "Server-approved pure local operation.", "parameters": _SCHEMAS[name]}, "x-threadbot-identity": f"builtin:{name}"} for name in sorted(selected)]


def classify_tool(tool_identity: str) -> dict:
    legacy = SAFE_BUILTIN_TOOLS - {"web_fetch", "current_datetime", "continue_thinking"}
    if tool_identity.startswith("builtin:") and tool_identity.removeprefix("builtin:") in legacy:
        return {"risk": "low" if tool_identity != "builtin:handoff_to_agent" else "medium", "allowed": True, "retry_safe": True}
    return {"risk": "unknown", "allowed": False, "retry_safe": False}


def classify_tool_for_agent(tool_identity: str) -> dict:
    """Runtime catalog for agents, including the existing chat built-ins."""
    if tool_identity.startswith("builtin:") and tool_identity.removeprefix("builtin:") in SAFE_BUILTIN_TOOLS:
        return {"risk": "medium" if tool_identity == "builtin:handoff_to_agent" else "low", "allowed": True, "retry_safe": True}
    if tool_identity.startswith("mcp:"):
        return {"risk": "medium", "allowed": True, "retry_safe": False}
    return classify_tool(tool_identity)

def identity_for_descriptor(descriptor: dict, function_name: str) -> str | None:
    identity = descriptor.get("x-threadbot-identity") or (descriptor.get("function") or {}).get("x-threadbot-identity")
    if identity:
        return identity
    if function_name in SAFE_BUILTIN_TOOLS and (descriptor.get("function") or {}).get("name") == function_name:
        return f"builtin:{function_name}"
    return None
