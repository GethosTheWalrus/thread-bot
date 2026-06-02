import asyncio
from datetime import timedelta
from uuid import UUID

import aiohttp
from temporalio.client import Client as TemporalClient

from app.config import get_discord_config, get_llm_config, get_settings


DISCORD_API_BASE = "https://discord.com/api/v10"


class DiscordIntegrationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        discord_code: int | None = None,
        body: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.discord_code = discord_code
        self.body = body


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bot {token}",
        "Content-Type": "application/json",
        "User-Agent": "ThreadBot Discord Integration",
    }


def _discord_enabled(config: dict | None = None) -> bool:
    config = config or get_discord_config()
    return bool(config.get("enabled") and config.get("bot_token"))


async def _load_fresh_discord_config() -> dict:
    """Load DB-backed Discord settings for worker-side activity processes."""
    from app.config import load_settings_from_db

    await load_settings_from_db()
    return get_discord_config()


async def _request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    discord_config: dict | None = None,
) -> dict | list | None:
    config = discord_config or await _load_fresh_discord_config()
    token = config.get("bot_token")
    if not token:
        raise DiscordIntegrationError("Discord bot token is not configured")

    async with aiohttp.ClientSession(headers=_headers(token)) as session:
        async with session.request(method, f"{DISCORD_API_BASE}{path}", json=json) as resp:
            text = await resp.text()
            if resp.status >= 400:
                discord_code = None
                try:
                    import json as json_mod
                    body = json_mod.loads(text) if text else {}
                    discord_code = body.get("code") if isinstance(body, dict) else None
                except Exception:
                    pass
                raise DiscordIntegrationError(
                    f"Discord API {resp.status}: {text}",
                    status=resp.status,
                    discord_code=discord_code,
                    body=text,
                )
            if not text:
                return None
            return await resp.json()


async def _send_discord_typing_quick(discord_thread_id: str, discord_channel_id: str | None, bot_token: str) -> None:
    """Lightweight typing pulse — no config lookup, no full config loading.
    Pulses in both the thread and the parent channel so typing is visible
    regardless of whether the user is in the thread or the source channel.
    """
    if not discord_thread_id or not bot_token:
        return
    try:
        async with aiohttp.ClientSession(headers=_headers(bot_token)) as session:
            # Thread typing (always works when user is in the thread)
            try:
                async with session.post(f"{DISCORD_API_BASE}/channels/{discord_thread_id}/typing") as resp:
                    if resp.status >= 400:
                        print(f"[discord] thread typing failed: {resp.status} {await resp.text()}", flush=True)
            except Exception:
                pass
            # Channel typing (so the indicator shows in the parent channel too)
            if discord_channel_id and discord_channel_id != discord_thread_id:
                try:
                    async with session.post(f"{DISCORD_API_BASE}/channels/{discord_channel_id}/typing") as resp:
                        if resp.status >= 400:
                            print(f"[discord] channel typing failed: {resp.status} {await resp.text()}", flush=True)
                except Exception:
                    pass
    except Exception:
        pass  # Typing is best-effort, non-critical


async def send_discord_typing(
    discord_thread_id: str,
    discord_config: dict | None = None,
) -> None:
    config = discord_config or await _load_fresh_discord_config()
    if not _discord_enabled(config):
        return
    await _send_discord_typing_quick(discord_thread_id, config.get("channel_id"), config.get("bot_token"))


async def _keep_discord_typing_until_done(workflow_handle, discord_config: dict) -> None:
    """Refresh Discord typing while a workflow is running.

    Discord typing indicators expire after a few seconds, so this runs in the
    Discord integration process that started the workflow and exits when the
    Temporal workflow completes, fails, or is cancelled.
    """
    if not _discord_enabled(discord_config):
        return
    discord_thread_id = discord_config.get("discord_thread_id")
    bot_token = discord_config.get("bot_token")
    if not discord_thread_id or not bot_token:
        return

    result_task = asyncio.create_task(workflow_handle.result())
    try:
        while not result_task.done():
            await _send_discord_typing_quick(discord_thread_id, discord_config.get("channel_id"), bot_token)
            try:
                await asyncio.wait_for(asyncio.shield(result_task), timeout=8)
            except asyncio.TimeoutError:
                continue
            except Exception:
                return
    finally:
        if not result_task.done():
            result_task.cancel()


def _discord_event_activity_id(guild_id: str, channel_id: str, event_id: str) -> str:
    return f"discord-event-{guild_id}-{channel_id}-{event_id}"


async def _claim_discord_event(
    temporal_client: TemporalClient,
    *,
    guild_id: str,
    channel_id: str,
    event_id: str | None,
) -> bool:
    if not event_id:
        return True

    from temporalio.common import ActivityIDConflictPolicy, ActivityIDReusePolicy
    from temporalio.exceptions import ActivityAlreadyStartedError
    from app.activities.llm_activities import claim_discord_event

    settings = get_settings()
    activity_id = _discord_event_activity_id(guild_id, channel_id, event_id)
    try:
        await temporal_client.start_activity(
            claim_discord_event,
            {"event_id": event_id, "guild_id": guild_id, "channel_id": channel_id},
            id=activity_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            schedule_to_close_timeout=timedelta(seconds=10),
            id_reuse_policy=ActivityIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=ActivityIDConflictPolicy.USE_EXISTING,
        )
        return True
    except ActivityAlreadyStartedError:
        print(f"[discord] duplicate event ignored: {activity_id}", flush=True)
        return False
    except Exception as exc:
        print(f"[discord] claim activity failed for {activity_id}: {exc}", flush=True)
        return False


async def get_bot_user_id() -> str | None:
    if not _discord_enabled():
        return None
    data = await _request("GET", "/users/@me")
    return str(data.get("id")) if isinstance(data, dict) else None


async def get_discord_guild(guild_id: str, discord_config: dict | None = None) -> dict:
    config = discord_config or await _load_fresh_discord_config()
    if not _discord_enabled(config):
        return {"id": guild_id, "name": guild_id}
    try:
        data = await _request("GET", f"/guilds/{guild_id}", discord_config=config)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"id": guild_id, "name": guild_id}


async def create_discord_thread(channel_id: str, name: str) -> dict:
    payload = {
        "name": name[:100] or "ThreadBot Thread",
        "type": 11,
        "auto_archive_duration": 10080,
    }
    data = await _request("POST", f"/channels/{channel_id}/threads", json=payload)
    if not isinstance(data, dict):
        raise DiscordIntegrationError("Discord did not return a thread object")
    return data


async def apply_discord_server_tool_defaults(db, thread_id, guild_id: str) -> None:
    from app.database.crud import (
        get_discord_server_tool_overrides,
        get_mcp_servers,
        set_thread_tool_overrides,
    )

    discord_overrides = await get_discord_server_tool_overrides(db, guild_id)
    server_enabled = {
        str(o.server_id): bool(o.enabled)
        for o in discord_overrides
        if o.tool_name is None
    }
    tool_enabled = {
        (str(o.server_id), o.tool_name): bool(o.enabled)
        for o in discord_overrides
        if o.tool_name is not None
    }
    servers_with_tool_overrides = {server_id for server_id, _ in tool_enabled}
    servers = await get_mcp_servers(db)
    thread_overrides = []
    for server in servers:
        server_id = str(server.id)
        if not server_enabled.get(server_id, False):
            thread_overrides.append({
                "server_id": server.id,
                "tool_name": None,
                "enabled": False,
            })
            continue

        if server_id not in servers_with_tool_overrides:
            continue

        for tool in server.cached_tools or []:
            tool_name = tool.get("name") if isinstance(tool, dict) else None
            if tool_name and not tool_enabled.get((server_id, tool_name), False):
                thread_overrides.append({
                    "server_id": server.id,
                    "tool_name": tool_name,
                    "enabled": False,
                })

    await set_thread_tool_overrides(db, thread_id, thread_overrides)


async def update_discord_thread_name(discord_thread_id: str, name: str, discord_config: dict | None = None) -> None:
    config = discord_config or await _load_fresh_discord_config()
    if not _discord_enabled(config):
        return
    await _request(
        "PATCH",
        f"/channels/{discord_thread_id}",
        json={"name": name[:100] or "ThreadBot Thread"},
        discord_config=config,
    )


async def delete_discord_thread(discord_thread_id: str, discord_config: dict | None = None) -> None:
    config = discord_config or await _load_fresh_discord_config()
    if not _discord_enabled(config):
        return
    try:
        await _request("DELETE", f"/channels/{discord_thread_id}", discord_config=config)
    except DiscordIntegrationError as exc:
        # If someone already deleted it in Discord, local deletion can still proceed.
        if exc.status == 404:
            return
        if exc.status == 403 and exc.discord_code == 50013:
            raise DiscordIntegrationError(
                "Missing Discord permissions to delete the linked thread. "
                "Grant the ThreadBot Discord bot Manage Threads and Manage Channels "
                "permissions in the target Discord channel, then try deleting again.",
                status=exc.status,
                discord_code=exc.discord_code,
                body=exc.body,
            ) from exc
        raise


async def post_discord_message(
    discord_thread_id: str,
    content: str,
    discord_config: dict | None = None,
    reply_to_message_id: str | None = None,
) -> str | None:
    config = discord_config or await _load_fresh_discord_config()
    if not _discord_enabled(config):
        return None
    last_id = None
    chunks = [content[i:i + 1900] for i in range(0, len(content), 1900)] or [" "]
    for index, chunk in enumerate(chunks):
        payload = {"content": chunk}
        if reply_to_message_id and index == 0:
            payload["message_reference"] = {
                "message_id": reply_to_message_id,
                "channel_id": discord_thread_id,
                "fail_if_not_exists": False,
            }
        data = await _request(
            "POST",
            f"/channels/{discord_thread_id}/messages",
            json=payload,
            discord_config=config,
        )
        if isinstance(data, dict):
            last_id = str(data.get("id"))
    return last_id


def format_threadbot_message(role: str, content: str) -> str | None:
    if role == "user":
        return f"**ThreadBot UI User:**\n{content}"
    if role == "assistant":
        return content
    return None


def _format_assistant_for_discord(content: str, discord_config: dict | None = None) -> str:
    prefix = (discord_config or {}).get("assistant_response_prefix") or ""
    return f"{prefix}{content}" if prefix else content


async def sync_message_to_discord(
    thread_id: UUID,
    role: str,
    content: str,
    metadata: dict | None = None,
    discord_config: dict | None = None,
) -> str | None:
    config = discord_config or await _load_fresh_discord_config()
    if not _discord_enabled(config) or metadata and metadata.get("source") == "discord":
        return None
    formatted = format_threadbot_message(role, content)
    if not formatted:
        return None
    if role == "assistant":
        formatted = _format_assistant_for_discord(formatted, config)

    discord_thread_id = config.get("discord_thread_id")
    if not discord_thread_id:
        from app.database import AsyncSessionLocal
        from app.database.crud import get_discord_link

        async with AsyncSessionLocal() as db:
            link = await get_discord_link(db, thread_id)
            if not link or not link.is_active:
                return None
            discord_thread_id = link.discord_thread_id
    try:
        reply_to_message_id = config.get("reply_to_message_id") if role == "assistant" else None
        return await post_discord_message(
            discord_thread_id,
            formatted,
            discord_config=config,
            reply_to_message_id=reply_to_message_id,
        )
    except Exception as exc:
        print(f"[discord] failed to post message for thread {thread_id}: {exc}", flush=True)
    return None


async def sync_title_to_discord(thread_id: UUID, title: str, discord_config: dict | None = None) -> None:
    config = discord_config or await _load_fresh_discord_config()
    if not _discord_enabled(config):
        return

    discord_thread_id = config.get("discord_thread_id")
    if not discord_thread_id:
        from app.database import AsyncSessionLocal
        from app.database.crud import get_discord_link

        async with AsyncSessionLocal() as db:
            link = await get_discord_link(db, thread_id)
            if not link or not link.is_active:
                return
            discord_thread_id = link.discord_thread_id
            try:
                await update_discord_thread_name(discord_thread_id, title, discord_config=config)
                link.discord_thread_name = title[:100] or "ThreadBot Thread"
                await db.commit()
            except Exception as exc:
                print(f"[discord] failed to update title for thread {thread_id}: {exc}", flush=True)
            return

    try:
        await update_discord_thread_name(discord_thread_id, title, discord_config=config)
    except Exception as exc:
        print(f"[discord] failed to update title for thread {thread_id}: {exc}", flush=True)


async def post_existing_thread_to_discord(thread_id: UUID) -> str | None:
    from app.database import AsyncSessionLocal
    from app.database.crud import get_discord_link, get_thread_messages, update_discord_link_cursor

    async with AsyncSessionLocal() as db:
        link = await get_discord_link(db, thread_id)
        if not link:
            return None
        messages = await get_thread_messages(db, thread_id)
        last_id = None
        for message in messages:
            formatted = format_threadbot_message(message.role, message.content)
            if formatted:
                last_id = await post_discord_message(link.discord_thread_id, formatted)
        if last_id:
            await update_discord_link_cursor(db, link, last_id)
            await db.commit()
        return last_id


async def fetch_discord_messages(discord_thread_id: str, after: str | None = None) -> list[dict]:
    path = f"/channels/{discord_thread_id}/messages?limit=50"
    if after:
        path += f"&after={after}"
    data = await _request("GET", path)
    if not isinstance(data, list):
        return []
    return list(reversed(data))


def _parse_threadbot_command(content: str) -> str | None:
    text = content.strip()
    for prefix in ("/threadbot", "!threadbot"):
        if text == prefix:
            return ""
        if text.startswith(prefix + " "):
            return text[len(prefix):].strip()
    return None


async def _start_thread_from_discord_command(
    temporal_client: TemporalClient,
    source_message: dict,
    prompt: str,
) -> None:
    author = source_message.get("author") or {}
    username = author.get("global_name") or author.get("username") or "Discord user"
    await start_thread_from_discord_prompt(
        temporal_client,
        prompt,
        username,
        source_message_id=str(source_message.get("id")),
        source_event_id=str(source_message.get("id")),
    )


async def start_thread_from_discord_prompt(
    temporal_client: TemporalClient,
    prompt: str,
    sender_name: str,
    *,
    source_message_id: str | None = None,
    source_message_link: str | None = None,
    source_event_id: str | None = None,
    channel_id: str | None = None,
    guild_id: str | None = None,
    guild_name: str | None = None,
) -> dict | None:
    from app.database import AsyncSessionLocal
    from app.database.crud import (
        add_message,
        create_discord_link,
        create_thread,
        upsert_discord_server,
        update_discord_link_cursor,
    )

    config = await _load_fresh_discord_config()
    channel_id = channel_id or config.get("channel_id")
    guild_id = guild_id or config.get("guild_id")
    if not channel_id or not guild_id:
        raise DiscordIntegrationError("Discord guild and channel are required")
    claimed = await _claim_discord_event(
        temporal_client,
        guild_id=guild_id,
        channel_id=channel_id,
        event_id=source_event_id or source_message_id,
    )
    if not claimed:
        return None
    if not guild_name:
        guild_info = await get_discord_guild(guild_id, config)
        guild_name = str(guild_info.get("name") or guild_id)

    title_seed = " ".join(prompt.split()[:6]).strip() or "Discord Thread"

    async with AsyncSessionLocal() as db:
        thread = await create_thread(db, "Discord Thread", parent_id=None)
        await upsert_discord_server(db, guild_id, guild_name, channel_id)
        await apply_discord_server_tool_defaults(db, thread.id, guild_id)
        discord_thread = await create_discord_thread(channel_id, title_seed[:100] or "ThreadBot Thread")
        link = await create_discord_link(
            db,
            thread.id,
            guild_id,
            channel_id,
            str(discord_thread["id"]),
            str(discord_thread.get("name") or title_seed or "ThreadBot Thread"),
        )
        local_content = f"{sender_name} (Discord): {prompt}"
        metadata = {
            "source": "discord",
            "sender_name": sender_name,
            "command": "threadbot",
        }
        if source_message_id:
            metadata["discord_message_id"] = source_message_id
        if source_message_link:
            metadata["discord_message_link"] = source_message_link
        await add_message(
            db,
            thread.id,
            "user",
            local_content,
            metadata=metadata,
        )
        await db.commit()

    mirrored_id = await post_discord_message(
        link.discord_thread_id,
        f"**{sender_name} started a ThreadBot thread from Discord:**\n{prompt}",
        discord_config={**config, "discord_thread_id": link.discord_thread_id},
    )
    if mirrored_id:
        async with AsyncSessionLocal() as db:
            db_link = await db.get(type(link), link.id)
            if db_link:
                await update_discord_link_cursor(db, db_link, mirrored_id)
                await db.commit()

    await start_discord_reply_workflow(
        temporal_client,
        link,
        local_content,
        reply_to_message_id=mirrored_id,
        assistant_response_prefix=f"Answering {source_message_link}: " if source_message_link else None,
    )
    from app.api.routes import broadcast_thread_updated
    await broadcast_thread_updated(str(thread.id))

    return {
        "thread_id": str(thread.id),
        "discord_thread_id": link.discord_thread_id,
        "discord_thread_name": link.discord_thread_name,
    }


async def poll_discord_commands_once(temporal_client: TemporalClient, bot_user_id: str | None = None) -> None:
    from app.database import AsyncSessionLocal
    from app.database.crud import upsert_settings
    from app.models.models import Setting
    from sqlalchemy import select

    config = await _load_fresh_discord_config()
    if not _discord_enabled(config) or not config.get("channel_id"):
        return

    channel_id = config["channel_id"]

    async with AsyncSessionLocal() as db:
        row = await db.execute(select(Setting).where(Setting.key == "discord:commands:cursor"))
        row = row.scalar_one_or_none()
        cursor = row.value if row and row.value else None

    messages = await fetch_discord_messages(channel_id, cursor)
    if not messages:
        return

    last_seen = str(messages[-1].get("id"))
    if not cursor:
        async with AsyncSessionLocal() as db:
            await upsert_settings(db, {"discord:commands:cursor": last_seen})
        return

    for message in messages:
        author = message.get("author") or {}
        if bot_user_id and str(author.get("id")) == bot_user_id:
            continue
        prompt = _parse_threadbot_command(message.get("content") or "")
        if prompt is None:
            continue
        if not prompt:
            await post_discord_message(channel_id, "Usage: `/threadbot your prompt`", discord_config=config)
            continue
        await _start_thread_from_discord_command(temporal_client, message, prompt)

    async with AsyncSessionLocal() as db:
        await upsert_settings(db, {"discord:commands:cursor": last_seen})


async def start_discord_reply_workflow(
    temporal_client: TemporalClient,
    link,
    message: str,
    reply_to_message_id: str | None = None,
    assistant_response_prefix: str | None = None,
) -> None:
    import uuid as uuid_mod
    from app.workflows.thread_workflow import RunThreadWorkflow

    thread_id = link.thread_id
    settings = get_settings()
    llm_config = get_llm_config().copy()
    config = await _load_fresh_discord_config()
    llm_config["discord"] = {
        "enabled": config.get("enabled"),
        "bot_token": config.get("bot_token"),
        "guild_id": link.guild_id,
        "channel_id": link.channel_id,
        "discord_thread_id": link.discord_thread_id,
        "discord_thread_name": link.discord_thread_name,
    }
    if reply_to_message_id:
        llm_config["discord"]["reply_to_message_id"] = reply_to_message_id
    if assistant_response_prefix:
        llm_config["discord"]["assistant_response_prefix"] = assistant_response_prefix
    run_id = f"discord-thread-{thread_id}-{uuid_mod.uuid4().hex[:8]}"
    handle = await temporal_client.start_workflow(
        RunThreadWorkflow.run,
        {"thread_id": str(thread_id), "message": message, "llm_config": llm_config},
        id=run_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
    )
    asyncio.create_task(_keep_discord_typing_until_done(handle, llm_config["discord"]))


async def poll_discord_once(temporal_client: TemporalClient, bot_user_id: str | None = None) -> None:
    if not _discord_enabled():
        return
    bot_user_id = bot_user_id or await get_bot_user_id()

    from app.database import AsyncSessionLocal
    from app.database.crud import add_message, get_active_discord_links, update_discord_link_cursor

    async with AsyncSessionLocal() as db:
        links = await get_active_discord_links(db)

    for link in links:
        try:
            messages = await fetch_discord_messages(link.discord_thread_id, link.last_discord_message_id)
            last_seen = link.last_discord_message_id
            for message in messages:
                last_seen = str(message.get("id"))
                author = message.get("author") or {}
                if str(author.get("id")) == bot_user_id:
                    continue
                content = (message.get("content") or "").strip()
                if not content:
                    continue
                claimed = await _claim_discord_event(
                    temporal_client,
                    guild_id=link.guild_id,
                    channel_id=link.discord_thread_id,
                    event_id=str(message.get("id")),
                )
                if not claimed:
                    continue
                username = author.get("global_name") or author.get("username") or "Discord user"
                local_content = f"{username} (Discord): {content}"
                async with AsyncSessionLocal() as db:
                    await add_message(
                        db,
                        link.thread_id,
                        "user",
                        local_content,
                        metadata={
                            "source": "discord",
                            "sender_name": username,
                            "discord_message_id": str(message.get("id")),
                        },
                    )
                    await db.commit()
                await start_discord_reply_workflow(
                    temporal_client,
                    link,
                    local_content,
                    reply_to_message_id=str(message.get("id")),
                )

            if last_seen and last_seen != link.last_discord_message_id:
                async with AsyncSessionLocal() as db:
                    db_link = await db.get(type(link), link.id)
                    if db_link:
                        await update_discord_link_cursor(db, db_link, last_seen)
                        await db.commit()
        except Exception as exc:
            print(f"[discord] sync failed for thread {link.thread_id}: {exc}", flush=True)


async def discord_poll_loop(temporal_client: TemporalClient) -> None:
    bot_user_id = None
    while True:
        config = get_discord_config()
        interval = max(5, int(config.get("poll_interval_seconds") or 10))
        try:
            if _discord_enabled(config):
                bot_user_id = bot_user_id or await get_bot_user_id()
                await poll_discord_commands_once(temporal_client, bot_user_id)
                await poll_discord_once(temporal_client, bot_user_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[discord] poll loop error: {exc}", flush=True)
        await asyncio.sleep(interval)
