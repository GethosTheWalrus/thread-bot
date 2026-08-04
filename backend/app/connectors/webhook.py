import base64
import hashlib
import hmac
import time
from typing import Any
from .base import TriggerEnvelope


def verify_signed_webhook(body: bytes, signature: str, secret: str, timestamp: str, nonce: str, *, now: float | None = None, tolerance_seconds: int = 300, used_nonces: set[str] | None = None) -> bool:
    try:
        stamp = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = time.time() if now is None else now
    if abs(current - stamp) > tolerance_seconds or not nonce or (used_nonces is not None and nonce in used_nonces):
        return False
    message = timestamp.encode() + b"." + nonce.encode() + b"." + body
    digest = hmac.new(secret.encode(), message, hashlib.sha256).digest()
    supplied = signature.removeprefix("sha256=")
    try:
        valid = hmac.compare_digest(base64.b64decode(supplied), digest) or hmac.compare_digest(supplied, digest.hex())
    except (ValueError, TypeError):
        valid = hmac.compare_digest(supplied, digest.hex())
    if valid and used_nonces is not None:
        used_nonces.add(nonce)
    return valid


async def normalize_webhook(payload: dict[str, Any], dedupe_key: str, origin_chain: tuple[str, ...] = ()) -> TriggerEnvelope:
    return TriggerEnvelope(source="webhook", event_type=str(payload.get("type", "webhook.event")), dedupe_key=dedupe_key, payload=payload, origin_chain=origin_chain)
