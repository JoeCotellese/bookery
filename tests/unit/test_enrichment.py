# ABOUTME: Unit tests for the multi-provider enrichment helper used by the web UI.
# ABOUTME: Covers ISBN/URL/title-author dispatch, ordering, empty groups, and detect helpers.

from bookery.core.enrichment import (
    ProviderResult,
    dispatch_from_form,
    looks_like_isbn,
    looks_like_url,
    multi_provider_search,
    normalize_isbn,
)
from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata


class _Provider:
    """Minimal MetadataProvider double for helper-level tests."""

    def __init__(
        self,
        name: str,
        *,
        by_isbn: list[MetadataCandidate] | None = None,
        by_title_author: list[MetadataCandidate] | None = None,
        by_url: MetadataCandidate | None = None,
    ) -> None:
        self.name = name
        self._by_isbn = by_isbn or []
        self._by_title_author = by_title_author or []
        self._by_url = by_url
        self.isbn_calls: list[str] = []
        self.title_author_calls: list[tuple[str, str | None]] = []
        self.url_calls: list[str] = []

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        self.isbn_calls.append(isbn)
        return list(self._by_isbn)

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]:
        self.title_author_calls.append((title, author))
        return list(self._by_title_author)

    def lookup_by_url(self, url: str) -> MetadataCandidate | None:
        self.url_calls.append(url)
        return self._by_url


def _cand(title: str, confidence: float) -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(title=title),
        confidence=confidence,
        source="fake",
        source_id="fake:1",
    )


class TestLooksLikeIsbn:
    def test_isbn13_digits(self):
        assert looks_like_isbn("9780441172719")

    def test_isbn10_digits(self):
        assert looks_like_isbn("0441172717")

    def test_isbn10_with_x_checksum(self):
        assert looks_like_isbn("044117271X")

    def test_isbn_with_hyphens(self):
        assert looks_like_isbn("978-0-441-17271-9")

    def test_too_short(self):
        assert not looks_like_isbn("123")

    def test_free_text(self):
        assert not looks_like_isbn("Dune Frank Herbert")


class TestLooksLikeUrl:
    def test_https(self):
        assert looks_like_url("https://openlibrary.org/works/OL1234W")

    def test_http(self):
        assert looks_like_url("http://example.com/path")

    def test_www_prefix(self):
        assert looks_like_url("www.example.com")

    def test_free_text_is_not_url(self):
        assert not looks_like_url("Dune Frank Herbert")


class TestNormalizeIsbn:
    def test_strips_hyphens_and_whitespace(self):
        assert normalize_isbn("978-0-441-17271-9") == "9780441172719"
        assert normalize_isbn(" 044117271X ") == "044117271X"


class TestMultiProviderSearch:
    def test_isbn_dispatch_hits_every_provider(self):
        a = _Provider("A", by_isbn=[_cand("a", 0.5)])
        b = _Provider("B", by_isbn=[_cand("b", 0.7)])

        results = multi_provider_search({"a": a, "b": b}, isbn="9780441172719")

        assert [r.name for r in results] == ["A", "B"]
        assert a.isbn_calls == ["9780441172719"]
        assert b.isbn_calls == ["9780441172719"]
        assert a.title_author_calls == []
        assert b.title_author_calls == []
        assert a.url_calls == []

    def test_title_author_dispatch(self):
        p = _Provider("A")
        multi_provider_search({"a": p}, title="Dune", author="Frank Herbert")
        assert p.title_author_calls == [("Dune", "Frank Herbert")]
        assert p.isbn_calls == []

    def test_title_only_dispatch_passes_none_author(self):
        p = _Provider("A")
        multi_provider_search({"a": p}, title="Dune")
        assert p.title_author_calls == [("Dune", None)]

    def test_url_dispatch_returns_single_candidate(self):
        cand = _cand("via url", 0.8)
        p = _Provider("A", by_url=cand)
        results = multi_provider_search({"a": p}, url="https://example.com")
        assert p.url_calls == ["https://example.com"]
        assert results[0].candidates == [cand]

    def test_url_dispatch_with_no_match_yields_empty_group(self):
        p = _Provider("A", by_url=None)
        results = multi_provider_search({"a": p}, url="https://example.com")
        assert results[0].is_empty
        assert results[0].count == 0

    def test_candidates_sorted_by_confidence_desc(self):
        p = _Provider(
            "A",
            by_title_author=[_cand("low", 0.1), _cand("high", 0.9), _cand("mid", 0.5)],
        )
        results = multi_provider_search({"a": p}, title="x")
        assert [c.metadata.title for c in results[0].candidates] == ["high", "mid", "low"]

    def test_preserves_provider_order(self):
        a = _Provider("Alpha")
        b = _Provider("Beta")
        c = _Provider("Gamma")
        results = multi_provider_search({"a": a, "b": b, "c": c}, title="x")
        assert [r.name for r in results] == ["Alpha", "Beta", "Gamma"]


class TestDispatchFromForm:
    def test_isbn_field_wins_over_title(self):
        d = dispatch_from_form("9780441172719", "ignored title", "ignored author")
        assert d.isbn == "9780441172719"
        assert d.url is None
        assert d.title is None
        assert d.author is None

    def test_isbn_field_normalizes_hyphens(self):
        d = dispatch_from_form("978-0-441-17271-9", "")
        assert d.isbn == "9780441172719"

    def test_isbn_like_title_routes_to_isbn(self):
        d = dispatch_from_form("", "9780441172719")
        assert d.isbn == "9780441172719"

    def test_url_in_title_routes_to_url(self):
        d = dispatch_from_form("", "https://openlibrary.org/works/OL1")
        assert d.url == "https://openlibrary.org/works/OL1"
        assert d.isbn is None
        assert d.title is None

    def test_title_and_author_route_separately(self):
        d = dispatch_from_form("", "Dune", "Frank Herbert")
        assert d.title == "Dune"
        assert d.author == "Frank Herbert"

    def test_title_only_route(self):
        d = dispatch_from_form("", "Dune")
        assert d.title == "Dune"
        assert d.author is None

    def test_empty_inputs_produce_empty_dispatch(self):
        d = dispatch_from_form("", "")
        assert d.is_empty
        assert d.isbn is None
        assert d.url is None
        assert d.title is None
        assert d.author is None


class TestProviderResult:
    def test_count_and_empty_flag(self):
        empty = ProviderResult(name="X", candidates=[])
        assert empty.is_empty
        assert empty.count == 0

        full = ProviderResult(name="X", candidates=[_cand("a", 0.5)])
        assert not full.is_empty
        assert full.count == 1
