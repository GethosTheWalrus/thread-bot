import asyncio
import json
import os
import re
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone
from uuid import UUID

import aiohttp
from temporalio.client import Client as TemporalClient

from app.config import get_discord_config, get_llm_config, get_settings
from app.discord_mentions import (
    allowed_mentions_payload,
    discord_agent_label,
    mention_display_names,
    normalize_discord_user_mentions,
    replace_readable_mentions,
)


DISCORD_API_BASE = "https://discord.com/api/v10"


def _discord_user_content(content: str, mentions: list | None = None) -> str:
    return normalize_discord_user_mentions(content, mentions).strip()


def _discord_image_attachments(message: dict) -> list[dict]:
    images = []
    for attachment in message.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        url = attachment.get("url") or attachment.get("proxy_url")
        content_type = attachment.get("content_type") or ""
        filename = attachment.get("filename") or "image"
        if not url:
            continue
        is_image = content_type.startswith("image/") or filename.lower().endswith(
            (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
        )
        if not is_image:
            continue
        images.append({
            "url": url,
            "source_url": attachment.get("url") or url,
            "proxy_url": attachment.get("proxy_url"),
            "filename": filename,
            "content_type": content_type or "image/*",
            "width": attachment.get("width"),
            "height": attachment.get("height"),
        })
    return images


async def persist_discord_image_attachments(image_attachments: list[dict] | None) -> list[dict]:
    """Copy Discord CDN images into ThreadBot storage before their URLs expire."""
    if not image_attachments:
        return []

    from app.database import AsyncSessionLocal
    from app.models.models import GeneratedImage

    llm_config = get_llm_config()
    image_dir = llm_config.get("generated_image_dir") or "/tmp/threadbot-generated-images"
    public_base_url = str(llm_config.get("public_base_url") or "").rstrip("/")
    os.makedirs(image_dir, exist_ok=True)

    persisted: list[dict] = []
    timeout = aiohttp.ClientTimeout(total=45)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for attachment in image_attachments:
            if not isinstance(attachment, dict):
                continue
            current_url = str(attachment.get("url") or "")
            if "/api/generated-images/" in current_url:
                persisted.append(attachment)
                continue

            raw = attachment.get("content") if isinstance(attachment.get("content"), bytes) else None
            content_type = str(attachment.get("content_type") or "image/png").split(";", 1)[0]
            source_url = ""
            try:
                if raw is None:
                    candidates = []
                    for value in (attachment.get("source_url"), attachment.get("proxy_url"), current_url):
                        candidate = str(value or "")
                        if candidate.startswith(("http://", "https://")) and candidate not in candidates:
                            candidates.append(candidate)
                    candidates.sort(key=lambda url: "placeholder.png" in url)

                    for candidate in candidates:
                        async with session.get(candidate, allow_redirects=True) as resp:
                            if resp.status != 200:
                                print(f"[discord] failed to copy image attachment: HTTP {resp.status} {candidate}", flush=True)
                                continue
                            response_type = (resp.headers.get("Content-Type") or content_type or "image/png").split(";", 1)[0]
                            if not response_type.startswith("image/"):
                                continue
                            fetched = await resp.content.read(12 * 1024 * 1024 + 1)
                            if len(fetched) > 12 * 1024 * 1024:
                                print(f"[discord] skipped oversized image attachment {candidate}", flush=True)
                                continue
                            raw = fetched
                            content_type = response_type
                            source_url = candidate
                            break

                    if raw is None:
                        persisted.append({k: v for k, v in attachment.items() if k != "content"})
                        continue
                else:
                    source_url = str(attachment.get("source_url") or attachment.get("proxy_url") or current_url)
            except Exception as exc:
                print(f"[discord] failed to copy image attachment {source_url}: {exc}", flush=True)
                persisted.append({k: v for k, v in attachment.items() if k != "content"})
                continue

            if len(raw) > 12 * 1024 * 1024:
                print(f"[discord] skipped oversized image attachment {source_url or current_url}", flush=True)
                persisted.append({k: v for k, v in attachment.items() if k != "content"})
                continue
            if not content_type.startswith("image/"):
                persisted.append({k: v for k, v in attachment.items() if k != "content"})
                continue

            ext = os.path.splitext(str(attachment.get("filename") or ""))[1].lower()
            if ext not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
                ext = {
                    "image/jpeg": ".jpg",
                    "image/png": ".png",
                    "image/gif": ".gif",
                    "image/webp": ".webp",
                    "image/bmp": ".bmp",
                }.get(content_type, ".png")
            stored_filename = f"discord-{uuid_mod.uuid4().hex}{ext}"
            with open(os.path.join(image_dir, stored_filename), "wb") as f:
                f.write(raw)
            async with AsyncSessionLocal() as db:
                await db.merge(GeneratedImage(
                    filename=stored_filename,
                    content=raw,
                    content_type=content_type,
                ))
                await db.commit()

            local_url = f"{public_base_url}/api/generated-images/{stored_filename}" if public_base_url else f"/api/generated-images/{stored_filename}"
            updated = {k: v for k, v in attachment.items() if k != "content"}
            updated["url"] = local_url
            updated["source_url"] = source_url
            updated["content_type"] = content_type
            persisted.append(updated)

    return persisted


def _content_with_image_lines(content: str, image_attachments: list[dict]) -> str:
    lines = [content.strip()] if content and content.strip() else []
    for attachment in image_attachments:
        url = attachment.get("url")
        if url:
            lines.append(f"Image attachment: {attachment.get('filename') or 'image'} {url}")
    return "\n".join(lines)


def _discord_mentions_user(content: str, mentions: list | None, user_id: str | None) -> bool:
    if not user_id:
        return False
    if f"<@{user_id}>" in (content or "") or f"<@!{user_id}>" in (content or ""):
        return True
    for mention in mentions or []:
        mention_id = mention.get("id") if isinstance(mention, dict) else getattr(mention, "id", None)
        if str(mention_id) == str(user_id):
            return True
    return False


def _strip_discord_user_mention(content: str, user_id: str | None) -> str:
    text = content or ""
    if not user_id:
        return text.strip()
    return text.replace(f"<@{user_id}>", "").replace(f"<@!{user_id}>", "").strip()


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


def _multipart_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bot {token}",
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


async def _request_multipart(
    method: str,
    path: str,
    *,
    payload: dict,
    files: list[dict],
    discord_config: dict | None = None,
) -> dict | list | None:
    import json as json_mod

    config = discord_config or await _load_fresh_discord_config()
    token = config.get("bot_token")
    if not token:
        raise DiscordIntegrationError("Discord bot token is not configured")

    form = aiohttp.FormData()
    form.add_field("payload_json", json_mod.dumps(payload), content_type="application/json")
    for idx, file_info in enumerate(files):
        form.add_field(
            f"files[{idx}]",
            file_info["content"],
            filename=file_info.get("filename") or f"image-{idx + 1}.png",
            content_type=file_info.get("content_type") or "image/png",
        )

    async with aiohttp.ClientSession(headers=_multipart_headers(token)) as session:
        async with session.request(method, f"{DISCORD_API_BASE}{path}", data=form) as resp:
            text = await resp.text()
            if resp.status >= 400:
                discord_code = None
                try:
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


async def _start_title_activity(
    temporal_client: TemporalClient,
    workflow_id: str,
    workflow_result,
) -> None:
    if not isinstance(workflow_result, dict):
        return
    title_args = workflow_result.get("title")
    if not title_args:
        return

    from temporalio.common import ActivityIDConflictPolicy, ActivityIDReusePolicy
    from temporalio.exceptions import ActivityAlreadyStartedError
    from app.activities.llm_activities import generate_and_update_title

    settings = get_settings()
    activity_id = f"title-{workflow_id}"
    try:
        await temporal_client.start_activity(
            generate_and_update_title,
            title_args,
            id=activity_id,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            schedule_to_close_timeout=timedelta(seconds=90),
            start_to_close_timeout=timedelta(seconds=60),
            id_reuse_policy=ActivityIDReusePolicy.REJECT_DUPLICATE,
            id_conflict_policy=ActivityIDConflictPolicy.FAIL,
        )
        print(f"[title] enqueued standalone activity {activity_id}", flush=True)
    except ActivityAlreadyStartedError:
        return
    except Exception as exc:
        print(f"[title] failed to start standalone activity {activity_id}: {exc}", flush=True)


async def _keep_discord_typing_until_done(
    workflow_handle,
    discord_config: dict,
    temporal_client: TemporalClient | None = None,
    workflow_id: str | None = None,
) -> None:
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
    if temporal_client and workflow_id and result_task.done() and not result_task.cancelled():
        try:
            await _start_title_activity(temporal_client, workflow_id, result_task.result())
        except Exception as exc:
            print(f"[title] discord watcher failed to enqueue title: {exc}", flush=True)


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
            id_conflict_policy=ActivityIDConflictPolicy.FAIL,
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
    servers = await get_mcp_servers(db)
    thread_overrides = []
    for server in servers:
        server_id = str(server.id)
        server_overrides = [o for o in discord_overrides if str(o.server_id) == server_id]
        if not any(o.tool_name is None for o in server_overrides):
            thread_overrides.append({
                "server_id": server.id,
                "tool_name": None,
                "enabled": False,
            })
        thread_overrides.extend({
            "server_id": server.id,
            "tool_name": override.tool_name,
            "enabled": bool(override.enabled),
        } for override in server_overrides)

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
    files: list[dict] | None = None,
    allowed_user_mentions: list[str] | None = None,
) -> str | None:
    config = discord_config or await _load_fresh_discord_config()
    if not _discord_enabled(config):
        return None
    last_id = None
    chunks = [content[i:i + 1900] for i in range(0, len(content), 1900)] or [" "]
    for index, chunk in enumerate(chunks):
        payload = {
            "content": chunk,
            "allowed_mentions": allowed_mentions_payload(allowed_user_mentions),
        }
        if reply_to_message_id and index == 0:
            payload["message_reference"] = {
                "message_id": reply_to_message_id,
                "channel_id": discord_thread_id,
                "fail_if_not_exists": False,
            }
        chunk_files = files if index == 0 else None
        if chunk_files:
            data = await _request_multipart(
                "POST",
                f"/channels/{discord_thread_id}/messages",
                payload=payload,
                files=chunk_files,
                discord_config=config,
            )
        else:
            data = await _request(
                "POST",
                f"/channels/{discord_thread_id}/messages",
                json=payload,
                discord_config=config,
            )
        if isinstance(data, dict):
            last_id = str(data.get("id"))
    return last_id


def _approval_prompt_text(
    *,
    approval_id: str,
    agent_name: str | None,
    agent_handle: str | None,
    tool_identity: str | None,
    risk_level: str,
    target: dict,
    arguments: dict,
    expires_at: datetime,
    intended_actor_id: str | None,
) -> str:
    identity = discord_agent_label(agent_name, agent_handle)
    attention = f"<@{intended_actor_id}>\n" if intended_actor_id else ""
    target_text = json.dumps(target or {}, sort_keys=True, ensure_ascii=True)[:500]
    arguments_text = json.dumps(arguments or {}, sort_keys=True, ensure_ascii=True)[:800]
    expires = int(expires_at.timestamp())
    return (
        f"{attention}**Approval required · {identity}**\n"
        f"Tool: `{tool_identity or 'unknown action'}`\n"
        f"Risk: **{risk_level}** · Expires <t:{expires}:R>\n"
        f"Target: `{target_text}`\n"
        f"Arguments (redacted): `{arguments_text}`\n\n"
        "Reply **to this message** with exactly **approve** or **deny**. "
        f"Request `{approval_id[:8]}`"
    )


def parse_discord_approval_decision(content: str) -> str | None:
    normalized = content.strip().casefold()
    if normalized == "approve":
        return "approved"
    if normalized == "deny":
        return "denied"
    return None


async def post_discord_approval_request(
    approval_id: str,
    *,
    reply_to_message_id: str | None = None,
    force_new: bool = False,
) -> str | None:
    """Post and durably correlate one Discord approval request."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent_models import Agent
    from app.models.approval_models import ApprovalProviderPrompt, ApprovalRequest
    from app.models.models import DiscordThreadLink
    from app.models.run_models import AgentRun

    async with AsyncSessionLocal() as db:
        if not force_new:
            existing_prompt = await db.scalar(
                select(ApprovalProviderPrompt)
                .where(
                    ApprovalProviderPrompt.request_id == UUID(str(approval_id)),
                    ApprovalProviderPrompt.channel == "discord",
                )
                .order_by(ApprovalProviderPrompt.created_at.desc())
            )
            if existing_prompt:
                return existing_prompt.provider_message_id
        row = (
            await db.execute(
                select(ApprovalRequest, AgentRun, Agent, DiscordThreadLink)
                .join(AgentRun, AgentRun.id == ApprovalRequest.run_id)
                .join(Agent, Agent.id == AgentRun.agent_id)
                .join(DiscordThreadLink, DiscordThreadLink.thread_id == AgentRun.thread_id)
                .where(
                    ApprovalRequest.id == UUID(str(approval_id)),
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.expires_at > datetime.now(timezone.utc),
                    DiscordThreadLink.is_active.is_(True),
                )
            )
        ).first()
        if not row:
            return None
        approval, run, agent, link = row
        snapshot = {
            "approval_id": str(approval.id),
            "agent_name": agent.name,
            "agent_handle": agent.handle,
            "tool_identity": approval.tool_identity,
            "risk_level": approval.risk_level,
            "target": approval.target or {},
            "arguments": approval.redacted_arguments or {},
            "expires_at": approval.expires_at,
            "intended_actor_id": run.origin_id,
            "discord_thread_id": link.discord_thread_id,
            "origin_message_id": run.origin_message_id,
        }

    prompt = _approval_prompt_text(**{
        key: snapshot[key]
        for key in (
            "approval_id", "agent_name", "agent_handle", "tool_identity",
            "risk_level", "target", "arguments", "expires_at", "intended_actor_id",
        )
    })
    message_id = await post_discord_message(
        snapshot["discord_thread_id"],
        prompt,
        discord_config=await _load_fresh_discord_config(),
        reply_to_message_id=reply_to_message_id or snapshot["origin_message_id"],
        allowed_user_mentions=[snapshot["intended_actor_id"]] if snapshot["intended_actor_id"] else None,
    )
    if not message_id:
        return None
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(
            select(ApprovalProviderPrompt).where(
                ApprovalProviderPrompt.channel == "discord",
                ApprovalProviderPrompt.provider_channel_id == snapshot["discord_thread_id"],
                ApprovalProviderPrompt.provider_message_id == message_id,
            )
        )
        if not existing:
            db.add(
                ApprovalProviderPrompt(
                    request_id=UUID(snapshot["approval_id"]),
                    channel="discord",
                    provider_channel_id=snapshot["discord_thread_id"],
                    provider_message_id=message_id,
                    intended_actor_id=snapshot["intended_actor_id"],
                )
            )
            await db.commit()
    return message_id


async def handle_discord_approval_reply(
    temporal_client: TemporalClient,
    *,
    guild_id: str,
    discord_thread_id: str,
    sender_id: str,
    content: str,
    reply_to_message_id: str | None,
    source_message_id: str | None,
) -> bool:
    """Consume an exact reply to one approval prompt, if it is one."""
    if not reply_to_message_id:
        return False
    from sqlalchemy import select
    from app.approval_service import (
        ApprovalDecisionError,
        record_approval_decision,
        signal_approval_decision,
    )
    from app.database import AsyncSessionLocal
    from app.models.approval_models import ApprovalProviderPrompt, ApprovalRequest

    async with AsyncSessionLocal() as db:
        match = (
            await db.execute(
                select(ApprovalProviderPrompt, ApprovalRequest)
                .join(ApprovalRequest, ApprovalRequest.id == ApprovalProviderPrompt.request_id)
                .where(
                    ApprovalProviderPrompt.channel == "discord",
                    ApprovalProviderPrompt.provider_channel_id == discord_thread_id,
                    ApprovalProviderPrompt.provider_message_id == reply_to_message_id,
                )
            )
        ).first()
        if not match:
            return False
        provider_prompt, approval = match
        approval_snapshot = {
            "id": approval.id,
            "workspace_id": approval.workspace_id,
            "run_id": approval.run_id,
            "status": approval.status,
            "expires_at": approval.expires_at,
            "intended_actor_id": provider_prompt.intended_actor_id,
        }

    claimed = await _claim_discord_event(
        temporal_client,
        guild_id=guild_id,
        channel_id=discord_thread_id,
        event_id=source_message_id,
    )
    if not claimed:
        return True

    if approval_snapshot["intended_actor_id"] and sender_id != approval_snapshot["intended_actor_id"]:
        await post_discord_message(
            discord_thread_id,
            "Only the user who initiated this Agent run can approve or deny this request.",
            reply_to_message_id=source_message_id,
        )
        return True

    decision = parse_discord_approval_decision(content)
    if decision is None:
        if approval_snapshot["status"] == "pending" and approval_snapshot["expires_at"] > datetime.now(timezone.utc):
            await post_discord_approval_request(
                str(approval_snapshot["id"]),
                reply_to_message_id=source_message_id,
                force_new=True,
            )
        else:
            await post_discord_message(
                discord_thread_id,
                "That approval request is no longer active.",
                reply_to_message_id=source_message_id,
            )
        return True

    try:
        async with AsyncSessionLocal() as db:
            result = await record_approval_decision(
                db,
                approval_id=approval_snapshot["id"],
                workspace_id=approval_snapshot["workspace_id"],
                decision=decision,
                actor_id=f"discord:{sender_id}",
                actor_type="human",
                channel="discord",
                provider_interaction_id=source_message_id or f"discord:{uuid_mod.uuid4()}",
            )
    except ApprovalDecisionError as exc:
        await post_discord_message(
            discord_thread_id,
            exc.message,
            reply_to_message_id=source_message_id,
        )
        return True

    await signal_approval_decision(result["run_id"], result["approval_id"])
    await post_discord_message(
        discord_thread_id,
        "Approved. The Agent may continue." if decision == "approved" else "Denied. The Agent will not perform this action.",
        reply_to_message_id=source_message_id,
    )
    return True


async def edit_discord_message(
    discord_thread_id: str,
    message_id: str,
    content: str,
    discord_config: dict | None = None,
) -> None:
    config = discord_config or await _load_fresh_discord_config()
    if not _discord_enabled(config) or not discord_thread_id or not message_id:
        return
    await _request(
        "PATCH",
        f"/channels/{discord_thread_id}/messages/{message_id}",
        json={
            "content": content[:1900] or " ",
            "allowed_mentions": allowed_mentions_payload(),
        },
        discord_config=config,
    )


def _preview(value: str, max_chars: int = 180) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _tool_input_lines(tool_name: str, args: dict) -> list[str]:
    name = tool_name.lower()
    lines = []
    url = args.get("url") or args.get("href") or args.get("link")
    query = (
        args.get("query")
        or args.get("q")
        or args.get("search")
        or args.get("search_terms")
        or args.get("keywords")
    )
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        lines.append(f"URL: <{_preview(url, 240)}>")
    if isinstance(query, str) and query.strip():
        label = "Search" if "search" in name or "duck" in name else "Query"
        lines.append(f"{label}: `{_preview(query, 160)}`")
    if name == "use_skill":
        skill_name = args.get("skill_name") or args.get("skill_id")
        reason = args.get("reason")
        if isinstance(skill_name, str) and skill_name.strip():
            lines.append(f"Skill: `{_preview(skill_name, 120)}`")
        if isinstance(reason, str) and reason.strip():
            lines.append(f"Reason: `{_preview(reason, 160)}`")
    if not lines and ("search" in name or "duck" in name):
        for key, value in args.items():
            if isinstance(value, str) and value.strip():
                lines.append(f"Search: `{_preview(value, 160)}`")
                break
    return lines[:3]


def _status_emoji(status: str, success: bool | None = None) -> str:
    if status == "running":
        return "⏳"
    if success is False:
        return "❌"
    return "✅"


def _format_activity_trace(state: dict) -> str:
    order = state.get("order") or []
    steps = state.get("steps") or {}
    identity = discord_agent_label(state.get("agent_name"), state.get("agent_handle"))
    lines = [f"**Agent activity · {identity}**"]
    if not order:
        lines.append("Preparing tools...")
        return "\n".join(lines)
    visible_steps = order[-8:]
    for call_id in visible_steps:
        step = steps.get(call_id) or {}
        tool = _preview(str(step.get("tool") or "tool"), 80)
        emoji = _status_emoji(str(step.get("status") or "running"), step.get("success"))
        lines.append(f"{emoji} **{tool}**")
        for detail in step.get("details") or []:
            lines.append(f"> {detail}")
    if len(order) > 8:
        lines.append(f"_Showing latest {len(visible_steps)} of {len(order)} tool steps._")
    if state.get("final_response_posted"):
        lines.append("**Final response posted.**")
    return "\n".join(lines)[:1900]


async def _load_activity_state(key: str) -> dict:
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.models import Setting

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Setting).where(Setting.key == key))
        row = result.scalar_one_or_none()
    if not row or not row.value:
        return {"order": [], "steps": {}}
    try:
        state = json.loads(row.value)
        return state if isinstance(state, dict) else {"order": [], "steps": {}}
    except Exception:
        return {"order": [], "steps": {}}


async def _save_activity_state(key: str, state: dict) -> None:
    from app.database import AsyncSessionLocal
    from app.database.crud import upsert_settings

    async with AsyncSessionLocal() as db:
        await upsert_settings(db, {key: json.dumps(state)})
        await db.commit()


async def sync_discord_tool_activity(
    event: dict,
    discord_config: dict | None = None,
) -> None:
    """Create/update a compact Discord activity trace for tool calls."""
    config = discord_config or {}
    if not _discord_enabled(config):
        return
    discord_thread_id = config.get("discord_thread_id")
    workflow_id = config.get("workflow_id") or config.get("active_workflow_id")
    if not discord_thread_id or not workflow_id:
        return

    event_type = event.get("type")
    if event_type not in {"tool_call", "tool_result"}:
        return

    key = f"discord:activity:{workflow_id}"
    state = await _load_activity_state(key)
    state.setdefault("order", [])
    state.setdefault("steps", {})
    if config.get("agent_name") or config.get("agent_handle"):
        state["agent_name"] = config.get("agent_name")
        state["agent_handle"] = config.get("agent_handle")

    if event_type == "tool_call":
        for tool_call in event.get("tool_calls") or []:
            if not isinstance(tool_call, dict):
                continue
            call_id = str(tool_call.get("id") or f"call-{len(state['order']) + 1}")
            function = tool_call.get("function") or {}
            tool_name = str(function.get("name") or "tool")
            try:
                args = json.loads(function.get("arguments") or "{}")
            except Exception:
                args = {}
            display_tool = tool_name
            if tool_name == "use_skill":
                skill_name = str(args.get("skill_name") or args.get("skill_id") or "skill").strip() or "skill"
                display_tool = f"skill:{skill_name}"
            if call_id not in state["order"]:
                state["order"].append(call_id)
            state["steps"][call_id] = {
                "tool": display_tool,
                "status": "running",
                "details": _tool_input_lines(tool_name, args),
            }
    elif event_type == "tool_result":
        call_id = str(event.get("tool_call_id") or "")
        if not call_id and state["order"]:
            call_id = str(state["order"][-1])
        if call_id:
            step = state["steps"].setdefault(call_id, {"tool": str(event.get("tool") or "tool")})
            step["status"] = "done"
            step["success"] = bool(event.get("success", True))
            if event.get("success") is False:
                content = str(event.get("content") or "")
                if content:
                    details = list(step.get("details") or [])
                    details.append(f"Error: `{_preview(content, 180)}`")
                    step["details"] = details[-3:]

    content = _format_activity_trace(state)
    message_id = state.get("message_id")
    if message_id:
        await edit_discord_message(discord_thread_id, str(message_id), content, discord_config=config)
    else:
        reply_to = config.get("reply_to_message_id")
        message_id = await post_discord_message(
            discord_thread_id,
            content,
            discord_config=config,
            reply_to_message_id=reply_to,
        )
        if message_id:
            state["message_id"] = message_id
    await _save_activity_state(key, state)


async def complete_discord_tool_activity(discord_config: dict | None = None) -> None:
    config = discord_config or {}
    if not _discord_enabled(config):
        return
    discord_thread_id = config.get("discord_thread_id")
    workflow_id = config.get("workflow_id") or config.get("active_workflow_id")
    if not discord_thread_id or not workflow_id:
        return
    key = f"discord:activity:{workflow_id}"
    state = await _load_activity_state(key)
    if not state.get("message_id"):
        return
    state["final_response_posted"] = True
    await edit_discord_message(
        discord_thread_id,
        str(state["message_id"]),
        _format_activity_trace(state),
        discord_config=config,
    )
    await _save_activity_state(key, state)


async def sync_agent_run_tool_activity(run_id: str, event: dict) -> None:
    """Sync one AgentRun's action progress with immutable Agent attribution."""
    from sqlalchemy import select
    from app.database import AsyncSessionLocal
    from app.models.agent_models import Agent
    from app.models.models import DiscordThreadLink
    from app.models.run_models import AgentRun

    try:
        async with AsyncSessionLocal() as db:
            run = await db.get(AgentRun, UUID(str(run_id)))
            if not run:
                return
            link = await db.scalar(
                select(DiscordThreadLink).where(
                    DiscordThreadLink.thread_id == run.thread_id,
                    DiscordThreadLink.is_active.is_(True),
                )
            )
            if not link:
                return
            agent = await db.get(Agent, run.agent_id)
        config = dict(await _load_fresh_discord_config())
        config.update({
            "discord_thread_id": link.discord_thread_id,
            "workflow_id": f"agent-run:{run.id}",
            "reply_to_message_id": run.origin_message_id,
            "agent_name": agent.name if agent else None,
            "agent_handle": agent.handle if agent else None,
        })
        await sync_discord_tool_activity(event, discord_config=config)
    except Exception as exc:
        print(f"[discord] Agent action sync failed for run {run_id}: {exc}", flush=True)


def format_threadbot_message(role: str, content: str) -> str | None:
    if role == "user":
        return f"**ThreadBot UI User:**\n{content}"
    if role == "assistant":
        return content
    return None


def _remove_image_attachment_lines(content: str) -> str:
    return "\n".join(
        line for line in (content or "").splitlines()
        if not line.startswith("Image attachment: ")
    ).strip()


def _format_assistant_for_discord(content: str, discord_config: dict | None = None) -> str:
    prefix = (discord_config or {}).get("assistant_response_prefix") or ""
    return f"{prefix}{content}" if prefix else content


async def _discord_files_from_generated_media_links(content: str, discord_config: dict | None = None) -> tuple[str, list[dict]]:
    """Turn assistant-generated media links into Discord file attachments.

    The saved ThreadBot message keeps Markdown for the web UI. Discord gets the
    bytes directly so generated images/videos are not presented as hosted URLs.
    """
    if not content or ("/api/generated-images/" not in content and "/api/generated-media/" not in content):
        return content, []

    import os
    import mimetypes
    from urllib.parse import urlparse
    from app.config import get_llm_config

    llm_config = get_llm_config()
    image_dir = llm_config.get("generated_image_dir") or "/tmp/threadbot-generated-images"
    media_dir = llm_config.get("generated_media_dir") or "/tmp/threadbot-generated-media"
    files = []

    async def _file_from_url(url: str, index: int) -> dict | None:
        parsed = urlparse(url)
        parsed_path = parsed.path or url
        local_match = re.search(r"/api/generated-(images|media)/([^/?#]+)", parsed_path)
        if local_match:
            media_kind = local_match.group(1)
            filename = local_match.group(2)
            if "/" in filename or "\\" in filename or filename.startswith("."):
                return None
            path = os.path.join(image_dir if media_kind == "images" else media_dir, filename)
            if not os.path.isfile(path):
                try:
                    from sqlalchemy import select
                    from app.database import AsyncSessionLocal
                    from app.models.models import GeneratedImage, GeneratedMedia

                    async with AsyncSessionLocal() as db:
                        model = GeneratedImage if media_kind == "images" else GeneratedMedia
                        result = await db.execute(
                            select(model).where(model.filename == filename)
                        )
                        media = result.scalar_one_or_none()
                    if not media:
                        return None
                    return {
                        "filename": filename,
                        "content": media.content,
                        "content_type": media.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream",
                    }
                except Exception as exc:
                    print(f"[discord] failed to load generated media {filename} from DB: {exc}", flush=True)
                    return None
            with open(path, "rb") as f:
                return {
                    "filename": filename,
                    "content": f.read(),
                    "content_type": mimetypes.guess_type(filename)[0] or "application/octet-stream",
                }

        if parsed.scheme not in {"http", "https"}:
            return None
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=timeout, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return None
                    content_type = resp.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
                    if not (content_type.startswith("image/") or content_type.startswith("video/")):
                        return None
                    raw = await resp.read()
                    if len(raw) > 24 * 1024 * 1024:
                        return None
                    ext = content_type.split("/", 1)[1].split(";", 1)[0] or "png"
                    if ext == "jpeg":
                        ext = "jpg"
                    return {
                        "filename": f"generated-media-{index}.{ext}",
                        "content": raw,
                        "content_type": content_type,
                    }
        except Exception as exc:
            print(f"[discord] failed to download generated media {url}: {exc}", flush=True)
            return None

    urls: list[str] = []
    for pattern in (
        r"!?\[[^\]]*\]\(((?:https?://[^\s)]+)?/api/generated-(?:images|media)/[^)]+)\)",
        r"src=[\"']((?:https?://[^\"']+)?/api/generated-(?:images|media)/[^\"']+)[\"']",
        r"(?<!\()((?:https?://\S+)?/api/generated-(?:images|media)/[^\s)<>\"']+)",
    ):
        for match in re.finditer(pattern, content, flags=re.IGNORECASE):
            url = match.group(1).strip().rstrip(".,>")
            if url not in urls:
                urls.append(url)

    for idx, url in enumerate(urls[:10], start=1):
        file_info = await _file_from_url(url, idx)
        if file_info:
            files.append(file_info)

    if not files:
        return content, []

    cleaned = re.sub(r"(?is)<video\b[^>]*>.*?/video>", "", content)
    cleaned = re.sub(r"!?\[[^\]]*\]\([^)]*/api/generated-(?:images|media)/[^)]+\)", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*(?:https?://\S+)?/api/generated-(?:images|media)/\S+\s*$", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*Generated image:\s*$", "", cleaned)
    cleaned = re.sub(r"(?im)^\s*Generated video:\s*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned or "Generated media:", files


async def _discord_files_from_image_urls(urls: list[dict] | list[str], discord_config: dict | None = None) -> list[dict]:
    if not urls:
        return []

    import os
    import mimetypes
    from urllib.parse import urlparse
    from app.config import get_llm_config

    llm_config = get_llm_config()
    image_dir = llm_config.get("generated_image_dir") or "/tmp/threadbot-generated-images"
    files = []

    async def _file_from_url(url: str, index: int) -> dict | None:
        parsed = urlparse(url)
        local_match = re.search(r"/api/generated-images/([^/?#]+)", parsed.path or url)
        if local_match:
            filename = local_match.group(1)
            if "/" in filename or "\\" in filename or filename.startswith("."):
                return None
            path = os.path.join(image_dir, filename)
            if not os.path.isfile(path):
                try:
                    from sqlalchemy import select
                    from app.database import AsyncSessionLocal
                    from app.models.models import GeneratedImage

                    async with AsyncSessionLocal() as db:
                        result = await db.execute(
                            select(GeneratedImage).where(GeneratedImage.filename == filename)
                        )
                        image = result.scalar_one_or_none()
                    if not image:
                        return None
                    return {
                        "filename": filename,
                        "content": image.content,
                        "content_type": image.content_type or "image/png",
                    }
                except Exception as exc:
                    print(f"[discord] failed to load uploaded image {filename} from DB: {exc}", flush=True)
                    return None
            with open(path, "rb") as f:
                return {
                    "filename": filename,
                    "content": f.read(),
                    "content_type": mimetypes.guess_type(filename)[0] or "image/png",
                }

        if parsed.scheme not in {"http", "https"}:
            return None
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=timeout, allow_redirects=True) as resp:
                    if resp.status != 200:
                        return None
                    content_type = resp.headers.get("Content-Type", "image/png")
                    if not content_type.startswith("image/"):
                        return None
                    raw = await resp.read()
                    if len(raw) > 24 * 1024 * 1024:
                        return None
                    ext = content_type.split("/", 1)[1].split(";", 1)[0] or "png"
                    if ext == "jpeg":
                        ext = "jpg"
                    return {
                        "filename": f"generated-image-{index}.{ext}",
                        "content": raw,
                        "content_type": content_type,
                    }
        except Exception as exc:
            print(f"[discord] failed to download uploaded image {url}: {exc}", flush=True)
            return None

    for idx, url in enumerate([u.get("url") if isinstance(u, dict) else u for u in urls][:10], start=1):
        if not isinstance(url, str) or not url:
            continue
        file_info = await _file_from_url(url.strip(), idx)
        if file_info:
            files.append(file_info)

    return files


async def _resolve_readable_mentions_for_discord(
    discord_thread_id: str,
    content: str,
    discord_config: dict | None = None,
) -> tuple[str, list[str]]:
    """Convert known readable @names back to Discord mention tokens.

    Incoming Discord mentions are normalized for the LLM as @display_name.
    If the model repeats one, Discord only sends a notification when the
    outbound message contains the real <@user_id> token.
    """
    if not content or "@" not in content:
        return content, []

    try:
        messages = await fetch_discord_messages(discord_thread_id, limit=100)
    except Exception:
        return content, []

    name_to_ids: dict[str, set[str]] = {}
    for message in messages:
        author = message.get("author") or {}
        author_id = author.get("id")
        if author_id:
            for name in mention_display_names(author):
                name_to_ids.setdefault(name.casefold(), set()).add(str(author_id))
        for mention in message.get("mentions") or []:
            mention_id = mention.get("id")
            if not mention_id:
                continue
            for name in mention_display_names(mention):
                name_to_ids.setdefault(name.casefold(), set()).add(str(mention_id))

    return replace_readable_mentions(content, name_to_ids)


async def sync_message_to_discord(
    thread_id: UUID,
    role: str,
    content: str,
    metadata: dict | None = None,
    discord_config: dict | None = None,
) -> str | None:
    config = dict(discord_config or await _load_fresh_discord_config())
    if metadata and metadata.get("agent_run_id"):
        config.setdefault("workflow_id", f"agent-run:{metadata['agent_run_id']}")
        config.setdefault("reply_to_message_id", metadata.get("origin_message_id"))
        config.setdefault("agent_name", metadata.get("agent_name"))
        config.setdefault("agent_handle", metadata.get("agent_handle"))
    if not _discord_enabled(config) or metadata and metadata.get("source") == "discord":
        return None
    formatted = format_threadbot_message(role, content)
    if not formatted:
        return None
    if role == "assistant":
        formatted = _format_assistant_for_discord(formatted, config)
        agent_handle = (metadata or {}).get("agent_handle")
        agent_name = (metadata or {}).get("agent_name")
        if agent_handle:
            formatted = f"**Agent: {discord_agent_label(agent_name, agent_handle)}**\n{formatted}"

    discord_thread_id = config.get("discord_thread_id")
    if not discord_thread_id:
        from app.database import AsyncSessionLocal
        from app.database.crud import get_discord_link

        async with AsyncSessionLocal() as db:
            link = await get_discord_link(db, thread_id)
            if not link or not link.is_active:
                return None
            discord_thread_id = link.discord_thread_id
            config["discord_thread_id"] = discord_thread_id
    try:
        files = []
        allowed_user_mentions = None
        image_attachments = (metadata or {}).get("image_attachments") or []
        if role == "assistant":
            origin_id = (metadata or {}).get("origin_id") or (metadata or {}).get("sender_id")
            if origin_id:
                # @user is the only reserved outbound token.  It is never
                # resolved through names or allowed to ping roles/everyone.
                parts = re.split(r"(```[\s\S]*?```|`[^`\n]*`)", formatted)
                for index in range(0, len(parts), 2):
                    parts[index] = re.sub(r"(?<![\w@])@user(?![\w])", f"<@{origin_id}>", parts[index], flags=re.IGNORECASE)
                formatted = "".join(parts)
            formatted, allowed_user_mentions = await _resolve_readable_mentions_for_discord(
                discord_thread_id,
                formatted,
                discord_config=config,
            )
            if origin_id and f"<@{origin_id}>" in formatted and origin_id not in (allowed_user_mentions or []):
                allowed_user_mentions = [*(allowed_user_mentions or []), str(origin_id)]
            formatted, markdown_files = await _discord_files_from_generated_media_links(formatted, discord_config=config)
            files.extend(markdown_files)
        if image_attachments:
            files.extend(await _discord_files_from_image_urls(image_attachments, discord_config=config))
            formatted = _remove_image_attachment_lines(formatted)
        reply_to_message_id = config.get("reply_to_message_id") if role == "assistant" else None
        posted_id = await post_discord_message(
            discord_thread_id,
            formatted,
            discord_config=config,
            reply_to_message_id=reply_to_message_id,
            files=files or None,
            allowed_user_mentions=allowed_user_mentions,
        )
        if role == "assistant":
            try:
                await complete_discord_tool_activity(config)
            except Exception as exc:
                print(f"[discord] failed to complete tool activity trace: {exc}", flush=True)
        return posted_id
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

    config = await _load_fresh_discord_config()
    async with AsyncSessionLocal() as db:
        link = await get_discord_link(db, thread_id)
        if not link:
            return None
        messages = await get_thread_messages(db, thread_id)
        last_id = None
        for message in messages:
            last_id = await sync_message_to_discord(
                thread_id,
                message.role,
                message.content,
                metadata=message.metadata_ or {},
                discord_config=config,
            )
        if last_id:
            await update_discord_link_cursor(db, link, last_id)
            await db.commit()
        return last_id


async def fetch_discord_messages(
    discord_thread_id: str,
    after: str | None = None,
    before: str | None = None,
    limit: int = 50,
) -> list[dict]:
    path = f"/channels/{discord_thread_id}/messages?limit={max(1, min(limit, 100))}"
    if after:
        path += f"&after={after}"
    if before:
        path += f"&before={before}"
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
        source_image_attachments=_discord_image_attachments(source_message),
    )


async def start_thread_from_discord_prompt(
    temporal_client: TemporalClient,
    prompt: str,
    sender_name: str,
    sender_id: str | None = None,
    *,
    source_message_id: str | None = None,
    source_message_link: str | None = None,
    source_event_id: str | None = None,
    channel_id: str | None = None,
    guild_id: str | None = None,
    guild_name: str | None = None,
    source_image_attachments: list[dict] | None = None,
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
        image_attachments = await persist_discord_image_attachments(source_image_attachments or [])
        local_content = _content_with_image_lines(_discord_user_content(prompt), image_attachments)
        metadata = {
            "source": "discord",
            "sender_name": sender_name,
            "command": "threadbot",
        }
        if sender_id:
            metadata["sender_id"] = sender_id
        if image_attachments:
            metadata["image_attachments"] = image_attachments
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
    config = await _load_fresh_discord_config()
    llm_config = get_llm_config().copy()
    from app.database import AsyncSessionLocal
    from sqlalchemy import select
    from app.database.crud import get_enabled_thread_skills, get_thread_tool_overrides

    async with AsyncSessionLocal() as db:
        thread_overrides = await get_thread_tool_overrides(db, thread_id)
        if thread_overrides:
            llm_config["tool_overrides"] = [
                {
                    "server_id": str(o.server_id),
                    "tool_name": o.tool_name,
                    "enabled": o.enabled,
                }
                for o in thread_overrides
            ]
        enabled_skills = await get_enabled_thread_skills(db, thread_id)
        if enabled_skills:
            llm_config["skills"] = [
                {
                    "id": str(skill.id),
                    "name": skill.name,
                    "description": skill.description or "",
                    "content": skill.content,
                }
                for skill in enabled_skills
                if skill.content and skill.content.strip()
            ]
        from app.database.crud import get_thread_llm_overrides
        from app.config import apply_thread_llm_overrides

        thread_llm_overrides = await get_thread_llm_overrides(db, thread_id)
        if thread_llm_overrides:
            llm_config = apply_thread_llm_overrides(llm_config, thread_llm_overrides)
        if "osrs_loadout" not in llm_config:
            from app.models.models import Thread
            from app.services.osrs_loadouts import resolve_thread_loadout, to_mcp_calculate_dps_loadout
            thread = await db.scalar(select(Thread).where(Thread.id == thread_id))
            if thread:
                selected_loadout, _ = await resolve_thread_loadout(db, thread.workspace_id, thread_id)
                if selected_loadout:
                    llm_config["osrs_loadout"] = to_mcp_calculate_dps_loadout(selected_loadout)
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
    llm_config["discord"]["workflow_id"] = run_id
    handle = await temporal_client.start_workflow(
        RunThreadWorkflow.run,
        {"thread_id": str(thread_id), "message": message, "llm_config": llm_config},
        id=run_id,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
    )
    asyncio.create_task(_keep_discord_typing_until_done(
        handle,
        llm_config["discord"],
        temporal_client=temporal_client,
        workflow_id=run_id,
    ))


async def start_discord_agent_dispatch(
    temporal_client: TemporalClient,
    *,
    link,
    agent,
    message,
    input_message_id,
    discord_message_id: str,
    sender_id: str | None,
    sender_name: str,
) -> None:
    """Create one attributed Discord trigger and route it through the agent coordinator."""
    from uuid import uuid4
    from app.database import AsyncSessionLocal
    from app.database.autonomy import create_trigger_event
    from app.workflows.agent_workflows import TriggerDispatchWorkflow

    async with AsyncSessionLocal() as db:
        event, created = await create_trigger_event(
            db, id=uuid4(), workspace_id=agent.workspace_id, agent_id=agent.id,
            trigger_id=None, schema_version=1, source="discord",
            event_type="discord.message", subject={
                "agent_handle": agent.handle, "guild_id": link.guild_id,
                "channel_id": link.discord_thread_id,
            }, occurred_at=datetime.now(timezone.utc),
            dedupe_key=f"message:{discord_message_id}", correlation_id=uuid4(),
            causation_id=None, origin_chain=[], trust="untrusted_content",
            payload={
                "message": message, "input_message_id": str(input_message_id),
                "origin_id": sender_id, "origin_message_id": discord_message_id,
                "origin_channel_id": link.discord_thread_id,
                "origin_guild_id": link.guild_id, "sender_name": sender_name,
                "response_mode": "both", "route": "discord_agent_mention",
            }, content_refs=[],
        )
        await db.commit()
    if not created:
        return
    await temporal_client.start_workflow(
        TriggerDispatchWorkflow.run, {"event_id": str(event.id)},
        id=f"trigger-dispatch:{event.id}", task_queue=get_settings().AGENT_TASK_QUEUE,
    )


async def _active_thread_workflow_id(temporal_client: TemporalClient, thread_id) -> str | None:
    for prefix in (f"thread-{thread_id}-", f"discord-thread-{thread_id}-", f"reachy-thread-{thread_id}-"):
        query = f'ExecutionStatus="Running" AND WorkflowId STARTS_WITH "{prefix}"'
        async for execution in temporal_client.list_workflows(query=query, limit=1):
            return execution.id
    return None


async def _maybe_signal_continue_response(
    temporal_client: TemporalClient,
    *,
    thread_id,
    discord_thread_id: str,
    content: str,
) -> bool:
    normalized = content.strip().lower()
    if normalized in {"continue", "yes", "y", "keep going", "go", "resume", "yes please"}:
        should_continue = True
    elif normalized in {"stop", "no", "n", "finish", "done", "no thanks"}:
        should_continue = False
    else:
        return False

    workflow_id = await _active_thread_workflow_id(temporal_client, thread_id)
    if not workflow_id:
        return False

    handle = temporal_client.get_workflow_handle(workflow_id)
    await handle.signal("respond_continue", should_continue)
    config = await _load_fresh_discord_config()
    await post_discord_message(
        discord_thread_id,
        "Continuing." if should_continue else "Stopping here.",
        discord_config={**config, "discord_thread_id": discord_thread_id},
    )
    return True


def _discord_index_in_progress(link) -> bool:
    if link.indexing_status not in {"queued", "running"} or not link.indexed_at:
        return False
    indexed_at = link.indexed_at
    if indexed_at.tzinfo is None:
        indexed_at = indexed_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - indexed_at < timedelta(minutes=10)


async def enqueue_stale_discord_index_workflows(
    temporal_client: TemporalClient,
    bot_user_id: str | None = None,
) -> None:
    from app.database import AsyncSessionLocal
    from app.database.crud import get_active_discord_links, update_discord_link_index_state
    from app.workflows.discord_index_workflow import IndexDiscordThreadWorkflow

    settings = get_settings()
    bot_user_id = bot_user_id or await get_bot_user_id()
    async with AsyncSessionLocal() as db:
        links = await get_active_discord_links(db)

    for link in links:
        try:
            if _discord_index_in_progress(link):
                continue
            latest = await fetch_discord_messages(link.discord_thread_id, limit=1)
            latest_message_id = str(latest[-1].get("id")) if latest else None
            if not latest_message_id or latest_message_id == link.indexed_discord_message_id:
                continue

            async with AsyncSessionLocal() as db:
                db_link = await db.get(type(link), link.id)
                if not db_link or not db_link.is_active or _discord_index_in_progress(db_link):
                    continue
                await update_discord_link_index_state(
                    db,
                    db_link,
                    indexed_at=datetime.now(timezone.utc),
                    indexing_status="queued",
                    indexing_error=None,
                )
                await db.commit()

            await temporal_client.start_workflow(
                IndexDiscordThreadWorkflow.run,
                {"link_id": str(link.id), "bot_user_id": bot_user_id},
                id=f"discord-index-{link.id}-{latest_message_id}-{uuid_mod.uuid4().hex[:8]}",
                task_queue=settings.TEMPORAL_TASK_QUEUE,
            )
        except Exception as exc:
            print(f"[discord] failed to enqueue index for thread {link.discord_thread_id}: {exc}", flush=True)


async def reply_to_existing_discord_thread(
    temporal_client: TemporalClient,
    *,
    discord_thread_id: str,
    guild_id: str,
    channel_id: str | None = None,
    guild_name: str | None = None,
    discord_thread_name: str | None = None,
    sender_name: str,
    sender_id: str | None = None,
    prompt: str,
    source_message_id: str | None,
    source_message_link: str | None = None,
    source_event_id: str | None = None,
    source_image_attachments: list[dict] | None = None,
) -> dict | None:
    """Reply to a user message that was sent inside an existing Discord thread.

    Looks up the existing ``discord_thread_links`` row by ``discord_thread_id``.
    If the Discord thread has not been linked yet, adopt it by creating a local
    ThreadBot thread/link without creating a new Discord thread. Then record the
    user message and start a reply workflow that posts back to the same Discord
    thread.
    """
    from app.database import AsyncSessionLocal
    from app.database.crud import (
        add_message,
        create_discord_link,
        create_thread,
        get_discord_link_by_discord_thread_id,
        update_discord_link_cursor,
        upsert_discord_server,
    )

    claimed = await _claim_discord_event(
        temporal_client,
        guild_id=guild_id,
        channel_id=discord_thread_id,
        event_id=source_event_id or source_message_id,
    )
    if not claimed:
        return None

    async with AsyncSessionLocal() as db:
        link = await get_discord_link_by_discord_thread_id(db, discord_thread_id)
        if link is None:
            if not guild_name:
                try:
                    config = await _load_fresh_discord_config()
                    guild_info = await get_discord_guild(guild_id, config)
                    guild_name = str(guild_info.get("name") or guild_id)
                except Exception:
                    guild_name = guild_id
            thread = await create_thread(db, "Discord Thread", parent_id=None)
            await upsert_discord_server(db, guild_id, guild_name, channel_id or discord_thread_id)
            await apply_discord_server_tool_defaults(db, thread.id, guild_id)
            link = await create_discord_link(
                db,
                thread.id,
                guild_id,
                channel_id or discord_thread_id,
                discord_thread_id,
                discord_thread_name or "Discord Thread",
            )
            print(
                f"[discord] adopted existing discord thread {discord_thread_id} "
                f"as ThreadBot thread {thread.id}",
                flush=True,
            )
        image_attachments = await persist_discord_image_attachments(source_image_attachments or [])
        local_content = _content_with_image_lines(_discord_user_content(prompt), image_attachments)
        metadata = {
            "source": "discord",
            "sender_name": sender_name,
        }
        if sender_id:
            metadata["sender_id"] = sender_id
        if source_message_id:
            metadata["discord_message_id"] = source_message_id
        if source_message_link:
            metadata["discord_message_link"] = source_message_link
        if image_attachments:
            metadata["image_attachments"] = image_attachments
        if await _maybe_signal_continue_response(
            temporal_client,
            thread_id=link.thread_id,
            discord_thread_id=discord_thread_id,
            content=prompt,
        ):
            return {
                "thread_id": str(link.thread_id),
                "discord_thread_id": link.discord_thread_id,
                "discord_thread_name": link.discord_thread_name,
            }
        await add_message(
            db,
            link.thread_id,
            "user",
            local_content,
            metadata=metadata,
        )
        if source_message_id:
            link.last_discord_message_id = source_message_id
            await update_discord_link_cursor(db, link, source_message_id)
        await db.commit()
        link_snapshot = link

    await start_discord_reply_workflow(
        temporal_client,
        link_snapshot,
        local_content,
        reply_to_message_id=source_message_id,
    )
    from app.api.routes import broadcast_thread_updated
    await broadcast_thread_updated(str(link_snapshot.thread_id))
    return {
        "thread_id": str(link_snapshot.thread_id),
        "discord_thread_id": link_snapshot.discord_thread_id,
        "discord_thread_name": link_snapshot.discord_thread_name,
    }


async def poll_discord_once(temporal_client: TemporalClient, bot_user_id: str | None = None) -> None:
    if not _discord_enabled():
        return
    bot_user_id = bot_user_id or await get_bot_user_id()

    from app.database import AsyncSessionLocal
    from app.database.crud import (
        add_message,
        get_active_discord_links,
        update_discord_link_cursor,
        update_discord_link_index_state,
    )

    async with AsyncSessionLocal() as db:
        links = await get_active_discord_links(db)

    for link in links:
        try:
            if not link.last_discord_message_id and not link.indexed_discord_message_id:
                continue
            messages = await fetch_discord_messages(link.discord_thread_id, link.last_discord_message_id)
            last_seen = link.last_discord_message_id
            for message in messages:
                last_seen = str(message.get("id"))
                author = message.get("author") or {}
                if str(author.get("id")) == bot_user_id:
                    continue
                raw_content = message.get("content") or ""
                reference = message.get("message_reference") or {}
                if await handle_discord_approval_reply(
                    temporal_client,
                    guild_id=link.guild_id,
                    discord_thread_id=link.discord_thread_id,
                    sender_id=str(author.get("id") or ""),
                    content=raw_content,
                    reply_to_message_id=str(reference.get("message_id")) if reference.get("message_id") else None,
                    source_message_id=str(message.get("id")) if message.get("id") else None,
                ):
                    continue
                mentions = message.get("mentions") or []
                should_reply = _discord_mentions_user(raw_content, mentions, bot_user_id)
                agent_target = None
                inactive_target = False
                async with AsyncSessionLocal() as roster_db:
                    from sqlalchemy import select
                    from app.models.models import Thread
                    from app.models.agent_models import Agent
                    from app.discord_mentions import classify_inbound_agent_route, has_explicit_handle
                    thread_row = await roster_db.get(Thread, link.thread_id)
                    if thread_row and thread_row.mode == "agent":
                        roster = list((await roster_db.execute(select(Agent).where(
                            Agent.thread_id == link.thread_id, Agent.status != "archived"))).scalars())
                        explicit_handle = has_explicit_handle(raw_content)
                        agent_target = classify_inbound_agent_route(raw_content, [a.handle for a in roster], bot_mentioned=should_reply)
                        target = next((a for a in roster if agent_target and a.handle.casefold() == agent_target.casefold()), None)
                        if explicit_handle and not target:
                            # Unknown handles are never silently redirected to
                            # the moderator.
                            agent_target = "__unknown__"
                            should_reply = False
                        elif target and target.status != "active":
                            # An explicit inactive destination must never fall
                            # through to the moderator.
                            should_reply = False
                            inactive_target = True
                        elif target:
                            should_reply = True
                        elif should_reply:
                            agent_target = next((a.handle for a in roster if a.is_moderator and a.status == "active"), "moderator")
                        else:
                            agent_target = None
                content = _strip_discord_user_mention(raw_content, bot_user_id) if should_reply else raw_content.strip()
                image_attachments = await persist_discord_image_attachments(_discord_image_attachments(message))
                if not content and not image_attachments:
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
                local_content = _content_with_image_lines(
                    _discord_user_content(content, mentions),
                    image_attachments,
                )
                if await _maybe_signal_continue_response(
                    temporal_client,
                    thread_id=link.thread_id,
                    discord_thread_id=link.discord_thread_id,
                    content=content,
                ):
                    continue
                metadata = {
                    "source": "discord",
                    "sender_name": username,
                    "sender_id": str(author.get("id")) if author.get("id") else None,
                    "discord_message_id": str(message.get("id")),
                    "discord_channel_id": link.discord_thread_id,
                    "discord_guild_id": link.guild_id,
                    "reply_requested": should_reply,
                    "agent_target_handle": agent_target,
                }
                if image_attachments:
                    metadata["image_attachments"] = image_attachments
                input_message = None
                async with AsyncSessionLocal() as db:
                    input_message = await add_message(
                        db,
                        link.thread_id,
                        "user",
                        local_content,
                        metadata=metadata,
                    )
                    await db.commit()
                from app.api.routes import broadcast_thread_updated
                await broadcast_thread_updated(str(link.thread_id))
                target = None
                if should_reply and agent_target:
                    async with AsyncSessionLocal() as roster_db:
                        from sqlalchemy import select
                        from app.models.agent_models import Agent
                        target = await roster_db.scalar(select(Agent).where(
                            Agent.thread_id == link.thread_id,
                            Agent.handle.ilike(agent_target),
                            Agent.status == "active",
                        ))
                if agent_target == "__unknown__":
                    await post_discord_message(
                        link.discord_thread_id,
                        "I couldn't find an active agent for that handle. Please mention an active agent or mention ThreadBot for the moderator.",
                        discord_config=await _load_fresh_discord_config(),
                        reply_to_message_id=str(message.get("id")),
                    )
                elif should_reply and target:
                    await start_discord_agent_dispatch(
                        temporal_client, link=link, agent=target, message=local_content,
                        input_message_id=input_message.id,
                        discord_message_id=str(message.get("id")), sender_id=str(author.get("id")) if author.get("id") else None,
                        sender_name=username,
                    )
                elif should_reply and not agent_target:
                    await start_discord_reply_workflow(
                        temporal_client, link, local_content,
                        reply_to_message_id=str(message.get("id")),
                    )
                elif inactive_target:
                    await post_discord_message(
                        link.discord_thread_id,
                        "That agent is not active and cannot receive this message.",
                        discord_config=await _load_fresh_discord_config(),
                        reply_to_message_id=str(message.get("id")),
                    )

            if last_seen and last_seen != link.last_discord_message_id:
                async with AsyncSessionLocal() as db:
                    db_link = await db.get(type(link), link.id)
                    if db_link:
                        if db_link.indexed_discord_message_id:
                            await update_discord_link_index_state(
                                db,
                                db_link,
                                indexed_discord_message_id=last_seen,
                                indexed_at=datetime.now(timezone.utc),
                                indexing_status="complete",
                                indexing_error=None,
                                update_cursor=True,
                            )
                        else:
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
                await enqueue_stale_discord_index_workflows(temporal_client, bot_user_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"[discord] poll loop error: {exc}", flush=True)
        await asyncio.sleep(interval)
