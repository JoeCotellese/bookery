# ABOUTME: Pre-search normalization of mangled EPUB metadata (CamelCase, concatenated words).
# ABOUTME: Splits garbage titles like "SteveBerry-TheTemplarLegacy" into clean search queries.

import re
from dataclasses import dataclass, replace

import wordninja

from bookery.metadata.types import BookMetadata

# Minimum length for a spaceless string to be considered "concatenated" and worth splitting.
# Shorter strings (e.g. "Dune", "1984") are left alone.
_MIN_CONCAT_LENGTH = 8

# Pre-compiled regexes for normalization detection and splitting.
_CAMEL_CASE_RE = re.compile(r"[a-z][A-Z]")
_CAMEL_LOWER_UPPER_RE = re.compile(r"([a-z\d])([A-Z])")
_CAMEL_UPPER_SEQUENCE_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_LETTER_DIGIT_RE = re.compile(r"([a-zA-Z])(\d)")
_DIGIT_LETTER_RE = re.compile(r"(\d)([a-zA-Z])")
_SEPARATOR_RE = re.compile(r"[-_]")

# Common English stop words that appear in titles but not person names.
_TITLE_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "and",
        "in",
        "on",
        "at",
        "to",
        "for",
        "by",
        "with",
        "from",
        "is",
        "was",
        "are",
        "were",
        "be",
        "been",
    }
)


def _needs_normalization(text: str) -> bool:
    """Check whether a title string looks mangled and needs normalization.

    Returns True for CamelCase-joined words, underscore-joined words,
    or long spaceless strings that are likely concatenated.
    """
    text = text.strip()
    if not text:
        return False

    # Underscores between words → needs normalization
    if "_" in text:
        return True

    # CamelCase pattern: lowercase followed by uppercase
    if _CAMEL_CASE_RE.search(text):
        return True

    # Split on hyphens to check individual segments (hyphens are valid separators)
    segments = text.split("-") if "-" in text else [text]

    return any(" " not in seg and len(seg) >= _MIN_CONCAT_LENGTH for seg in segments)


def _split_camel_case(text: str) -> list[str]:
    """Split a CamelCase string into individual words.

    Handles boundaries between:
    - lowercase → uppercase (e.g. "templarL" → "templar", "L")
    - uppercase sequence → uppercase+lowercase (e.g. "HTMLParser" → "HTML", "Parser")
    - letter → digit and digit → letter (e.g. "Fahrenheit451" → "Fahrenheit", "451")
    """
    # Insert a split marker at each boundary
    # lowercase or digit followed by uppercase
    result = _CAMEL_LOWER_UPPER_RE.sub(r"\1_SPLIT_\2", text)
    # uppercase sequence followed by uppercase+lowercase (e.g. HTMLParser → HTML_SPLIT_Parser)
    result = _CAMEL_UPPER_SEQUENCE_RE.sub(r"\1_SPLIT_\2", result)
    # letter followed by digit
    result = _LETTER_DIGIT_RE.sub(r"\1_SPLIT_\2", result)
    # digit followed by letter
    result = _DIGIT_LETTER_RE.sub(r"\1_SPLIT_\2", result)

    parts = [p for p in result.split("_SPLIT_") if p]
    return parts if parts else [text]


def _split_with_wordninja(text: str) -> str:
    """Split an all-lowercase concatenated string using wordninja's unigram model."""
    words = wordninja.split(text)
    return " ".join(words) if words else text


def split_concatenated(text: str) -> str:
    """Split a concatenated/mangled string into space-separated words.

    Pipeline:
    1. Split on hyphens and underscores into segments
    2. Apply CamelCase splitting to each segment
    3. For all-lowercase segments that are still long, use wordninja
    4. Join everything with spaces
    """
    if not _needs_normalization(text):
        return text

    # Split on structural separators (hyphens and underscores)
    raw_segments = _SEPARATOR_RE.split(text)

    words: list[str] = []
    for segment in raw_segments:
        segment = segment.strip()
        if not segment:
            continue

        # Try CamelCase splitting first
        camel_parts = _split_camel_case(segment)

        for part in camel_parts:
            # If a part is still all-lowercase and long, use wordninja
            if part.islower() and len(part) >= _MIN_CONCAT_LENGTH:
                words.append(_split_with_wordninja(part))
            else:
                words.append(part)

    return " ".join(words)


def _is_likely_person_name(text: str) -> bool:
    """Heuristic check whether a string looks like a person's name.

    Recognizes 2-3 capitalized words (including single-letter initials)
    without common stop words.
    """
    words = text.split()

    # Person names are typically 2-3 words
    if len(words) < 2 or len(words) > 3:
        return False

    # All words must be capitalized (or single-letter initials)
    for word in words:
        if not word[0].isupper():
            return False

    # No stop words allowed in a person name
    return not any(w.lower() in _TITLE_STOP_WORDS for w in words)


def _detect_author_in_title(title: str) -> tuple[str, str | None]:
    """Try to detect an author name embedded at the start of a title string.

    Checks if the first 2 or 3 words look like a person name. If so, splits
    them off as the author and returns the remainder as the title.

    Returns:
        (cleaned_title, detected_author) — author is None if not detected.
    """
    words = title.split()

    # Try 3-word name first, then 2-word
    for name_len in (3, 2):
        if len(words) <= name_len:
            continue
        candidate = " ".join(words[:name_len])
        if _is_likely_person_name(candidate):
            remaining = " ".join(words[name_len:])
            return remaining, candidate

    return title, None


# Author values that indicate missing/unknown authorship.
_UNKNOWN_AUTHORS = frozenset({"unknown", "various", "anonymous", ""})

# Structural patterns for titles with embedded author/series info.
# "Author - Title" or "Author - [Series NN] - Title"
_AUTHOR_DASH_TITLE_RE = re.compile(
    r"^(?P<author>.+?)\s+-\s+(?:\[(?P<series>[^\]]+)\]\s+-\s+)?(?P<title>.+)$"
)
# "Title by Author" — author must be 2-3 capitalized words
_TITLE_BY_AUTHOR_RE = re.compile(
    r"^(?P<title>.+?)\s+by\s+(?P<author>[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)$"
)
# Series index pattern inside brackets: "Series Name 07" or "Series Name 1"
_SERIES_INDEX_RE = re.compile(r"^(?P<name>.+?)\s+(?P<index>\d+)$")


@dataclass
class _StructuralMatch:
    """Result of detecting a structural pattern in a title string."""

    title: str
    author: str
    series: str | None = None
    series_index: float | None = None


def _parse_series_bracket(series_text: str) -> tuple[str, float | None]:
    """Parse a series bracket like 'Cotton Malone 07' into name and index."""
    m = _SERIES_INDEX_RE.match(series_text.strip())
    if m:
        return m.group("name"), float(m.group("index"))
    return series_text.strip(), None


def _detect_structural_pattern(title: str, metadata: BookMetadata) -> _StructuralMatch | None:
    """Detect 'Author - Title', 'Author - [Series] - Title', or 'Title by Author'.

    Only activates when the metadata has no valid authors — prevents false
    positives on legitimate titles like "Stand by Me".
    """
    if _has_valid_authors(metadata):
        return None

    # Try "Author - [Series] - Title" or "Author - Title"
    m = _AUTHOR_DASH_TITLE_RE.match(title)
    if m:
        candidate_author = m.group("author").strip()
        if _is_likely_person_name(candidate_author):
            series_raw = m.group("series")
            series_name = None
            series_index = None
            if series_raw:
                series_name, series_index = _parse_series_bracket(series_raw)
            return _StructuralMatch(
                title=m.group("title").strip(),
                author=candidate_author,
                series=series_name,
                series_index=series_index,
            )

    # Try "Title by Author"
    m = _TITLE_BY_AUTHOR_RE.match(title)
    if m:
        candidate_author = m.group("author").strip()
        if _is_likely_person_name(candidate_author):
            return _StructuralMatch(
                title=m.group("title").strip(),
                author=candidate_author,
            )

    return None


@dataclass
class NormalizationResult:
    """Result of normalizing a BookMetadata instance.

    Attributes:
        original: The unmodified input metadata.
        normalized: The cleaned metadata (same object as original if unmodified).
        was_modified: Whether any fields were changed.
    """

    original: BookMetadata
    normalized: BookMetadata
    was_modified: bool


def _has_valid_authors(meta: BookMetadata) -> bool:
    """Check whether metadata has meaningful author information."""
    if not meta.authors:
        return False
    return not all(a.strip().lower() in _UNKNOWN_AUTHORS for a in meta.authors)


def normalize_metadata(metadata: BookMetadata) -> NormalizationResult:
    """Normalize mangled EPUB metadata for better search queries.

    Strips invalid authors unconditionally, then applies title splitting
    (CamelCase, wordninja) and author detection.
    Returns a NormalizationResult preserving the original metadata intact.
    """
    modified = False
    title = metadata.title
    authors = list(metadata.authors)

    series = metadata.series
    series_index = metadata.series_index

    # Strip invalid authors unconditionally — before any title checks
    if not _has_valid_authors(metadata) and metadata.authors:
        authors = []
        modified = True

    # Structural patterns: "Author - Title", "Author - [Series] - Title", "Title by Author"
    structural = _detect_structural_pattern(title, metadata)
    if structural:
        title = structural.title
        authors = [structural.author]
        if structural.series:
            series = structural.series
        if structural.series_index is not None:
            series_index = structural.series_index
        modified = True
    elif _needs_normalization(title):
        # CamelCase / concatenated word normalization
        title = split_concatenated(title)
        modified = True
        if not authors:
            cleaned_title, detected_author = _detect_author_in_title(title)
            if detected_author:
                title = cleaned_title
                authors = [detected_author]

    if not modified:
        return NormalizationResult(original=metadata, normalized=metadata, was_modified=False)

    normalized = replace(
        metadata,
        title=title,
        authors=authors,
        series=series,
        series_index=series_index,
    )
    return NormalizationResult(original=metadata, normalized=normalized, was_modified=True)
