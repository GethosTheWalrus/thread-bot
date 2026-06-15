"""Unit tests for app.text_sanitize.strip_markdown_for_tts."""

import sys
import unittest
from pathlib import Path

# Make the backend package importable when running this file directly.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.text_sanitize import strip_markdown_for_tts


class StripMarkdownForTTSTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(strip_markdown_for_tts(""), "")
        self.assertEqual(strip_markdown_for_tts(None), "")

    def test_plain_text_unchanged(self):
        self.assertEqual(
            strip_markdown_for_tts("Plain text with no markdown at all."),
            "Plain text with no markdown at all.",
        )

    def test_bold_underscore(self):
        self.assertEqual(
            strip_markdown_for_tts("This is __very__ important."),
            "This is very important.",
        )

    def test_bold_asterisk(self):
        self.assertEqual(
            strip_markdown_for_tts("This is **very** important."),
            "This is very important.",
        )

    def test_italic_underscore(self):
        self.assertEqual(
            strip_markdown_for_tts("This is _kind of_ important."),
            "This is kind of important.",
        )

    def test_italic_asterisk(self):
        self.assertEqual(
            strip_markdown_for_tts("This is *kind of* important."),
            "This is kind of important.",
        )

    def test_action_marker(self):
        self.assertEqual(
            strip_markdown_for_tts("Hello *smiles* — welcome back!"),
            "Hello smiles — welcome back!",
        )

    def test_action_marker_with_punctuation(self):
        self.assertEqual(
            strip_markdown_for_tts("Trailing punctuation: *wave*. Then more text."),
            "Trailing punctuation: wave. Then more text.",
        )

    def test_inline_code(self):
        self.assertEqual(
            strip_markdown_for_tts("Use the `print` function to display output."),
            "Use the print function to display output.",
        )

    def test_fenced_code_block(self):
        self.assertEqual(
            strip_markdown_for_tts("Look:\n```python\nprint('hi')\n```\nall done."),
            "Look:\n\nall done.",
        )

    def test_link_keeps_text(self):
        self.assertEqual(
            strip_markdown_for_tts("Visit [our site](https://example.com) for more."),
            "Visit our site for more.",
        )

    def test_image_keeps_alt(self):
        self.assertEqual(
            strip_markdown_for_tts("Look at ![a happy robot](https://x/y.png) here."),
            "Look at a happy robot here.",
        )

    def test_unordered_list(self):
        self.assertEqual(
            strip_markdown_for_tts(
                "Steps:\n- First, open the menu.\n- Then click save.\n- Done!"
            ),
            "Steps:\nFirst, open the menu.\nThen click save.\nDone!",
        )

    def test_ordered_list(self):
        self.assertEqual(
            strip_markdown_for_tts(
                "Steps:\n1. First\n2. Second\n3. Third"
            ),
            "Steps:\nFirst\nSecond\nThird",
        )

    def test_blockquote(self):
        self.assertEqual(
            strip_markdown_for_tts(
                "> Note: this is a blockquote.\n> It continues."
            ),
            "Note: this is a blockquote.\nIt continues.",
        )

    def test_headers(self):
        self.assertEqual(
            strip_markdown_for_tts("## Heading\n\nSome body text."),
            "Heading\n\nSome body text.",
        )

    def test_emoji_stripped(self):
        self.assertEqual(
            strip_markdown_for_tts("Got back from the trip! 🎉✈️ Great weather 😊"),
            "Got back from the trip! Great weather",
        )

    def test_latex_inline_stripped(self):
        self.assertEqual(
            strip_markdown_for_tts("Math: $E = mc^2$ is famous."),
            "Math: is famous.",
        )

    def test_mixed_markdown_and_emoji(self):
        self.assertEqual(
            strip_markdown_for_tts(
                "Mixed: *italic* and **bold** and `code` and emoji 🚀"
            ),
            "Mixed: italic and bold and code and emoji",
        )

    def test_horizontal_rule(self):
        self.assertEqual(
            strip_markdown_for_tts("Above\n\n---\n\nBelow"),
            "Above\n\nBelow",
        )

    def test_html_tags_stripped(self):
        self.assertEqual(
            strip_markdown_for_tts("Some <em>emphasis</em> here."),
            "Some emphasis here.",
        )

    def test_table_separator_removed(self):
        result = strip_markdown_for_tts(
            "Header A | Header B\n-------- | --------\nValue 1  | Value 2"
        )
        self.assertNotIn("----", result)
        self.assertNotIn("|", result)
        self.assertIn("Value 1", result)
        self.assertIn("Value 2", result)


if __name__ == "__main__":
    unittest.main()
