# ABOUTME: Unit tests for serializing an enrich candidate into/out of the Apply form.
# ABOUTME: Covers round-trip fidelity, byte/Path field exclusion, and robust failure to None.

from pathlib import Path

from bookery.metadata.candidate import MetadataCandidate
from bookery.metadata.types import BookMetadata
from bookery.web.candidate_payload import deserialize_candidate, serialize_candidate


def _candidate() -> MetadataCandidate:
    return MetadataCandidate(
        metadata=BookMetadata(
            title="Dune",
            authors=["Frank Herbert", "Brian Herbert"],
            isbn="9780441172719",
            publisher="Ace",
            description="A desert planet epic.",
            series="Dune",
            series_index=1.0,
            subjects=["Science Fiction", "Classic"],
            identifiers={"google": "abc123", "isbn": "9780441172719"},
            cover_url="https://example.test/cover.jpg",
        ),
        confidence=0.92,
        source="Open Library",
        source_id="OL:M/123",
    )


class TestRoundTrip:
    def test_round_trip_preserves_fields(self):
        restored = deserialize_candidate(serialize_candidate(_candidate()))

        assert restored is not None
        assert restored.confidence == 0.92
        assert restored.source == "Open Library"
        assert restored.source_id == "OL:M/123"
        meta = restored.metadata
        assert meta.title == "Dune"
        assert meta.authors == ["Frank Herbert", "Brian Herbert"]
        assert meta.isbn == "9780441172719"
        assert meta.publisher == "Ace"
        assert meta.description == "A desert planet epic."
        assert meta.series == "Dune"
        assert meta.series_index == 1.0
        assert meta.subjects == ["Science Fiction", "Classic"]
        assert meta.identifiers == {"google": "abc123", "isbn": "9780441172719"}
        assert meta.cover_url == "https://example.test/cover.jpg"

    def test_cover_image_bytes_are_dropped(self):
        candidate = _candidate()
        candidate.metadata.cover_image = b"\xff\xd8\xff binary jpeg bytes"

        restored = deserialize_candidate(serialize_candidate(candidate))

        assert restored is not None
        # cover_image is re-fetched from cover_url at apply time, never carried.
        assert restored.metadata.cover_image is None

    def test_source_path_is_dropped(self):
        candidate = _candidate()
        candidate.metadata.source_path = Path("/library/dune.epub")

        restored = deserialize_candidate(serialize_candidate(candidate))

        assert restored is not None
        assert restored.metadata.source_path is None


class TestDeserializeFailsSafe:
    def test_empty_string_returns_none(self):
        assert deserialize_candidate("") is None

    def test_non_json_returns_none(self):
        assert deserialize_candidate("not json at all") is None

    def test_wrong_shape_returns_none(self):
        # Valid JSON but not the expected object shape.
        assert deserialize_candidate("[1, 2, 3]") is None
        assert deserialize_candidate('{"foo": "bar"}') is None

    def test_missing_title_returns_none(self):
        payload = (
            '{"confidence": 0.5, "source": "x", "source_id": "1", "metadata": {"authors": ["A"]}}'
        )
        assert deserialize_candidate(payload) is None

    def test_out_of_range_confidence_returns_none(self):
        payload = (
            '{"confidence": 1.5, "source": "x", "source_id": "1", "metadata": {"title": "T"}}'
        )
        assert deserialize_candidate(payload) is None

    def test_unknown_metadata_key_returns_none(self):
        payload = (
            '{"confidence": 0.5, "source": "x", "source_id": "1", '
            '"metadata": {"title": "T", "bogus_field": 1}}'
        )
        assert deserialize_candidate(payload) is None
