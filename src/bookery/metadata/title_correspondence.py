# ABOUTME: Predicate deciding whether a candidate's title describes the same book as ours.
# ABOUTME: Gates series acceptance so provider series can't ride in on an unrelated match (#303).

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from bookery.metadata.normalizer import split_concatenated

# Minimum SequenceMatcher ratio between comparison keys for two titles to be
# considered the same book. Tuned against the #301 audit: unrelated pairs there
# score below 0.4, while edition/subtitle variants of the same book stay above.
DEFAULT_MIN_SIMILARITY = 0.62

# Token-containment fallback for subtitle and edition drift ("Foo" vs "Foo: The
# Uncut Version"). Needs real overlap, not one shared numeral, hence the floor.
_MIN_CONTAINMENT = 0.8
_MIN_OVERLAP_TOKENS = 2

# "Book 17 - Remnant", "Book 2 - The Force Unleashed II", "Vol. 3: Foo".
# The separator class covers hyphen, en dash and em dash, written as escapes so
# the two dashes stay distinguishable in source.
_BOOK_PREFIX_RE = re.compile(
    r"^\s*(?:book|bk|vol|volume|part)\s*\.?\s*#?\s*"
    r"(?P<index>\d+(?:\.\d+)?)\b\s*"
    "[-\u2013\u2014:.]*"
    r"\s*",
    re.IGNORECASE,
)

_PUNCT_RE = re.compile(r"[^\w\s]+")
_WS_RE = re.compile(r"\s+")
_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+")

# Function words carry no identifying signal, so they're excluded from the
# token-overlap rule — otherwise "of the" alone could clear the floor.
_STOP_WORDS = frozenset(
    {"the", "a", "an", "of", "and", "in", "on", "at", "to", "for", "by", "with", "from"}
)


@dataclass(frozen=True)
class Correspondence:
    """Whether a candidate title describes the same book, with a showable reason."""

    corresponds: bool
    similarity: float
    reason: str


def comparison_key(title: str) -> str:
    """Reduce a title to a form safe to compare across sources.

    Runs the shared normalizer first so mangled filenames-as-titles
    ("SteveBerry-TheTemplarLegacy") compare as words rather than as one blob,
    then strips punctuation, case, and a leading article.
    """
    text = split_concatenated(title or "").lower()
    text = _PUNCT_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    return _LEADING_ARTICLE_RE.sub("", text)


def _tokens(key: str) -> set[str]:
    return {t for t in key.split() if t not in _STOP_WORDS}


def leading_book_number(title: str) -> float | None:
    """Return N from a "Book N - ..." style title prefix, or None.

    Used to refuse a series position that only agrees with the numbering our
    own filename already carried — that agreement is a coincidence of the
    query, not evidence about where the book sits in a series.
    """
    match = _BOOK_PREFIX_RE.match(title or "")
    return float(match.group("index")) if match else None


def titles_correspond(
    book_title: str,
    candidate_title: str,
    *,
    minimum: float = DEFAULT_MIN_SIMILARITY,
) -> Correspondence:
    """Decide whether ``candidate_title`` names the same book as ``book_title``.

    An overall match confidence is not evidence about the series field
    specifically: a weak query ("Book 17 - Remnant") can return a
    threshold-clearing candidate for an entirely different book whose series
    then gets written verbatim. This asks the narrower question directly.
    """
    if not (book_title or "").strip() or not (candidate_title or "").strip():
        return Correspondence(
            corresponds=False,
            similarity=0.0,
            reason="cannot compare titles: one side is missing a title",
        )

    key_a = comparison_key(book_title)
    key_b = comparison_key(candidate_title)
    ratio = SequenceMatcher(None, key_a, key_b).ratio()

    tokens_a, tokens_b = _tokens(key_a), _tokens(key_b)
    overlap = tokens_a & tokens_b
    containment = 0.0
    if tokens_a and tokens_b:
        containment = len(overlap) / min(len(tokens_a), len(tokens_b))

    contained = len(overlap) >= _MIN_OVERLAP_TOKENS and containment >= _MIN_CONTAINMENT
    similarity = max(ratio, containment) if contained else ratio

    if ratio >= minimum or contained:
        return Correspondence(
            corresponds=True,
            similarity=similarity,
            reason=f"candidate title {candidate_title!r} matches (similarity {similarity:.2f})",
        )
    return Correspondence(
        corresponds=False,
        similarity=similarity,
        reason=(
            f"candidate title {candidate_title!r} does not correspond to "
            f"{book_title!r} (similarity {similarity:.2f})"
        ),
    )
