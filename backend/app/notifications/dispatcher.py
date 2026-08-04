import aiohttp
from app.security import autonomy_flags, security_mode, validate_outbound_url


async def dispatch(route: dict, payload: dict, credential: dict | None = None, mode: str | None = None) -> dict:
    from app.effect_policy import blocked_effect
    if (blocked := blocked_effect(mode, "notification")):
        return {"delivered": False, "suppressed": True, "error": blocked}
    channel = route.get("channel")
    if security_mode() != "admin_token" or not autonomy_flags().get("autonomy_side_effects_enabled", False):
        return {"delivered": False, "error": "external notifications are disabled"}
    if channel == "in_app":
        return {"delivered": True, "channel": channel}
    if channel == "thread":
        return {"delivered": True, "channel": channel, "write_thread": True}
    if channel == "webhook":
        url = route.get("config", {}).get("url")
        validate_outbound_url(url, route.get("config", {}).get("allowed_hosts", []))
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            headers = {"Authorization": f"Bearer {credential['secret']}"} if credential and route.get("config", {}).get("auth", "bearer") == "bearer" else {}
            async with session.post(url, json=payload, headers=headers, allow_redirects=False) as response:
                response.raise_for_status()
        return {"delivered": True, "channel": channel}
    if channel == "discord":
        url = route.get("config", {}).get("webhook_url")
        validate_outbound_url(url, route.get("config", {}).get("allowed_hosts", []))
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.post(url, json={"content": str(payload.get("message", "")), "allowed_mentions": {"parse": []}}, allow_redirects=False) as response:
                response.raise_for_status()
        return {"delivered": True, "channel": channel}
    if channel == "discord_thread":
        from app.discord_integration import post_discord_message
        thread_id = route.get("config", {}).get("discord_thread_id")
        if not thread_id:
            return {"delivered": False, "error": "discord thread is missing"}
        await post_discord_message(thread_id, str(payload.get("message", "")))
        return {"delivered": True, "channel": channel}
    return {"delivered": False, "error": "unsupported notification channel"}
