# ABOUTME: Unit tests for the ConsensusProvider metadata merger.
# ABOUTME: Verifies per-field agreement preference, priority fallback, and confidence bump.

import pytest

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.consensus import ConsensusProvider
from bookery.metadata.types import BookMetadata


class FakeProvider:
    def __init__(
        self,
        name: str,
        *,
        isbn_results: list[MetadataCandidate] | None = None,
        title_results: list[MetadataCandidate] | None = None,
        url_result: MetadataCandidate | None = None,
    ) -> None:
        self._name = name
        self._isbn = isbn_results or []
        self._title = title_results or []
        self._url = url_result
        self.isbn_calls: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
        self.isbn_calls.append(isbn)
        return list(self._isbn)

    def search_by_title_author(
        self, title: str, author: str | None = None
    ) -> list[MetadataCandidate]:
        return list(self._title)

    def lookup_by_url(self, url: str) -> MetadataCandidate | None:
        return self._url


def _cand(source: str, **meta_fields) -> MetadataCandidate:
    meta = BookMetadata(**meta_fields)
    return MetadataCandidate(
        metadata=meta,
        confidence=meta_fields.pop("confidence", 1.0) if False else 1.0,
        source=source,
        source_id=f"{source}:1",
    )


def test_single_provider_returns_its_candidate_unchanged() -> None:
    p = FakeProvider(
        "openlibrary",
        isbn_results=[_cand("openlibrary", title="Dune", authors=["Frank Herbert"])],
    )
    consensus = ConsensusProvider([p])
    result = consensus.search_by_isbn("9780441013593")
    assert len(result) == 1
    assert result[0].metadata.title == "Dune"


def test_two_providers_agreement_wins_over_priority() -> None:
    # Provider 1 (priority) says "Dune", provider 2 and 3 agree on "Dune (Special Edition)".
    p1 = FakeProvider(
        "openlibrary",
        isbn_results=[_cand("openlibrary", title="Dune", authors=["Frank Herbert"])],
    )
    p2 = FakeProvider(
        "googlebooks",
        isbn_results=[
            _cand(
                "googlebooks",
                title="Dune (Special Edition)",
                authors=["Frank Herbert"],
            )
        ],
    )
    p3 = FakeProvider(
        "other",
        isbn_results=[
            _cand(
                "other",
                title="Dune (Special Edition)",
                authors=["Frank Herbert"],
            )
        ],
    )
    consensus = ConsensusProvider([p1, p2, p3])
    result = consensus.search_by_isbn("9780441013593")
    assert len(result) == 1
    # Agreement between p2 and p3 beats p1's priority.
    assert result[0].metadata.title == "Dune (Special Edition)"


def test_no_agreement_falls_back_to_priority_order() -> None:
    p1 = FakeProvider(
        "openlibrary",
        isbn_results=[_cand("openlibrary", title="Dune", authors=["Frank Herbert"])],
    )
    p2 = FakeProvider(
        "googlebooks",
        isbn_results=[
            _cand("googlebooks", title="DUNE (messiah edition)", authors=["F. Herbert"])
        ],
    )
    consensus = ConsensusProvider([p1, p2])
    result = consensus.search_by_isbn("9780441013593")
    assert result[0].metadata.title == "Dune"
    # Per-field provenance is recorded in identifiers under provenance_<field>.
    assert result[0].metadata.identifiers["provenance_title"] == "openlibrary"


def test_missing_field_is_filled_from_other_provider() -> None:
    # Open Library has no page_count; Google Books supplies it.
    p1 = FakeProvider(
        "openlibrary",
        isbn_results=[_cand("openlibrary", title="Dune", authors=["Frank Herbert"])],
    )
    p2 = FakeProvider(
        "googlebooks",
        isbn_results=[
            _cand(
                "googlebooks",
                title="Dune",
                authors=["Frank Herbert"],
                page_count=412,
                published_date="1965",
            )
        ],
    )
    consensus = ConsensusProvider([p1, p2])
    result = consensus.search_by_isbn("9780441013593")
    merged = result[0].metadata
    assert merged.page_count == 412
    assert merged.published_date == "1965"
    assert merged.identifiers["provenance_page_count"] == "googlebooks"


def test_isbn_agreement_bumps_confidence() -> None:
    cand1 = MetadataCandidate(
        metadata=BookMetadata(title="Dune", isbn="978-0-441-01359-3"),
        confidence=0.9,
        source="openlibrary",
        source_id="OL1",
    )
    cand2 = MetadataCandidate(
        metadata=BookMetadata(title="Dune", isbn="9780441013593"),
        confidence=0.85,
        source="googlebooks",
        source_id="GB1",
    )
    p1 = FakeProvider("openlibrary", isbn_results=[cand1])
    p2 = FakeProvider("googlebooks", isbn_results=[cand2])
    consensus = ConsensusProvider([p1, p2])
    result = consensus.search_by_isbn("9780441013593")
    # max confidence (0.9) + agreement bonus (0.05).
    assert result[0].confidence == pytest.approx(0.95, abs=1e-6)


def test_failing_provider_does_not_break_consensus() -> None:
    class BoomProvider(FakeProvider):
        def search_by_isbn(self, isbn: str) -> list[MetadataCandidate]:
            raise RuntimeError("API down")

    p1 = BoomProvider("openlibrary")
    p2 = FakeProvider(
        "googlebooks",
        isbn_results=[_cand("googlebooks", title="Dune", authors=["Frank Herbert"])],
    )
    consensus = ConsensusProvider([p1, p2])
    result = consensus.search_by_isbn("9780441013593")
    assert len(result) == 1
    assert result[0].metadata.title == "Dune"


def test_empty_provider_list_rejected() -> None:
    with pytest.raises(ValueError):
        ConsensusProvider([])


def test_merged_metadata_records_source_identifier() -> None:
    p1 = FakeProvider(
        "openlibrary",
        isbn_results=[_cand("openlibrary", title="Dune", authors=["Frank Herbert"])],
    )
    p2 = FakeProvider(
        "googlebooks",
        isbn_results=[_cand("googlebooks", title="Dune", authors=["Frank Herbert"])],
    )
    consensus = ConsensusProvider([p1, p2])
    result = consensus.search_by_isbn("9780441013593")
    assert result[0].metadata.identifiers["source"] == consensus.name


def test_single_provider_passthrough_stamps_source() -> None:
    # Even with a single-provider ConsensusProvider, downstream code
    # (rematch, provenance tracking) expects ``identifiers["source"]``.
    p = FakeProvider(
        "openlibrary",
        isbn_results=[_cand("openlibrary", title="Dune", authors=["Frank Herbert"])],
    )
    consensus = ConsensusProvider([p])
    result = consensus.search_by_isbn("9780441013593")
    assert result[0].metadata.identifiers["source"] == "openlibrary"


def test_authors_list_agreement_prefers_agreed_value() -> None:
    # Two providers emit authors in a normalized "First Last" form; priority
    # provider's single-author spelling differs — agreement should win.
    p1 = FakeProvider(
        "openlibrary",
        isbn_results=[_cand("openlibrary", title="Dune", authors=["F. Herbert"])],
    )
    p2 = FakeProvider(
        "googlebooks",
        isbn_results=[_cand("googlebooks", title="Dune", authors=["Frank Herbert"])],
    )
    p3 = FakeProvider(
        "other",
        isbn_results=[_cand("other", title="Dune", authors=["Frank Herbert"])],
    )
    consensus = ConsensusProvider([p1, p2, p3])
    result = consensus.search_by_isbn("9780441013593")
    assert result[0].metadata.authors == ["Frank Herbert"]
    assert result[0].metadata.identifiers["provenance_authors"] == "googlebooks"


def test_lookup_by_url_returns_first_hit_in_priority_order() -> None:
    cand = MetadataCandidate(
        metadata=BookMetadata(title="Dune"),
        confidence=1.0,
        source="openlibrary",
        source_id="OL/works/1",
    )
    p1 = FakeProvider("openlibrary", url_result=cand)
    p2 = FakeProvider("googlebooks", url_result=None)
    consensus = ConsensusProvider([p1, p2])
    assert consensus.lookup_by_url("https://openlibrary.org/works/OL1") is cand
