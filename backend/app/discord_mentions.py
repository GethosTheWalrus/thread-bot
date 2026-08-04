"""Pure helpers for converting Discord mentions safely."""

import re
from app.agent_mentions import parse_agent_mention


def normalize_discord_user_mentions(content: str, mentions: list | None = None) -> str:
    """Make Discord user mention tokens readable and inert for the LLM."""
    text = content or ""
    for mention in mentions or []:
        user_id = None
        display_name = None
        if isinstance(mention, dict):
            user_id = mention.get("id")
            display_name = mention.get("global_name") or mention.get("username")
        else:
            user_id = getattr(mention, "id", None)
            display_name = (
                getattr(mention, "global_name", None)
                or getattr(mention, "display_name", None)
                or getattr(mention, "name", None)
            )
        if not user_id:
            continue
        label = f"@{display_name}" if display_name else f"Discord user {user_id}"
        text = text.replace(f"<@{user_id}>", f"{label} (Discord user)")
        text = text.replace(f"<@!{user_id}>", f"{label} (Discord user)")
    return re.sub(r"<@!?(\d+)>", r"Discord user \1", text)


def mention_display_names(user: dict) -> list[str]:
    names = []
    for key in ("global_name", "display_name", "username"):
        value = (user or {}).get(key)
        if value and value not in names:
            names.append(str(value))
    return names


def replace_readable_mentions(
    content: str,
    name_to_ids: dict[str, set[str]],
) -> tuple[str, list[str]]:
    """Resolve unambiguous readable names and return their notification allowlist."""
    resolved = content
    allowed_ids = []
    for name_key, user_ids in sorted(
        name_to_ids.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if not name_key or len(user_ids) != 1:
            continue
        user_id = next(iter(user_ids))
        pattern = re.compile(
            rf"(?<![\w<])(?:@\{{{re.escape(name_key)}\}}|@{re.escape(name_key)})(?![\w])",
            re.IGNORECASE,
        )
        resolved, count = pattern.subn(f"<@{user_id}>", resolved)
        if count:
            allowed_ids.append(user_id)
    return resolved, allowed_ids


def allowed_mentions_payload(user_ids: list[str] | None = None) -> dict:
    """Allow only explicitly resolved users; deny roles, everyone, and reply pings."""
    return {
        "parse": [],
        "users": list(dict.fromkeys(user_ids or [])),
        "roles": [],
        "replied_user": False,
    }


def classify_inbound_agent_route(content: str, handles: list[str], *, bot_mentioned: bool) -> str | None:
    """Return an agent handle, ``moderator``, or None for passive chatter."""
    result = parse_agent_mention(content, handles)
    if result.target_handle:
        return result.target_handle
    if bot_mentioned:
        return "moderator"
    return None


def inbound_agent_handle(content: str, handles: list[str]) -> str | None:
    """Return the explicitly addressed known handle, if any.

    This is intentionally separate from ``classify_inbound_agent_route``:
    callers need to distinguish an unknown ``@name`` from ordinary chatter
    and from a native mention of the bot (which targets the moderator).
    """
    result = parse_agent_mention(content, handles)
    return result.target_handle


def has_explicit_handle(content: str) -> bool:
    text = re.sub(r"<[@#&]!?[0-9]+>", "", content or "")
    return bool(re.search(r"(?<![\w@])@\{?[A-Za-z0-9][A-Za-z0-9_.-]*\}?\b", text))
