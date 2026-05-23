# ABOUTME: Plain-text helpers for description fields — HTML stripping and paragraph rendering.
# ABOUTME: Storage is plain text; render-time wraps blank-line paragraphs in <p> tags.

from __future__ import annotations

import html
import re

from markupsafe import Markup, escape

_TAG_RE = re.compile(r"<[^>]+>")
# Match runs of whitespace that don't contain a blank-line break. A blank line
# is two or more newlines (possibly with intervening spaces/tabs); we keep
# those as a single "\n\n" so paragraph structure survives the strip.
_INLINE_WS_RE = re.compile(r"[ \t\r\f\v]+|\n(?!\s*\n)")
_PARAGRAPH_BREAK_RE = re.compile(r"\n\s*\n+")


def strip_html(value: str) -> str:
    """Strip HTML tags and decode entities, preserving paragraph breaks.

    Removes all tags (the simple regex matches anything between angle
    brackets), unescapes HTML entities (``&amp;`` → ``&`` etc.), collapses
    runs of inline whitespace to a single space, and normalizes paragraph
    breaks (any run of blank lines) to a single ``"\\n\\n"`` separator.

    The result is plain text suitable for writing to the catalog. Idempotent:
    running it on output that contains no markup returns the input with the
    same whitespace normalization applied.
    """
    if not value:
        return ""

    # Block-level tags should produce paragraph breaks so we don't run text
    # together. Insert a sentinel newline pair before stripping all tags.
    block_break = re.sub(
        r"</(?:p|div|section|article|header|footer|li|h[1-6]|blockquote|pre)\s*>",
        "\n\n",
        value,
        flags=re.IGNORECASE,
    )
    block_break = re.sub(r"<br\s*/?>", "\n", block_break, flags=re.IGNORECASE)

    no_tags = _TAG_RE.sub("", block_break)
    decoded = html.unescape(no_tags)

    # Normalize paragraph breaks first so the inline-whitespace pass doesn't
    # eat them. Mark paragraph breaks with a sentinel that survives the
    # subsequent whitespace collapse, then restore.
    sentinel = "\x00PARA\x00"
    with_paras = _PARAGRAPH_BREAK_RE.sub(sentinel, decoded)
    collapsed = _INLINE_WS_RE.sub(" ", with_paras)
    restored = collapsed.replace(sentinel, "\n\n")

    # Trim per-paragraph leading/trailing spaces and drop empty paragraphs.
    paragraphs = [p.strip() for p in restored.split("\n\n")]
    paragraphs = [p for p in paragraphs if p]
    return "\n\n".join(paragraphs)


def description_paragraphs(value: str | None) -> Markup:
    """Render plain-text description as HTML paragraphs.

    Splits on blank lines, escapes each paragraph for safe HTML output, and
    wraps it in ``<p>`` tags. Returns an empty :class:`Markup` for ``None``
    or empty input so the caller can branch with ``{% if %}`` cleanly.

    This is a render-time helper — it does NOT sanitize, because storage is
    already plain text (HTML is stripped on write). The escape pass is purely
    to render characters like ``&`` and ``<`` literally rather than as markup.
    """
    if not value:
        return Markup("")
    paragraphs = [p.strip() for p in value.split("\n\n")]
    paragraphs = [p for p in paragraphs if p]
    if not paragraphs:
        return Markup("")
    rendered = "\n".join(f"<p>{escape(p)}</p>" for p in paragraphs)
    return Markup(rendered)
