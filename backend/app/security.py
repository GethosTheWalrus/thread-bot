from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, WebSocket, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_setting
from app.contracts import ActorContext, ActorType, AuthenticationMethod
from app.models.foundation_models import ApiToken
from app.database import get_db
import ipaddress
from urllib.parse import urlparse
import socket

LOCAL_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")
LOCAL_ACTOR_ID = "local-owner"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60


def security_mode() -> str:
    mode = str(get_setting("SECURITY_MODE") or "local").lower()
    if mode not in {"local", "admin_token", "oidc"}:
        raise RuntimeError("SECURITY_MODE must be local, admin_token, or oidc")
    return mode


def configured_cors_origins() -> list[str]:
    raw = str(get_setting("CORS_ORIGINS") or "*")
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    if security_mode() != "local" and "*" in origins:
        raise RuntimeError("CORS_ORIGINS cannot contain '*' outside local security mode")
    return origins or (["*"] if security_mode() == "local" else [])


def cors_origin_allowed(origin: str, scheme: str, host: str) -> bool:
    raw = str(get_setting("CORS_ORIGINS") or "*")
    origins = {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}
    normalized = origin.rstrip("/")
    if normalized in origins:
        return True
    if "*" not in origins:
        return False
    return security_mode() == "local" or normalized == f"{scheme}://{host}".rstrip("/")


def browser_cookie_secure(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return forwarded == "https" or request.url.scheme == "https"


def autonomy_flags() -> dict[str, bool]:
    names = ("AUTONOMY_ENABLED", "AUTONOMY_SIDE_EFFECTS_ENABLED", "AUTONOMY_WEBHOOKS_ENABLED", "AGENTS_ENABLED", "AGENTS_MANUAL_RUN_ENABLED", "AGENTS_SCHEDULES_ENABLED", "AGENTS_CONNECTORS_ENABLED", "AGENTS_ACTIONS_ENABLED", "AGENTS_APPROVALS_ENABLED", "AGENTS_HANDOFFS_ENABLED", "AGENTS_REPLAY_ENABLED", "AGENTS_CANARY_ENABLED", "AGENTS_REACHY_ACTIONS_ENABLED")
    values = {name.lower(): str(get_setting(name)).lower() in {"1", "true", "yes", "on"} for name in names}
    if security_mode() == "local":
        # Webhooks remain disabled in local mode regardless of the side-effect
        # flag; they are a distinct inbound surface.  Side effects themselves
        # may be explicitly enabled by a trusted local deployment.
        values["autonomy_webhooks_enabled"] = False
    return values


def validate_outbound_url(url: str, allowed_hosts: list[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("only HTTP(S) connector URLs are allowed")
    host = parsed.hostname.lower().rstrip(".")
    allowed = {item.lower().rstrip(".") for item in (allowed_hosts or [])}
    if allowed and host not in allowed:
        raise ValueError("connector host is not allowlisted")
    if host in {"localhost", "metadata.google.internal", "metadata", "0.0.0.0"} or host.endswith(".local"):
        raise ValueError("connector host is not permitted")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("connector host cannot be resolved") from exc
    for item in addresses:
        address = ipaddress.ip_address(item[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
            raise ValueError("connector host resolves to a blocked address")
    return parsed.geturl()


def untrusted_source_block(value: str) -> str:
    return "UNTRUSTED_SOURCE_DATA\n" + value[:100_000] + "\nEND_UNTRUSTED_SOURCE_DATA"


def origin_chain_allows(origin_chain: list[str] | tuple[str, ...], source_id: str, max_hops: int = 8) -> tuple[bool, str | None]:
    if len(origin_chain) >= max_hops:
        return False, "hop_limit"
    if source_id in origin_chain:
        return False, "self_origin"
    return True, None


def require_autonomy_feature(feature: str) -> None:
    """Hard gate for future autonomy routes and dispatchers."""
    flags = autonomy_flags()
    if not flags.get(feature.lower(), False):
        raise HTTPException(status_code=404, detail="Autonomy feature is disabled")


def require_autonomy(feature: str):
    async def dependency() -> None:
        require_autonomy_feature(feature)
    return dependency


def hash_token(token: str) -> str:
    from argon2 import PasswordHasher
    return PasswordHasher().hash(token)


def verify_token(token: str, token_hash: str) -> bool:
    from argon2 import PasswordHasher
    try:
        return PasswordHasher().verify(token_hash, token)
    except Exception:
        return False


def local_actor(correlation_id: UUID | None = None) -> ActorContext:
    return ActorContext(workspace_id=LOCAL_WORKSPACE_ID, actor_type=ActorType.human,
                        actor_id=LOCAL_ACTOR_ID, authentication_method=AuthenticationMethod.local,
                        roles=("owner", "admin"), correlation_id=correlation_id or uuid4())


def correlation_id_for_request(request: Request) -> UUID:
    raw = request.headers.get("X-Correlation-ID")
    if not raw:
        return uuid4()
    try:
        return UUID(raw)
    except (ValueError, AttributeError, TypeError):
        # A malformed client value must never turn into an authentication failure.
        return uuid4()


async def actor_from_request(request: Request, db: AsyncSession) -> ActorContext:
    correlation_id = getattr(request.state, "correlation_id", None) or correlation_id_for_request(request)
    mode = security_mode()
    if mode == "local":
        return local_actor(correlation_id)
    if mode == "oidc":
        raise HTTPException(status_code=501, detail="OIDC authentication is not configured")
    authorization = request.headers.get("Authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
    if not token:
        token = request.cookies.get("threadbot_session")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    env_hash = get_setting("ADMIN_TOKEN_HASH")
    valid = bool(env_hash and verify_token(token, str(env_hash)))
    record = None
    if not valid:
        rows = (await db.execute(select(ApiToken).where(
            ApiToken.token_prefix == token[:12],
            ApiToken.revoked_at.is_(None),
        ))).scalars()
        for candidate in rows:
            if (candidate.expires_at is None or candidate.expires_at > datetime.now(timezone.utc)) and verify_token(token, candidate.token_hash):
                record = candidate
                valid = True
                break
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return ActorContext(workspace_id=record.workspace_id if record else LOCAL_WORKSPACE_ID,
                        actor_type=ActorType.human, actor_id=record.actor_id if record else "admin",
                        authentication_method=AuthenticationMethod.admin_token,
                        roles=tuple(record.roles if record else ["owner", "admin"]), correlation_id=correlation_id)


async def require_actor(request: Request, db: Annotated[AsyncSession, Depends(get_db)]) -> ActorContext:
    actor = getattr(request.state, "actor", None)
    if actor is not None:
        return actor
    actor = await actor_from_request(request, db)
    request.state.actor = actor
    return actor


def require_roles(*roles: str):
    async def dependency(actor: Annotated[ActorContext, Depends(require_actor)]) -> ActorContext:
        if not set(roles).intersection(actor.roles):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return actor
    return dependency


async def require_owner_or_admin(actor: Annotated[ActorContext, Depends(require_actor)]) -> ActorContext:
    if not {"owner", "admin"}.intersection(actor.roles):
        raise HTTPException(status_code=403, detail="Owner or admin role required")
    return actor


def validate_websocket_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if origin is None:
        return security_mode() == "local"
    scheme = websocket.headers.get("x-forwarded-proto", websocket.url.scheme).split(",", 1)[0].strip()
    host = websocket.headers.get("x-forwarded-host", websocket.headers.get("host", "")).split(",", 1)[0].strip()
    return cors_origin_allowed(origin, scheme, host)


async def authenticate_websocket(websocket: WebSocket, required_roles: set[str] | None = None) -> ActorContext | None:
    if not validate_websocket_origin(websocket):
        await websocket.close(code=1008)
        return None
    if security_mode() == "local":
        actor = local_actor()
        if required_roles and not required_roles.intersection(actor.roles):
            await websocket.close(code=1008)
            return None
        return actor
    # Browser sessions use a HttpOnly cookie; bearer remains available to native clients.
    request = Request({"type": "http", "headers": websocket.scope.get("headers", []), "query_string": b"", "method": "GET"})
    from app.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        try:
            actor = await actor_from_request(request, db)
            if required_roles and not required_roles.intersection(actor.roles):
                await websocket.close(code=1008)
                return None
            return actor
        except HTTPException:
            await websocket.close(code=1008)
            return None
