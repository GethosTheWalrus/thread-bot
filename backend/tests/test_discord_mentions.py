"""Unit tests for safe Discord mention resolution."""

import sys
import unittest
import asyncio
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.discord_mentions import (
    allowed_mentions_payload,
    normalize_discord_user_mentions,
    replace_readable_mentions,
    classify_inbound_agent_route,
    discord_agent_label,
    has_explicit_handle,
)
from app.discord_integration import (
    _approval_prompt_text,
    _format_activity_trace,
    parse_discord_approval_decision,
)
from app.activities import llm_activities


class DiscordMentionTests(unittest.TestCase):
    def test_normalizes_known_and_unknown_tokens_to_inert_text(self):
        self.assertEqual(
            normalize_discord_user_mentions(
                "Hi <@123> and <@456>",
                [{"id": "123", "global_name": "Alice"}],
            ),
            "Hi @Alice (Discord user) and Discord user 456",
        )

    def test_resolves_plain_and_braced_unique_names(self):
        content, allowed = replace_readable_mentions(
            "Ask @Alice, then notify @{Bob Smith}.",
            {"alice": {"123"}, "bob smith": {"456"}},
        )
        self.assertEqual(content, "Ask <@123>, then notify <@456>.")
        self.assertEqual(set(allowed), {"123", "456"})

    def test_does_not_resolve_ambiguous_or_unknown_names(self):
        content, allowed = replace_readable_mentions(
            "Ask @Alex and @Nobody.",
            {"alex": {"123", "456"}},
        )
        self.assertEqual(content, "Ask @Alex and @Nobody.")
        self.assertEqual(allowed, [])
    def test_allowlist_denies_roles_everyone_and_reply_pings(self):
        self.assertEqual(
            allowed_mentions_payload(["123", "123"]),
            {
                "parse": [],
                "users": ["123"],
                "roles": [],
                "replied_user": False,
            },
        )

    def test_native_bot_mention_is_not_an_unknown_handle(self):
        assert not has_explicit_handle("<@123> please help")
        assert classify_inbound_agent_route("<@123> please help", ["research"], bot_mentioned=True) == "moderator"

    def test_unmentioned_chatter_has_no_agent_route(self):
        assert classify_inbound_agent_route("just chatting", ["research"], bot_mentioned=False) is None

    def test_agent_label_is_readable_and_strips_discord_markdown(self):
        assert discord_agent_label("OSRS **Researcher**", "osrs_researcher") == "OSRS Researcher (@osrs_researcher)"
        assert discord_agent_label(None, "mod") == "mod (@mod)"

    def test_agent_action_traces_keep_identity_and_tools_run_scoped(self):
        osrs = _format_activity_trace({
            "agent_name": "OSRS Researcher",
            "agent_handle": "osrs",
            "order": ["action-a"],
            "steps": {"action-a": {"tool": "mcp:DuckDuckGo:search", "status": "running"}},
        })
        moderator = _format_activity_trace({
            "agent_name": "Moderator",
            "agent_handle": "mod",
            "order": ["action-b"],
            "steps": {"action-b": {"tool": "builtin:calculator", "status": "done", "success": True}},
        })
        assert "OSRS Researcher (@osrs)" in osrs
        assert "mcp:DuckDuckGo:search" in osrs
        assert "Moderator (@mod)" not in osrs
        assert "Moderator (@mod)" in moderator
        assert "builtin:calculator" in moderator
        assert "OSRS Researcher (@osrs)" not in moderator

    def test_approval_prompt_requires_an_exact_reply_and_is_mention_safe(self):
        from datetime import datetime, timezone

        prompt = _approval_prompt_text(
            approval_id="12345678-aaaa-bbbb-cccc-123456789abc",
            agent_name="OSRS **Researcher**",
            agent_handle="osrs",
            tool_identity="mcp:DuckDuckGo:search",
            risk_level="medium",
            target={"site": "oldschool.runescape.wiki"},
            arguments={"query": "dragon claws"},
            expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            intended_actor_id="42",
        )
        assert prompt.startswith("<@42>\n**Approval required · OSRS Researcher (@osrs)**")
        assert "Reply **to this message** with exactly **approve** or **deny**" in prompt
        assert "mcp:DuckDuckGo:search" in prompt
        assert "12345678" in prompt

    def test_approval_decision_accepts_only_exact_approve_or_deny(self):
        assert parse_discord_approval_decision(" approve ") == "approved"
        assert parse_discord_approval_decision("DENY") == "denied"
        assert parse_discord_approval_decision("approve please") is None
        assert parse_discord_approval_decision("yes") is None
        assert parse_discord_approval_decision("") is None


@pytest.mark.asyncio
async def test_agent_typing_activity_pulses_and_heartbeats(monkeypatch):
    pulses = []
    heartbeats = []

    async def pulse(thread_id, channel_id, token):
        pulses.append((thread_id, channel_id, token))

    async def stop_after_first_pulse(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr("app.discord_integration._send_discord_typing_quick", pulse)
    monkeypatch.setattr(llm_activities, "heartbeat", heartbeats.append)
    monkeypatch.setattr(llm_activities.asyncio, "sleep", stop_after_first_pulse)

    with pytest.raises(asyncio.CancelledError):
        await llm_activities.maintain_discord_typing({
            "discord": {
                "discord_thread_id": "thread-1",
                "channel_id": "channel-1",
                "bot_token": "secret",
            },
        })

    assert pulses == [("thread-1", "channel-1", "secret")]
    assert heartbeats == [{"discord_thread_id": "thread-1"}]


if __name__ == "__main__":
    unittest.main()
