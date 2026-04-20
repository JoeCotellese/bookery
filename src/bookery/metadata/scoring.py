# ABOUTME: Confidence scoring for metadata candidate matching.
# ABOUTME: Compares extracted EPUB metadata against candidates using weighted field similarity.

from difflib import SequenceMatcher

from bookery.core.dedup import normalize_isbn as _canonical_isbn
from bookery.metadata.types import BookMetadata

# Match weights — must sum to 1.0
_WEIGHT_TITLE = 0.4
_WEIGHT_AUTHOR = 0.3
_WEIGHT_ISBN = 0.2
_WEIGHT_LANGUAGE = 0.1

# Completeness bonus — max added on top of the match score.
_COMPLETENESS_BONUS = 0.10

# Per-field weights within the completeness bonus (must sum to 1.0).
_COMPLETENESS_FIELDS: dict[str, float] = {
    "description": 0.40,
    "isbn": 0.30,
    "authors": 0.15,
    "language": 0.10,
    "publisher": 0.05,
}

def _normalize_author(name: str) -> str:
    """Normalize 'Last, First' to 'First Last' and lowercase."""
    name = name.strip().lower()
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        name = f"{parts[1]} {parts[0]}"
    return name


def _normalize_isbn(isbn: str) -> str:
    """Canonicalize ISBN for comparison (strip separators, convert ISBN-10 to ISBN-13)."""
    return _canonical_isbn(isbn)


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
    Weights from uncomparable fields (missing on one or both sides) are
    redistributed proportionally across comparable fields so that a perfect
    match on available fields scores near 1.0.
    Returns a float clamped to [0.0, 1.0].
    """
    comparable: list[tuple[float, float]] = []

    # Title is always comparable (always present on both sides).
    comparable.append((_WEIGHT_TITLE, _string_similarity(extracted.title, candidate.title)))

    # Author is comparable if either side has authors.
    # When both sides lack author info, we can't infer a match — skip entirely.
    extracted_authors = " ".join(_normalize_author(a) for a in extracted.authors)
    candidate_authors = " ".join(_normalize_author(a) for a in candidate.authors)
    if extracted_authors or candidate_authors:
        comparable.append(
            (_WEIGHT_AUTHOR, _string_similarity(extracted_authors, candidate_authors))
        )

    # ISBN is comparable only if both sides have one.
    if extracted.isbn and candidate.isbn:
        extracted_isbn = _normalize_isbn(extracted.isbn)
        candidate_isbn = _normalize_isbn(candidate.isbn)
        isbn_score = 1.0 if extracted_isbn == candidate_isbn else 0.0
        comparable.append((_WEIGHT_ISBN, isbn_score))

    # Language is comparable only if both sides have one.
    if extracted.language and candidate.language:
        lang_score = 1.0 if extracted.language.lower() == candidate.language.lower() else 0.0
        comparable.append((_WEIGHT_LANGUAGE, lang_score))

    # Redistribute: normalize weights so comparable fields sum to 1.0.
    available_weight = sum(w for w, _ in comparable)
    score = sum(w / available_weight * s for w, s in comparable) if available_weight > 0 else 0.0

    score += completeness_bonus(candidate)

    return max(0.0, min(1.0, score))


def completeness_bonus(candidate: BookMetadata) -> float:
    """Calculate a small bonus based on how many metadata fields are populated.

    Rewards candidates with richer metadata so they float above sparse stubs
    when match scores are otherwise tied. Returns a value in [0.0, _COMPLETENESS_BONUS].
    """
    filled = 0.0
    for field_name, weight in _COMPLETENESS_FIELDS.items():
        value = getattr(candidate, field_name, None)
        if value:
            filled += weight
    return _COMPLETENESS_BONUS * filled
