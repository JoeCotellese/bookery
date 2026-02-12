# ABOUTME: Confidence scoring for metadata candidate matching.
# ABOUTME: Compares extracted EPUB metadata against candidates using weighted field similarity.

import re
from difflib import SequenceMatcher

from bookery.metadata.types import BookMetadata

# Scoring weights — must sum to 1.0
_WEIGHT_TITLE = 0.4
_WEIGHT_AUTHOR = 0.3
_WEIGHT_ISBN = 0.2
_WEIGHT_LANGUAGE = 0.1

_ISBN_STRIP_RE = re.compile(r"[\s-]")


def _normalize_author(name: str) -> str:
    """Normalize 'Last, First' to 'First Last' and lowercase."""
    name = name.strip().lower()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}"
    return name


def _normalize_isbn(isbn: str) -> str:
    """Strip hyphens and spaces from an ISBN for comparison."""
    return _ISBN_STRIP_RE.sub("", isbn)


def _string_similarity(a: str, b: str) -> float:
    """Case-insensitive string similarity using SequenceMatcher."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def score_candidate(extracted: BookMetadata, candidate: BookMetadata) -> float:
    """Score how well a candidate matches extracted EPUB metadata.

    Uses weighted comparison across title, author, ISBN, and language.
    Returns a float clamped to [0.0, 1.0].
    """
    score = 0.0

    # Title similarity (weight: 0.4)
    score += _WEIGHT_TITLE * _string_similarity(extracted.title, candidate.title)

    # Author similarity (weight: 0.3)
    # When both sides lack author info, we can't infer a match — score 0 instead of 1.
    extracted_authors = " ".join(_normalize_author(a) for a in extracted.authors)
    candidate_authors = " ".join(_normalize_author(a) for a in candidate.authors)
    if extracted_authors or candidate_authors:
        score += _WEIGHT_AUTHOR * _string_similarity(extracted_authors, candidate_authors)

    # ISBN exact match (weight: 0.2)
    if extracted.isbn and candidate.isbn:
        extracted_isbn = _normalize_isbn(extracted.isbn)
        candidate_isbn = _normalize_isbn(candidate.isbn)
        if extracted_isbn == candidate_isbn:
            score += _WEIGHT_ISBN

    # Language match (weight: 0.1)
    if (
        extracted.language
        and candidate.language
        and extracted.language.lower() == candidate.language.lower()
    ):
        score += _WEIGHT_LANGUAGE

    return max(0.0, min(1.0, score))
