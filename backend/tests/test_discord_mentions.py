"""Unit tests for safe Discord mention resolution."""

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.discord_mentions import (
    allowed_mentions_payload,
    normalize_discord_user_mentions,
    replace_readable_mentions,
    classify_inbound_agent_route,
    has_explicit_handle,
)


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


if __name__ == "__main__":
    unittest.main()
