from .base import PollResult, TriggerEnvelope


class DiscordConnector:
    async def validate(self, config, credential=None): return {"valid": bool(config.get("guild_id")), "type": "discord"}
    async def normalize(self, native_event):
        event_id = str(native_event.get("id") or native_event.get("message_id"))
        return TriggerEnvelope("discord", "discord.message", event_id, {"message": native_event}, {"message": event_id}, ("connector:discord",), "untrusted_content")
    async def poll(self, cursor=None): return PollResult((), cursor or {})
    async def snapshot(self, subject): return None
    async def preview(self, action): return None
    async def execute(self, action, idempotency_key): raise PermissionError("Discord mutation requires a reviewed action adapter")
