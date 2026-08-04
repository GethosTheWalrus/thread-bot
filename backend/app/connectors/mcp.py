class McpConnector:
    async def validate(self, config, credential=None):
        if not config.get("profile_id"): raise ValueError("MCP connector requires an explicit profile_id")
        return {"valid": True, "type": "mcp"}
    async def poll(self, cursor=None): from .base import PollResult; return PollResult((), cursor or {})
    async def normalize(self, native_event): from .base import TriggerEnvelope; return TriggerEnvelope("mcp", "mcp.event", str(native_event.get("id")), native_event)
    async def snapshot(self, subject): return None
    async def preview(self, action): return {"supported": False, "reason": "MCP actions require per-tool review"}
    async def execute(self, action, idempotency_key): raise PermissionError("unknown MCP actions are disabled")
