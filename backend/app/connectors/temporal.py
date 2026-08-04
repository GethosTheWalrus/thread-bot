from .base import TriggerEnvelope


class TemporalConnector:
    async def validate(self, config, credential=None): return {"valid": bool(config.get("namespace")), "type": "temporal"}
    async def normalize(self, native_event):
        key = str(native_event.get("workflow_id") or native_event.get("run_id"))
        return TriggerEnvelope("temporal", "temporal.failure", key, {"event": native_event}, {"workflow": key}, ("connector:temporal",), "trusted_metadata")
    async def poll(self, cursor=None): from .base import PollResult; return PollResult((), cursor or {})
    async def snapshot(self, subject): return None
    async def preview(self, action): return None
    async def execute(self, action, idempotency_key): raise PermissionError("Temporal connector is observation-only")
