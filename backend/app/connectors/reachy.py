class ReachyConnector:
    async def validate(self, config, credential=None): return {"valid": bool(config.get("device_id")), "type": "reachy", "actions_enabled": False}
    async def poll(self, cursor=None): from .base import PollResult; return PollResult((), cursor or {})
    async def normalize(self, native_event): from .base import TriggerEnvelope; return TriggerEnvelope("reachy", "reachy.event", str(native_event.get("id")), native_event)
    async def snapshot(self, subject): return None
    async def preview(self, action): return {"supported": False, "reason": "Reachy physical actions are disabled in Phase 2"}
    async def execute(self, action, idempotency_key): raise PermissionError("Reachy actions are disabled")
