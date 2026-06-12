from uuid import UUID
from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.models import (
    Thread,
    Message,
    MCPServer,
    Setting,
    ThreadToolOverride,
    DiscordThreadLink,
    DiscordServer,
    DiscordServerToolOverride,
)


async def create_thread(db: AsyncSession, title: str, parent_id: UUID | None = None) -> Thread:
    thread = Thread(title=title, parent_id=parent_id)
    db.add(thread)
    await db.flush()
    await db.refresh(thread)
    return thread


async def get_thread(db: AsyncSession, thread_id: UUID) -> Thread | None:
    result = await db.execute(
        select(Thread).where(Thread.id == thread_id)
    )
    return result.scalar_one_or_none()


async def get_thread_llm_overrides(db: AsyncSession, thread_id: UUID) -> dict:
    """Return the per-thread LLM override dict, or {} if none is set.

    The raw JSONB column is the source of truth; values are always plain
    Python primitives (str, int, float, bool, None, list, dict).
    """
    thread = await get_thread(db, thread_id)
    if thread is None:
        return {}
    overrides = thread.llm_overrides
    if not overrides:
        return {}
    if not isinstance(overrides, dict):
        return {}
    return overrides


async def set_thread_llm_overrides(db: AsyncSession, thread_id: UUID, overrides: dict) -> dict:
    """Replace the per-thread LLM override dict. Empty dict clears overrides."""
    thread = await get_thread(db, thread_id)
    if thread is None:
        return {}
    cleaned = {str(k): v for k, v in (overrides or {}).items() if v is not None}
    thread.llm_overrides = cleaned or None
    await db.flush()
    return cleaned


async def clear_thread_llm_overrides(db: AsyncSession, thread_id: UUID) -> None:
    thread = await get_thread(db, thread_id)
    if thread is None:
        return
    thread.llm_overrides = None
    await db.flush()


async def get_thread_with_messages(db: AsyncSession, thread_id: UUID) -> Thread | None:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Thread)
        .where(Thread.id == thread_id)
        .options(selectinload(Thread.messages))
    )
    return result.scalar_one_or_none()


async def get_root_threads(db: AsyncSession, limit: int = 50, offset: int = 0) -> list[Thread]:
    result = await db.execute(
        select(Thread)
        .where(Thread.parent_id.is_(None))
        .order_by(Thread.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all())


async def get_child_threads(db: AsyncSession, parent_id: UUID) -> list[Thread]:
    result = await db.execute(
        select(Thread)
        .where(Thread.parent_id == parent_id)
        .order_by(Thread.created_at)
    )
    return list(result.scalars().all())


async def add_message(
    db: AsyncSession,
    thread_id: UUID,
    role: str,
    content: str,
    metadata: dict | None = None,
    created_at: datetime | None = None,
) -> Message:
    message = Message(thread_id=thread_id, role=role, content=content, metadata_=metadata)
    if created_at is not None:
        message.created_at = created_at
    db.add(message)
    await db.flush()
    await db.refresh(message)
    return message


async def get_thread_messages(db: AsyncSession, thread_id: UUID) -> list[Message]:
    result = await db.execute(
        select(Message)
        .where(Message.thread_id == thread_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars().all())


async def get_thread_discord_message_ids(db: AsyncSession, thread_id: UUID) -> set[str]:
    result = await db.execute(
        select(Message.metadata_["discord_message_id"].astext)
        .where(
            Message.thread_id == thread_id,
            Message.metadata_["source"].astext == "discord",
            Message.metadata_["discord_message_id"].astext.is_not(None),
        )
    )
    return {str(message_id) for message_id in result.scalars().all() if message_id}


async def update_thread_title(db: AsyncSession, thread_id: UUID, title: str) -> Thread | None:
    thread = await get_thread(db, thread_id)
    if thread:
        thread.title = title
        await db.flush()
        await db.refresh(thread)
    return thread


async def delete_thread(db: AsyncSession, thread_id: UUID) -> bool:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Thread)
        .options(selectinload(Thread.messages))
        .where(Thread.id == thread_id)
    )
    thread = result.scalar_one_or_none()
    if thread:
        await db.delete(thread)
        await db.flush()
        return True
    return False


async def get_message_count(db: AsyncSession, thread_id: UUID) -> int:
    result = await db.execute(
        select(func.count(Message.id)).where(Message.thread_id == thread_id)
    )
    return result.scalar_one()


# ── Discord Thread Links ──────────────────────────────────────────────

async def get_discord_link(db: AsyncSession, thread_id: UUID) -> DiscordThreadLink | None:
    result = await db.execute(
        select(DiscordThreadLink).where(DiscordThreadLink.thread_id == thread_id)
    )
    return result.scalar_one_or_none()


async def get_active_discord_links(db: AsyncSession) -> list[DiscordThreadLink]:
    result = await db.execute(
        select(DiscordThreadLink).where(DiscordThreadLink.is_active == True)
    )
    return list(result.scalars().all())


async def get_discord_link_by_discord_thread_id(
    db: AsyncSession, discord_thread_id: str
) -> DiscordThreadLink | None:
    result = await db.execute(
        select(DiscordThreadLink).where(
            DiscordThreadLink.discord_thread_id == discord_thread_id,
            DiscordThreadLink.is_active == True,
        )
    )
    return result.scalar_one_or_none()


async def create_discord_link(
    db: AsyncSession,
    thread_id: UUID,
    guild_id: str,
    channel_id: str,
    discord_thread_id: str,
    discord_thread_name: str,
) -> DiscordThreadLink:
    link = DiscordThreadLink(
        thread_id=thread_id,
        guild_id=guild_id,
        channel_id=channel_id,
        discord_thread_id=discord_thread_id,
        discord_thread_name=discord_thread_name,
    )
    db.add(link)
    await db.flush()
    await db.refresh(link)
    return link


async def update_discord_link_cursor(
    db: AsyncSession,
    link: DiscordThreadLink,
    last_discord_message_id: str | None,
) -> DiscordThreadLink:
    link.last_discord_message_id = last_discord_message_id
    await db.flush()
    await db.refresh(link)
    return link


async def update_discord_link_index_state(
    db: AsyncSession,
    link: DiscordThreadLink,
    *,
    indexed_discord_message_id: str | None = None,
    indexed_at=None,
    indexing_status: str | None = None,
    indexing_error: str | None = None,
    update_cursor: bool = False,
) -> DiscordThreadLink:
    if indexed_discord_message_id is not None:
        link.indexed_discord_message_id = indexed_discord_message_id
        if update_cursor:
            link.last_discord_message_id = indexed_discord_message_id
    if indexed_at is not None:
        link.indexed_at = indexed_at
    link.indexing_status = indexing_status
    link.indexing_error = indexing_error
    await db.flush()
    await db.refresh(link)
    return link


async def set_discord_link_active(db: AsyncSession, thread_id: UUID, is_active: bool) -> DiscordThreadLink | None:
    link = await get_discord_link(db, thread_id)
    if link:
        link.is_active = is_active
        await db.flush()
        await db.refresh(link)
    return link


# ── Discord Servers ───────────────────────────────────────────────────

async def upsert_discord_server(
    db: AsyncSession,
    guild_id: str,
    guild_name: str,
    default_channel_id: str | None = None,
) -> DiscordServer:
    result = await db.execute(select(DiscordServer).where(DiscordServer.guild_id == guild_id))
    server = result.scalar_one_or_none()
    if server:
        server.guild_name = guild_name
        if default_channel_id is not None:
            server.default_channel_id = default_channel_id
    else:
        server = DiscordServer(
            guild_id=guild_id,
            guild_name=guild_name,
            default_channel_id=default_channel_id,
        )
        db.add(server)
    await db.flush()
    await db.refresh(server)
    return server


async def get_discord_servers(db: AsyncSession) -> list[DiscordServer]:
    result = await db.execute(select(DiscordServer).order_by(DiscordServer.updated_at.desc()))
    return list(result.scalars().all())


async def get_discord_server(db: AsyncSession, guild_id: str) -> DiscordServer | None:
    result = await db.execute(select(DiscordServer).where(DiscordServer.guild_id == guild_id))
    return result.scalar_one_or_none()


async def get_discord_server_tool_overrides(db: AsyncSession, guild_id: str) -> list[DiscordServerToolOverride]:
    result = await db.execute(
        select(DiscordServerToolOverride).where(DiscordServerToolOverride.guild_id == guild_id)
    )
    return list(result.scalars().all())


async def set_discord_server_tool_overrides(
    db: AsyncSession,
    guild_id: str,
    overrides: list[dict],
) -> list[DiscordServerToolOverride]:
    from sqlalchemy import delete

    await db.execute(delete(DiscordServerToolOverride).where(DiscordServerToolOverride.guild_id == guild_id))
    new_overrides = []
    for o in overrides:
        override = DiscordServerToolOverride(
            guild_id=guild_id,
            server_id=o["server_id"],
            tool_name=o.get("tool_name"),
            enabled=o.get("enabled", False),
        )
        db.add(override)
        new_overrides.append(override)
    await db.flush()
    for o in new_overrides:
        await db.refresh(o)
    return new_overrides


async def get_discord_server_tool_override_map(db: AsyncSession, guild_id: str) -> dict[str, bool]:
    overrides = await get_discord_server_tool_overrides(db, guild_id)
    return {
        f"{o.server_id}:{o.tool_name}" if o.tool_name is not None else str(o.server_id): bool(o.enabled)
        for o in overrides
    }


async def create_mcp_server(
    db: AsyncSession,
    name: str,
    image: str,
    env_vars: dict | None = None,
    args: dict | None = None,
    registry_credentials: dict | None = None,
) -> MCPServer:
    from app.encryption import encrypt_dict
    encrypted_env = await encrypt_dict(env_vars or {})
    encrypted_args = await encrypt_dict(args or {})
    encrypted_registry_credentials = await encrypt_dict(registry_credentials or {})
    server = MCPServer(
        name=name,
        image=image,
        env_vars=encrypted_env,
        args=encrypted_args,
        registry_credentials=encrypted_registry_credentials,
    )
    db.add(server)
    await db.flush()
    await db.refresh(server)
    return server


async def get_mcp_servers(db: AsyncSession) -> list[MCPServer]:
    result = await db.execute(
        select(MCPServer).order_by(MCPServer.created_at.desc())
    )
    return list(result.scalars().all())


async def delete_mcp_server(db: AsyncSession, server_id: UUID) -> bool:
    result = await db.execute(
        select(MCPServer).where(MCPServer.id == server_id)
    )
    server = result.scalar_one_or_none()
    if server:
        await db.delete(server)
        await db.flush()
        return True
    return False


async def toggle_mcp_server(db: AsyncSession, server_id: UUID) -> MCPServer | None:
    result = await db.execute(
        select(MCPServer).where(MCPServer.id == server_id)
    )
    server = result.scalar_one_or_none()
    if server:
        server.is_active = not server.is_active
        await db.flush()
        await db.refresh(server)
    return server


async def update_mcp_server(
    db: AsyncSession,
    server_id: UUID,
    name: str | None = None,
    image: str | None = None,
    env_vars: dict | None = None,
    args: dict | None = None,
    registry_credentials: dict | None = None,
) -> MCPServer | None:
    from app.encryption import encrypt_dict
    result = await db.execute(
        select(MCPServer).where(MCPServer.id == server_id)
    )
    server = result.scalar_one_or_none()
    if server:
        if name is not None:
            server.name = name
        if image is not None:
            server.image = image
        if env_vars is not None:
            server.env_vars = await encrypt_dict(env_vars)
        if args is not None:
            server.args = await encrypt_dict(args)
        if registry_credentials is not None:
            server.registry_credentials = await encrypt_dict(registry_credentials)
        await db.flush()
        await db.refresh(server)
    return server


async def get_all_settings(db: AsyncSession) -> dict[str, str]:
    """Get all settings as a key-value dict."""
    result = await db.execute(select(Setting))
    rows = result.scalars().all()
    return {r.key: r.value for r in rows}


async def upsert_settings(db: AsyncSession, settings: dict[str, str]) -> None:
    """Insert or update multiple settings."""
    for key, value in settings.items():
        result = await db.execute(select(Setting).where(Setting.key == key))
        existing = result.scalar_one_or_none()
        if existing:
            existing.value = value
        else:
            db.add(Setting(key=key, value=value))
    await db.flush()


# ── Thread Tool Overrides ─────────────────────────────────────────────

async def get_thread_tool_overrides(db: AsyncSession, thread_id: UUID) -> list[ThreadToolOverride]:
    result = await db.execute(
        select(ThreadToolOverride).where(ThreadToolOverride.thread_id == thread_id)
    )
    return list(result.scalars().all())


async def set_thread_tool_overrides(
    db: AsyncSession, thread_id: UUID, overrides: list[dict]
) -> list[ThreadToolOverride]:
    """Replace all overrides for a thread with the given list.

    Each override dict has: server_id, tool_name (optional), enabled.
    """
    from sqlalchemy import delete
    await db.execute(
        delete(ThreadToolOverride).where(ThreadToolOverride.thread_id == thread_id)
    )

    new_overrides = []
    for o in overrides:
        override = ThreadToolOverride(
            thread_id=thread_id,
            server_id=o["server_id"],
            tool_name=o.get("tool_name"),
            enabled=o["enabled"],
        )
        db.add(override)
        new_overrides.append(override)

    await db.flush()
    for o in new_overrides:
        await db.refresh(o)
    return new_overrides
