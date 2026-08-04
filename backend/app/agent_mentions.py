"""Deterministic, transport-neutral agent mention parsing."""
from dataclasses import dataclass
import re


class AmbiguousUserMention(ValueError):
    pass


@dataclass(frozen=True)
class MentionResult:
    target_handle: str | None
    user_mentioned: bool = False


def _masked(text: str) -> str:
    # Preserve offsets while making code and escaped tokens impossible to match.
    text = re.sub(r"```[\s\S]*?```|`[^`\n]*`", lambda m: " " * len(m.group()), text)
    text = re.sub(r"\\@", "  ", text)
    text = re.sub(r"@@", "  ", text)
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", lambda m: " " * len(m.group()), text)
    # Discord native user/channel/role mentions are not textual handles.
    return re.sub(r"<[@#&]!?[0-9]+>", lambda m: " " * len(m.group()), text)


def parse_agent_mention(content: str, agent_handles: list[str] | set[str], *, user_names: list[str] | set[str] = (), current_handle: str | None = None) -> MentionResult:
    """Resolve at most one destination.

    Complete handles are case-insensitive.  ``@user`` is reserved for the
    originating human; other user names must be unambiguous.  Agent output may
    address only the first valid *other* agent; self and unknown handles are
    ignored so a model cannot create an unbounded fan-out.
    """
    text = _masked(content or "")
    handles = {str(x).casefold(): str(x) for x in agent_handles}
    if isinstance(user_names, dict):
        user_names_cf = {str(key).casefold(): len(value) if isinstance(value, (list, set, tuple)) else int(value) for key, value in user_names.items()}
    else:
        user_names_cf = {str(x).casefold(): 1 for x in user_names}
    matches = list(re.finditer(r"(?<![\w@])@\{?([A-Za-z0-9][A-Za-z0-9_.-]*)\}?\b", text))
    for match in matches:
        token = match.group(1).casefold()
        if token == "user":
            return MentionResult(None, True)
        if token in handles:
            if current_handle and token == current_handle.casefold():
                continue
            return MentionResult(handles[token], False)
        if token in user_names_cf:
            if user_names_cf[token] != 1:
                raise AmbiguousUserMention(f"ambiguous user mention: @{match.group(1)}")
            return MentionResult(None, True)
    return MentionResult(None, False)


# Friendly aliases for callers that prefer a noun-oriented name.
parse_mentions = parse_agent_mention
parse_agent_mentions = parse_agent_mention
resolve_agent_mention = parse_agent_mention
