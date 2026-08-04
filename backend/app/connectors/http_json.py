import json
from typing import Any
import aiohttp
from .base import Connector, PollResult, TriggerEnvelope, fingerprint
from app.security import validate_outbound_url


class HttpJsonConnector:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    async def validate(self, config, credential=None):
        validate_outbound_url(config["url"], config.get("allowed_hosts", []))
        return {"valid": True, "type": "http_json"}

    async def poll(self, cursor=None):
        url = self.config["url"]
        validate_outbound_url(url, self.config.get("allowed_hosts", []))
        headers = {k: v for k, v in (self.config.get("headers") or {}).items() if k.lower() not in {"authorization", "cookie", "x-api-key"}}
        timeout = aiohttp.ClientTimeout(total=min(int(self.config.get("timeout_seconds", 20)), 30))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers, allow_redirects=False) as response:
                response.raise_for_status()
                raw = await response.content.read(min(int(self.config.get("max_bytes", 1_000_000)), 2_000_000) + 1)
                if len(raw) > int(self.config.get("max_bytes", 1_000_000)):
                    raise ValueError("connector response exceeds size limit")
                value = json.loads(raw)
        digest = fingerprint(value)
        if cursor and cursor.get("fingerprint") == digest:
            return PollResult((), cursor, digest, True)
        return PollResult((TriggerEnvelope("poller", "http.json.changed", digest, {"data": value}),), {"fingerprint": digest}, digest)

    async def normalize(self, native_event):
        return TriggerEnvelope("poller", "http.json.changed", fingerprint(native_event), {"data": native_event})
    async def snapshot(self, subject): return None
    async def preview(self, action): return None
    async def execute(self, action, idempotency_key): raise PermissionError("HTTP JSON connector is observation-only")
