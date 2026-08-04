from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4
from app.autonomy_hashing import canonical_hash


@dataclass(frozen=True)
class TriggerEnvelope:
    source: str
    event_type: str
    dedupe_key: str
    payload: dict[str, Any]
    subject: dict[str, str] = field(default_factory=dict)
    origin_chain: tuple[str, ...] = ()
    trust: str = "untrusted_content"
    event_id: UUID = field(default_factory=uuid4)
    correlation_id: UUID = field(default_factory=uuid4)
    causation_id: UUID | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class PollResult:
    events: tuple[TriggerEnvelope, ...]
    cursor: dict[str, Any]
    fingerprint: str | None = None
    unchanged: bool = False


class Connector(Protocol):
    async def validate(self, config: dict[str, Any], credential: dict[str, Any] | None = None) -> dict[str, Any]: ...
    async def poll(self, cursor: dict[str, Any] | None = None) -> PollResult: ...
    async def normalize(self, native_event: Any) -> TriggerEnvelope: ...
    async def snapshot(self, subject: dict[str, str]) -> dict[str, Any] | None: ...
    async def preview(self, action: dict[str, Any]) -> dict[str, Any] | None: ...
    async def execute(self, action: dict[str, Any], idempotency_key: str) -> dict[str, Any]: ...


def fingerprint(value: Any) -> str:
    return canonical_hash(value)
