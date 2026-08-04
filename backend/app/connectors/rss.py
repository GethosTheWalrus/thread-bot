import xml.etree.ElementTree as ET
import aiohttp
from .base import PollResult, TriggerEnvelope, fingerprint
from app.security import validate_outbound_url


class RssConnector:
    def __init__(self, config): self.config = config

    async def validate(self, config, credential=None):
        validate_outbound_url(config["url"], config.get("allowed_hosts", [])); return {"valid": True, "type": "rss"}

    async def poll(self, cursor=None):
        validate_outbound_url(self.config["url"], self.config.get("allowed_hosts", []))
        timeout = aiohttp.ClientTimeout(total=min(int(self.config.get("timeout_seconds", 20)), 30))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(self.config["url"], allow_redirects=False) as response:
                response.raise_for_status(); raw = await response.content.read(min(int(self.config.get("max_bytes", 1_000_000)), 2_000_000) + 1)
        root = ET.fromstring(raw)
        items = [{child.tag.rsplit("}", 1)[-1]: (child.text or "")[:10_000] for child in item} for item in root.findall(".//item")[:100]]
        digest = fingerprint(items)
        if cursor and cursor.get("fingerprint") == digest: return PollResult((), cursor, digest, True)
        events = tuple(TriggerEnvelope("poller", "rss.item", fingerprint(item), {"item": item}, {"item": item.get("guid", item.get("link", ""))}) for item in items)
        return PollResult(events, {"fingerprint": digest}, digest)

    async def normalize(self, native_event): return TriggerEnvelope("poller", "rss.item", fingerprint(native_event), {"item": native_event})
    async def snapshot(self, subject): return None
    async def preview(self, action): return None
    async def execute(self, action, idempotency_key): raise PermissionError("RSS connector is observation-only")
