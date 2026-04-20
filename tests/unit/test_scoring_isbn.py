# ABOUTME: Unit tests that ISBN-10 and ISBN-13 of the same book score as equal in scoring.
# ABOUTME: Complements test_scoring.py by focusing on the ISBN-normalization behavior.

from bookery.metadata.scoring import score_candidate
from bookery.metadata.types import BookMetadata


def _meta(**kwargs) -> BookMetadata:
    defaults = {"title": "The Hobbit", "authors": ["J.R.R. Tolkien"]}
    defaults.update(kwargs)
    return BookMetadata(**defaults)


class TestIsbnEquivalence:
    def test_isbn10_matches_isbn13_of_same_book(self) -> None:
        extracted = _meta(isbn="0151446474")
        candidate = _meta(isbn="9780151446476")
        # Identical title+author, matching ISBN after canonicalization → near-perfect
        assert score_candidate(extracted, candidate) >= 0.95

    def test_different_isbns_still_penalized(self) -> None:
        extracted = _meta(isbn="0151446474")
        candidate = _meta(isbn="9999999999999")
        # Different books should score lower than the matching-ISBN case
        match_score = score_candidate(extracted, _meta(isbn="9780151446476"))
        mismatch_score = score_candidate(extracted, candidate)
        assert mismatch_score < match_score

    def test_hyphenated_variants_match(self) -> None:
        extracted = _meta(isbn="0-15-144647-4")
        candidate = _meta(isbn="978-0-15-144647-6")
        assert score_candidate(extracted, candidate) >= 0.95
