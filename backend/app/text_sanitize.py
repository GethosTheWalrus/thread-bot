"""Plain-text TTS sanitizer for Reachy speech output.

Strips Markdown syntax and emoji from LLM responses before they go to the
text-to-speech engine. The original (un-stripped) text is preserved in the
database and shown in the chat UI, which renders Markdown itself.

The rules are intentionally conservative: anything that wouldn't survive
being read aloud by Piper (asterisk emphasis, list markers, fenced code,
URL syntax, emoji glyphs, *action* markers) is removed, but ordinary
punctuation, capitalization, and spacing are preserved.
"""

from __future__ import annotations

import re


_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_UNDERSCORE_RE = re.compile(r"__([^_\n][^_\n]*)__")
_BOLD_ASTERISK_RE = re.compile(r"\*\*([^*\n][^*\n]*)\*\*")
_ITALIC_UNDERSCORE_RE = re.compile(r"(?<!_)_(?!_)([^_\n]+?)(?<!_)_(?!_)")
_ITALIC_ASTERISK_RE = re.compile(r"(?<!\*)\*(?!\*)([^*\n]+?)(?<!\*)\*(?!\*)")
_ACTION_MARKER_RE = re.compile(r"(?<![\w*])\*([^*\n]{1,80}?)\*(?![\w*])")
_HEADER_PREFIX_RE = re.compile(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+")
_BLOCKQUOTE_RE = re.compile(r"(?m)^[ \t]{0,3}>[ \t]?")
_LIST_MARKER_RE = re.compile(r"(?m)^[ \t]{0,3}(?:[-*+]|\d+[.)])\s+")
_HORIZONTAL_RULE_RE = re.compile(r"(?m)^[ \t]{0,3}(?:[-*_][ \t]*){3,}\s*$")
def _strip_table_blocks(text: str) -> str:
    """Detect contiguous Markdown table blocks and rewrite them for TTS.

    A table block is a sequence of 2+ adjacent lines where the first row
    has at least one pipe and the second row is a dash separator. All rows
    in the block have their internal pipes collapsed to spaces.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    pipe_row = re.compile(r"^[ \t]*(?=[^|\n]*\|)[^|\n]*(?:\|[^|\n]*)+\s*$")
    sep_row = re.compile(r"^\s*\|?[ \t]*:?-{2,}:?[ \t]*(\|[ \t]*:?-{2,}:?[ \t]*)+\|?\s*$")
    while i < n:
        if (
            i + 1 < n
            and pipe_row.match(lines[i] or "")
            and sep_row.match(lines[i + 1] or "")
        ):
            # Table block. Consume all contiguous pipe rows.
            out.append(lines[i].replace("|", " "))
            out.append("")  # separator is dropped
            i += 2
            while i < n and pipe_row.match(lines[i] or ""):
                out.append(lines[i].replace("|", " "))
                i += 1
            if i < n and lines[i] == "":
                # Preserve the blank line after a table block.
                out.append("")
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\n]*)\)")
_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]*)\)")
_HTML_TAG_RE = re.compile(r"</?[A-Za-z][^>\n]*>")
_LATEX_INLINE_RE = re.compile(r"\$([^$\n]+)\$")
_LATEX_BLOCK_RE = re.compile(r"\$\$[\s\S]*?\$\$")

# Common emoji ranges. We do not try to be exhaustive (Unicode keeps growing);
# these cover BMP symbols, dingbats, emoticons, transport, geometric shapes,
# supplemental symbols & pictographs, and the SMP emoji block.
_EMOJI_RANGES = (
    (0x2600, 0x26FF),    # Misc Symbols
    (0x2700, 0x27BF),    # Dingbats
    (0x1F300, 0x1F5FF),  # Misc Symbols & Pictographs
    (0x1F600, 0x1F64F),  # Emoticons
    (0x1F680, 0x1F6FF),  # Transport & Map
    (0x1F700, 0x1F77F),  # Alchemical
    (0x1F780, 0x1F7FF),  # Geometric Shapes Extended
    (0x1F800, 0x1F8FF),  # Supplemental Arrows-C
    (0x1F900, 0x1F9FF),  # Supplemental Symbols & Pictographs
    (0x1FA00, 0x1FAFF),  # Symbols & Pictographs Extended-A
    (0x1F1E6, 0x1F1FF),  # Regional indicator symbols (flag pairs)
)


def _is_emoji(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch)
    for start, end in _EMOJI_RANGES:
        if start <= cp <= end:
            return True
    return False


def _emoji_regex() -> re.Pattern[str]:
    parts: list[str] = []
    for start, end in _EMOJI_RANGES:
        # Use a range with codepoints as escape sequences.
        parts.append(f"\\U000{start:05X}-\\U000{end:05X}")
    # Allow ZWJ-joined sequences (e.g. 👨‍👩‍👧) and drop trailing variation
    # selectors (U+FE0F, U+FE0E) that often dangle after an emoji was removed.
    pattern = (
        "[" + "".join(parts) + "]+(?:\\u200D[" + "".join(parts) + "]+)*[\\uFE0F\\uFE0E]?"
    )
    return re.compile(pattern)


_EMOJI_MATCH_RE = _emoji_regex()


def _collapse_whitespace(text: str) -> str:
    # Remove any leftover back-to-back blank lines created by stripping blocks.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def strip_markdown_for_tts(text: str) -> str:
    """Return a plain-text version of `text` safe to send to TTS."""
    if not text:
        return ""

    cleaned = text

    # 1. Fenced code blocks (``` ... ```) — drop entirely, including
    #    the line they sit on, since code rarely makes sense read aloud.
    cleaned = _FENCED_CODE_RE.sub("", cleaned)

    # 2. LaTeX blocks ($$ ... $$) — drop entirely.
    cleaned = _LATEX_BLOCK_RE.sub("", cleaned)

    # 3. Markdown tables: drop the separator line, collapse pipes inside
    #    data rows to spaces so TTS reads them as ordinary text.
    cleaned = _strip_table_blocks(cleaned)

    # 4. Image syntax ![alt](url) — keep the alt text if any, drop the URL.
    cleaned = _IMAGE_RE.sub(r"\1", cleaned)

    # 5. Link syntax [text](url) — keep the link text, drop the URL.
    cleaned = _LINK_RE.sub(r"\1", cleaned)

    # 6. Inline code `code` — keep the code text, drop the backticks.
    cleaned = _INLINE_CODE_RE.sub(r"\1", cleaned)

    # 7. Inline LaTeX $x$ — drop entirely.
    cleaned = _LATEX_INLINE_RE.sub("", cleaned)

    # 8. HTML tags.
    cleaned = _HTML_TAG_RE.sub("", cleaned)

    # 9. Headers (line-leading # / ## / ### etc.).
    cleaned = _HEADER_PREFIX_RE.sub("", cleaned)

    # 10. Blockquote markers (line-leading >).
    cleaned = _BLOCKQUOTE_RE.sub("", cleaned)

    # 11. List markers (line-leading - * + 1. 2) etc.).
    cleaned = _LIST_MARKER_RE.sub("", cleaned)

    # 12. Horizontal rules.
    cleaned = _HORIZONTAL_RULE_RE.sub("", cleaned)

    # 13. Bold: __word__ and **word**.
    cleaned = _BOLD_UNDERSCORE_RE.sub(r"\1", cleaned)
    cleaned = _BOLD_ASTERISK_RE.sub(r"\1", cleaned)

    # 14. Action markers: *smiles* / *waves hello* (italic-ish emphasis
    #     around short phrases). Only remove a single pair of asterisks so we
    #     do not collapse genuine **bold** that survived above.
    cleaned = _ACTION_MARKER_RE.sub(r"\1", cleaned)

    # 15. Italic: _word_ and *word*. Order matters — we run italic last so
    #     it does not eat underscores that the bold rules already cleaned up.
    cleaned = _ITALIC_UNDERSCORE_RE.sub(r"\1", cleaned)
    cleaned = _ITALIC_ASTERISK_RE.sub(r"\1", cleaned)

    # 16. Emoji.
    cleaned = _EMOJI_MATCH_RE.sub("", cleaned)

    # 17. Whitespace cleanup.
    cleaned = _collapse_whitespace(cleaned)

    return cleaned
